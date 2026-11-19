# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Cura setting resolver.

Cura profiles only store *overrides*. The value Cura actually slices with is
found by walking a stack of containers (user -> quality_changes -> quality ->
material -> machine definition -> fdmprinter) and, for most settings,
evaluating a Python expression that depends on other settings. This module
re-implements enough of that to get concrete numbers out of a profile.
"""
from __future__ import annotations

import ast
import configparser
import gzip
import io
import json
import math
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

DATA_DIR = os.path.join(os.path.dirname(__file__), "data", "cura")

class CuraError(Exception):
    pass


# --------------------------------------------------------------------------
# Resource discovery
# --------------------------------------------------------------------------

def candidate_resource_dirs() -> List[str]:
    """Places an installed Cura keeps its resources folder (newest guess first)."""
    home = os.path.expanduser("~")
    c = [
        "/Applications/UltiMaker Cura.app/Contents/Resources/share/cura/resources",
        "/Applications/Ultimaker Cura.app/Contents/Resources/share/cura/resources",
        "/var/lib/flatpak/app/com.ultimaker.cura/current/active/files/share/cura/resources",
        os.path.join(home, ".local/share/flatpak/app/com.ultimaker.cura/current/active/files/share/cura/resources"),
        "/usr/share/cura/resources",
        "/usr/local/share/cura/resources",
        r"C:\Program Files\UltiMaker Cura\share\cura\resources",
    ]
    return [p for p in c if os.path.isdir(os.path.join(p, "definitions"))]


class Resources:
    """Cura definitions + global qualities. Uses bundled copies, optionally a real install."""

    def __init__(self, extra_dir: Optional[str] = None):
        self.dirs: List[str] = []
        if extra_dir:
            if not os.path.isdir(os.path.join(extra_dir, "definitions")):
                raise CuraError(f"Not a Cura resources folder (no definitions/): {extra_dir}")
            self.dirs.append(extra_dir)
        self.dirs.append(DATA_DIR)
        self._def_cache: Dict[str, dict] = {}
        self._quality_cache: Optional[List[Tuple[dict, dict, Dict[str, str]]]] = None
        with open(os.path.join(DATA_DIR, "generic_materials.json"), encoding="utf-8") as fh:
            self.generic_materials: Dict[str, dict] = json.load(fh)

    # definitions ----------------------------------------------------------
    def _find_def(self, def_id: str) -> Optional[str]:
        for d in self.dirs:
            for sub in ("definitions", "extruders"):
                p = os.path.join(d, sub, def_id + ".def.json")
                if os.path.isfile(p):
                    return p
        return None

    def load_def(self, def_id: str) -> dict:
        if def_id not in self._def_cache:
            p = self._find_def(def_id)
            if not p:
                raise CuraError(f"Unknown Cura machine/extruder definition '{def_id}'")
            with open(p, encoding="utf-8") as fh:
                self._def_cache[def_id] = json.load(fh)
        return self._def_cache[def_id]

    def def_chain(self, def_id: str) -> List[Tuple[str, dict]]:
        """[(id, json)] from the root (fdmprinter / fdmextruder) down to def_id."""
        chain = []
        seen = set()
        cur: Optional[str] = def_id
        while cur and cur not in seen:
            seen.add(cur)
            d = self.load_def(cur)
            chain.append((cur, d))
            cur = d.get("inherits")
        return list(reversed(chain))

    def machine_metadata(self, def_id: str) -> dict:
        md: dict = {}
        for _, d in self.def_chain(def_id):
            md.update(d.get("metadata", {}))
        return md

    def machines(self) -> List[Tuple[str, str]]:
        """(id, display name) of every visible machine definition."""
        out = {}
        for d in self.dirs:
            folder = os.path.join(d, "definitions")
            for fn in os.listdir(folder):
                if not fn.endswith(".def.json"):
                    continue
                mid = fn[:-9]
                if mid in out:
                    continue
                try:
                    with open(os.path.join(folder, fn), encoding="utf-8") as fh:
                        js = json.load(fh)
                except (OSError, ValueError):
                    continue
                if js.get("metadata", {}).get("visible", True) and js.get("metadata", {}).get("type") != "extruder":
                    out[mid] = js.get("name", mid)
        out.setdefault("fdmprinter", "Custom FFF printer (fdmprinter)")
        return sorted(out.items(), key=lambda kv: kv[1].lower())

    def quality_definition(self, machine_id: str) -> str:
        md = self.machine_metadata(machine_id)
        if str(md.get("has_machine_quality", False)).lower() == "true" or md.get("has_machine_quality") is True:
            return md.get("quality_definition", machine_id)
        return "fdmprinter"

    # qualities, intents, variants --------------------------------------------
    def _all_containers(self) -> List["InstCfg"]:
        """Every quality / intent / variant container: an installed Cura's files first, then the bundled set."""
        if self._quality_cache is None:
            out: List[InstCfg] = []
            seen = set()
            for d in self.dirs:
                if d == DATA_DIR:
                    continue
                for sub in ("quality", "intent", "variants"):
                    for dp, _, files in os.walk(os.path.join(d, sub)):
                        for fn in files:
                            if not fn.endswith(".inst.cfg") or fn in seen:
                                continue
                            seen.add(fn)
                            try:
                                with open(os.path.join(dp, fn), encoding="utf-8") as fh:
                                    ic = read_inst_cfg_text(fh.read(), fn[:-9])
                            except Exception:
                                continue
                            out.append(ic)
            try:
                with gzip.open(os.path.join(DATA_DIR, "containers.json.gz"), "rt", encoding="utf-8") as fh:
                    recs = json.load(fh)
            except (OSError, ValueError):
                recs = []
            for r in recs:
                if r["id"] + ".inst.cfg" in seen:
                    continue
                md = {"type": r.get("t", "quality")}
                for src, dst in (("q", "quality_type"), ("m", "material"), ("var", "variant"),
                                 ("i", "intent_category"), ("hw", "hardware_type")):
                    if src in r:
                        md[dst] = r[src]
                if r.get("g"):
                    md["global_quality"] = "True"
                out.append(InstCfg(general={"definition": r.get("d") or "", "name": r.get("n") or ""},
                                   metadata=md, values=r.get("v") or {}, source=r["id"]))
            self._quality_cache = out
        return self._quality_cache

    def _qualities(self, qd: str) -> List["InstCfg"]:
        return [ic for ic in self._all_containers() if ic.type == "quality" and ic.general.get("definition") == qd]

    def quality_types(self, machine_id: str) -> List[str]:
        return sorted({ic.metadata.get("quality_type") for ic in self._qualities(self.quality_definition(machine_id))
                       if ic.metadata.get("quality_type") and ic.metadata.get("quality_type") != "not_supported"})

    def material_type(self, material_id: Optional[str]) -> Optional[str]:
        if not material_id:
            return None
        mid = material_id.lower()
        for cand in (mid, re.sub(r"_175$", "", mid)):
            if cand in self.generic_materials:
                return self.generic_materials[cand]["material"]
        return None

    def find_quality(self, machine_id: str, quality_type: str, material: Optional[str] = None,
                     variant: Optional[str] = None) -> List["InstCfg"]:
        """[global quality, material/nozzle specific quality] as far as they exist (the order Cura stacks them)."""
        cands = [ic for ic in self._qualities(self.quality_definition(machine_id))
                 if ic.metadata.get("quality_type") == quality_type]
        glob_q = [ic for ic in cands if str(ic.metadata.get("global_quality", "")).lower() == "true"]
        rest = [ic for ic in cands if ic not in glob_q]
        if variant is not None and any(ic.metadata.get("variant") for ic in rest):
            rest = [ic for ic in rest if ic.metadata.get("variant") in (variant, None)]
        specific: List[InstCfg] = []
        if material:
            base = re.sub(r"_175$", "", material.lower())
            exact = [ic for ic in rest if ic.metadata.get("material") in (material, base)]
            mtype = self.material_type(material)
            same_type = [ic for ic in rest if mtype and self.material_type(ic.metadata.get("material")) == mtype]
            specific = exact or same_type
        if not specific:
            specific = [ic for ic in rest if not ic.metadata.get("material")]
        return glob_q[:1] + specific[:1]

    def variant(self, machine_id: str, wanted: Optional[str] = None) -> Optional["InstCfg"]:
        """The nozzle variant container for this printer (by id, by name, or the printer's preferred one)."""
        md = self.machine_metadata(machine_id)
        chain = [i for i, _ in self.def_chain(machine_id)]
        cands = [ic for ic in self._all_containers() if ic.type == "variant"
                 and ic.metadata.get("hardware_type", "nozzle") == "nozzle" and ic.general.get("definition") in chain]
        if not cands:
            return None
        cands.sort(key=lambda ic: -chain.index(ic.general.get("definition")))  # most specific printer first
        for want in (wanted, md.get("preferred_variant_name")):
            if not want:
                continue
            for ic in cands:
                if ic.source == want or ic.general.get("name") == want:
                    return ic
        return None

    def material_values(self, material_id: str, machine_id: str) -> Dict[str, Any]:
        """What Cura's material profile contributes for this printer (generic materials only)."""
        gm = self.generic_materials.get(material_id)
        if not gm:
            return {}
        out: Dict[str, Any] = dict(gm.get("settings") or {})
        for def_id, _ in self.def_chain(machine_id):
            out.update((gm.get("machines") or {}).get(def_id, {}))
        out["material_diameter"] = gm["diameter"]
        out["material_type"] = gm["material"]
        out["material_brand"] = "Generic"
        return out

    def touchable_keys(self, machine_id: str) -> set:
        """Settings some quality, intent, nozzle or material profile of this printer may set behind our back."""
        qd = self.quality_definition(machine_id)
        chain = {i for i, _ in self.def_chain(machine_id)} | {qd}
        keys = set()
        for ic in self._all_containers():
            if ic.general.get("definition") in chain:
                keys.update(ic.values)
        for gm in self.generic_materials.values():
            keys.update(gm.get("settings") or {})
            for v in (gm.get("machines") or {}).values():
                keys.update(v)
        keys.add("material_diameter")
        return keys

    def setting_definitions(self, machine_id: str) -> Dict[str, dict]:
        """Flattened {key: {type, default_value, value, ...}} with machine overrides applied."""
        base: Dict[str, dict] = {}

        def walk(node: dict, category: str):
            for k, v in node.items():
                entry = {kk: vv for kk, vv in v.items() if kk != "children"}
                entry["category"] = category
                base[k] = entry
                if "children" in v:
                    walk(v["children"], category)

        for root_id in ("fdmprinter", "fdmextruder"):
            root = self.load_def(root_id)
            for cat, cv in root.get("settings", {}).items():
                walk(cv.get("children", {}), cat)

        def apply_overrides(def_id: str):
            for _, d in self.def_chain(def_id):
                for k, ov in d.get("overrides", {}).items():
                    tgt = base.setdefault(k, {"type": "str", "default_value": None, "category": "machine_settings"})
                    tgt.update(ov)

        apply_overrides(machine_id)
        trains = self.machine_metadata(machine_id).get("machine_extruder_trains", {})
        if "0" in trains:
            try:
                apply_overrides(trains["0"])
            except CuraError:
                pass
        return base


# --------------------------------------------------------------------------
# .inst.cfg handling
# --------------------------------------------------------------------------

@dataclass
class InstCfg:
    general: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, str] = field(default_factory=dict)
    values: Dict[str, str] = field(default_factory=dict)
    source: str = ""

    @property
    def type(self) -> str:
        return self.metadata.get("type", "")

    @property
    def position(self) -> Optional[str]:
        return self.metadata.get("position")


def read_inst_cfg_text(text: str, source: str = "") -> InstCfg:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # keep case
    cp.read_string(text)
    ic = InstCfg(source=source)
    for sec, tgt in (("general", ic.general), ("metadata", ic.metadata), ("values", ic.values)):
        if cp.has_section(sec):
            for k, v in cp.items(sec):
                tgt[k] = v
    return ic


def write_inst_cfg(ic: InstCfg) -> str:
    out = io.StringIO()
    for sec, src in (("general", ic.general), ("metadata", ic.metadata), ("values", ic.values)):
        out.write(f"[{sec}]\n")
        for k, v in src.items():
            v = str(v)
            if "\n" in v:
                # configparser continuation lines: indent every following line
                v = v.replace("\n", "\n\t")
            out.write(f"{k} = {v}\n")
        out.write("\n")
    return out.getvalue()


@dataclass
class CuraProfile:
    """Everything we could pull out of a Cura file."""
    name: str = "Imported"
    machine: Optional[str] = None
    quality_type: Optional[str] = None
    material: Optional[str] = None
    variant: Optional[str] = None
    global_changes: Dict[str, str] = field(default_factory=dict)
    extruder_changes: Dict[str, str] = field(default_factory=dict)
    machine_changes: Dict[str, str] = field(default_factory=dict)  # definition_changes
    extra_extruders: int = 0
    notes: List[str] = field(default_factory=list)


def _apply(ic: InstCfg, prof: CuraProfile):
    """Merge one container into the profile by its type/position."""
    t = ic.type
    if t == "definition_changes":
        prof.machine_changes.update(ic.values)
        return
    if t not in ("quality_changes", "user", ""):
        return
    pos = ic.position
    if pos is None:
        prof.global_changes.update(ic.values)
        prof.name = ic.general.get("name", prof.name)
        prof.quality_type = ic.metadata.get("quality_type", prof.quality_type)
        d = ic.general.get("definition")
        if d and not prof.machine:
            prof.machine = d
    elif pos == "0":
        prof.extruder_changes.update(ic.values)
    else:
        prof.extra_extruders = max(prof.extra_extruders, int(pos))



MAX_ZIP_MEMBER = 50_000_000


def zread(zf, name: str) -> bytes:
    """Read one file from a project/profile zip, refusing sizes no slicer writes (a damaged or hostile file)."""
    if zf.getinfo(name).file_size > MAX_ZIP_MEMBER:
        raise ValueError(f"'{name}' inside the file is far larger than any slicer profile. Nothing was written.")
    return zf.read(name)


def read_cura_file(path: str) -> CuraProfile:
    """Read .curaprofile (zip), single .inst.cfg, or a Cura .3mf project."""
    prof = CuraProfile(name=os.path.splitext(os.path.basename(path))[0])
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if any(n.startswith("Cura/") for n in names):
                return _read_3mf(zf, prof)
            # .curaprofile: one inst.cfg per container; global first
            containers = [read_inst_cfg_text(zread(zf, n).decode("utf-8"), n) for n in names]
            for ic in sorted(containers, key=lambda c: c.position is not None):
                _apply(ic, prof)
    else:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        ic = read_inst_cfg_text(text, path)
        _apply(ic, prof)
    if prof.extra_extruders:
        prof.notes.append(f"Profile has {prof.extra_extruders + 1} extruders; only extruder 1 is converted.")
    return prof


def _read_3mf(zf: zipfile.ZipFile, prof: CuraProfile) -> CuraProfile:
    from urllib.parse import unquote
    files = {n: n for n in zf.namelist() if n.startswith("Cura/")}
    by_id: Dict[str, InstCfg] = {}
    stacks = []
    for n in files:
        base = unquote(os.path.basename(n))
        if n.endswith(".inst.cfg"):
            by_id[base[:-9]] = read_inst_cfg_text(zread(zf, n).decode("utf-8"), n)
        elif n.endswith(".global.cfg") or n.endswith(".extruder.cfg"):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            cp.optionxform = str
            cp.read_string(zread(zf, n).decode("utf-8"))
            stacks.append((n, cp))
    for n, cp in stacks:
        is_global = n.endswith(".global.cfg")
        conts = dict(cp.items("containers")) if cp.has_section("containers") else {}
        meta = dict(cp.items("metadata")) if cp.has_section("metadata") else {}
        pos = meta.get("position")
        if not is_global and pos not in (None, "0"):
            prof.extra_extruders = max(prof.extra_extruders, int(pos))
            continue
        ordered = [conts[k] for k in sorted(conts, key=int)]  # 0 = user ... 7 = definition
        if is_global:
            if ordered:
                prof.machine = ordered[-1]
            prof.name = cp.get("general", "name", fallback=prof.name)
        for cid in reversed(ordered):  # lowest priority first
            ic = by_id.get(cid)
            if ic is None:
                continue
            t = ic.type
            if t == "quality" and is_global:
                prof.quality_type = ic.metadata.get("quality_type", prof.quality_type)
            if t == "quality_changes" and is_global:
                prof.quality_type = ic.metadata.get("quality_type", prof.quality_type)
                prof.name = ic.general.get("name", prof.name)
            if t in ("quality_changes", "user"):
                (prof.global_changes if is_global else prof.extruder_changes).update(ic.values)
            elif t == "definition_changes":
                prof.machine_changes.update(ic.values)
        if not is_global and len(ordered) >= 8:
            # extruder stack: user, quality_changes, intent, quality, material, variant, definition_changes, definition
            mat, var = ordered[4], ordered[5]
            prof.material = None if mat.startswith("empty") else mat
            prof.variant = None if var.startswith("empty") else var
    return prof


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

_SAFE_BUILTINS = {
    "max": max, "min": min, "round": round, "int": int, "float": float, "sum": sum,
    "any": any, "all": all, "len": len, "map": map, "abs": abs, "str": str,
    "bool": bool, "list": list, "sorted": sorted, "True": True, "False": False,
    "None": None, "filter": filter, "range": range, "set": set, "tuple": tuple,
}


def _check_expr(expr: str):
    """Reject anything that is not a plain expression over names/calls (no dunder tricks)."""
    tree = ast.parse(expr, mode="eval")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise CuraError(f"Refusing unsafe expression: {expr!r}")
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            raise CuraError(f"Refusing unsafe expression: {expr!r}")
        if isinstance(node, (ast.Lambda,)):
            raise CuraError(f"Refusing unsafe expression: {expr!r}")
    return compile(tree, "<cura>", "eval")


class Resolver:
    """Lazily evaluates every Cura setting for one (single-extruder) stack."""

    def __init__(self, defs: Dict[str, dict], layers: List[Dict[str, Any]]):
        self.defs = defs
        self.layers = layers  # lowest priority first, each {key: raw}
        self.cache: Dict[str, Any] = {}
        self.stack: List[str] = []
        self.errors: Dict[str, str] = {}
        self._code: Dict[str, Any] = {}

    def raw(self, key: str) -> Tuple[Any, str]:
        """(raw value, origin) from the highest layer that defines key."""
        for name, layer in reversed(list(zip(LAYERS_FOR_EVAL, self.layers))):
            if key in layer:
                return layer[key], name
        d = self.defs.get(key)
        if d is None:
            return None, "unknown"
        if "value" in d:
            v = d["value"]
            return ("=" + v) if isinstance(v, str) else v, "definition"
        return d.get("default_value"), "definition"

    def origin(self, key: str) -> str:
        return self.raw(key)[1]

    def _cast(self, key: str, v: Any) -> Any:
        t = self.defs.get(key, {}).get("type")
        try:
            if t == "float":
                return float(v)
            if t == "int":
                return int(round(float(v))) if not isinstance(v, bool) else int(v)
            if t == "bool":
                if isinstance(v, str):
                    return v.strip().lower() in ("true", "1", "yes")
                return bool(v)
            if t in ("extruder", "optional_extruder"):
                return str(v)
        except (TypeError, ValueError):
            return v
        return v

    def _parse_literal(self, key: str, raw: Any) -> Any:
        if not isinstance(raw, str):
            return self._cast(key, raw)
        t = self.defs.get(key, {}).get("type")
        s = raw.strip()
        if t in ("float", "int"):
            try:
                return self._cast(key, float(s))
            except ValueError:
                return self._cast(key, self._eval(key, s))
        if t == "bool":
            return self._cast(key, s)
        if t == "[int]":
            try:
                return ast.literal_eval(s) if s else []
            except (ValueError, SyntaxError):
                return []
        return raw

    def _eval(self, key: str, expr: str) -> Any:
        code = self._code.get(expr)
        if code is None:
            code = self._code[expr] = _check_expr(expr)
        ns = _Namespace(self)
        return eval(code, {"__builtins__": _SAFE_BUILTINS, "math": math}, ns)

    def get(self, key: str) -> Any:
        if key in self.cache:
            return self.cache[key]
        if key in self.stack:
            raise CuraError("Circular setting reference: " + " -> ".join(self.stack + [key]))
        self.stack.append(key)
        try:
            raw, _ = self.raw(key)
            try:
                if isinstance(raw, str) and raw.startswith("="):
                    expr = raw[1:].strip()
                    if (self.defs.get(key, {}).get("type") in ("enum", "str") and expr.isidentifier()
                            and expr not in self.defs and expr not in ("True", "False", "None")):
                        val = expr  # some machine files write enum values unquoted
                    else:
                        val = self._cast(key, self._eval(key, expr))
                else:
                    val = self._parse_literal(key, raw)
            except CuraError:
                raise
            except Exception as exc:  # formula failed: fall back to default_value
                self.errors[key] = f"{type(exc).__name__}: {exc}"
                val = self._cast(key, self.defs.get(key, {}).get("default_value"))
        finally:
            self.stack.pop()
        self.cache[key] = val
        return val

    def all_values(self, keys: Optional[Iterable[str]] = None) -> Dict[str, Any]:
        return {k: self.get(k) for k in (keys if keys is not None else self.defs)}


LAYERS_FOR_EVAL = ["definition_changes", "variant", "material", "quality", "quality_changes", "user"]
QC_LAYER = LAYERS_FOR_EVAL.index("quality_changes")


class _Namespace(dict):
    """Name lookup for Cura expressions: setting keys + Cura's helper functions."""

    def __init__(self, r: Resolver):
        super().__init__()
        self.r = r

    def __missing__(self, name: str):
        r = self.r
        helpers = {
            "resolveOrValue": lambda k: r.get(k),
            "extruderValue": lambda ext, k: r.get(k),
            "extruderValues": lambda k: [r.get(k)],
            "extruderValueFromContainer": lambda ext, k, ctx=None: r.get(k),
            "valueFromContainer": lambda k, idx=None: r.get(k),
            "anyExtruderWithMaterial": lambda prop: "0",
            "anyExtruderNrWithOrDefault": lambda k: "0",
            "defaultExtruderPosition": lambda: "0",
        }
        if name in helpers:
            return helpers[name]
        if name in r.defs:
            return r.get(name)
        raise KeyError(name)  # KeyError lets Python fall through to builtins/globals


def _generic_material_for(mat_id: str, generics: Dict[str, dict], diameter: Optional[float]) -> str:
    """Map any Cura material id (e.g. 'creality_pla', 'generic_petg_175') to a bundled generic one."""
    mid = (mat_id or "").lower()
    want_175 = diameter is not None and abs(diameter - 1.75) < 0.1
    if mid in generics:
        if want_175 and not mid.endswith("_175") and mid + "_175" in generics:
            return mid + "_175"
        return mid
    words = re.split(r"[^a-z0-9]+", mid)
    order = sorted({g.split("_")[1] for g in generics if g.count("_") >= 1}, key=len, reverse=True)
    kind = next((k for k in order if k in words), "pla")
    cand = f"generic_{kind}_175" if want_175 else f"generic_{kind}"
    if cand in generics:
        return cand
    return f"generic_{kind}" if f"generic_{kind}" in generics else "generic_pla_175"


def _layer_from_values(values: Dict[str, str]) -> Dict[str, Any]:
    return dict(values)


@dataclass
class ResolvedCura:
    values: Dict[str, Any]
    explicit: Dict[str, Any]          # keys the user/profile actually set
    machine: str
    quality_type: Optional[str]
    material: Optional[str]
    resolver: Resolver
    notes: List[str]


def resolve_profile(prof: CuraProfile, res: Resources, machine: Optional[str] = None,
                    material: Optional[str] = None, quality_type: Optional[str] = None) -> ResolvedCura:
    notes = list(prof.notes)
    machine_id = machine or prof.machine or "fdmprinter"
    try:
        res.load_def(machine_id)
    except CuraError:
        notes.append(f"Machine definition '{machine_id}' not found; using generic fdmprinter.")
        machine_id = "fdmprinter"
    # A profile's definition is the *quality definition* (e.g. creality_base), not the exact printer.
    defs = res.setting_definitions(machine_id)
    md = res.machine_metadata(machine_id)

    qtype = quality_type or prof.quality_type or md.get("preferred_quality_type") or "normal"
    mat_id = material or prof.material or md.get("preferred_material") or "generic_pla"
    # Cura appends _175 for 1.75 mm machines
    dia_guess = None
    trains = md.get("machine_extruder_trains", {})
    if "0" in trains:
        try:
            for _, d in res.def_chain(trains["0"]):
                dv = d.get("overrides", {}).get("material_diameter", {}).get("default_value")
                if dv:
                    dia_guess = float(dv)
        except CuraError:
            pass
    base_mat = _generic_material_for(mat_id, res.generic_materials, dia_guess)
    material_layer = {k: v for k, v in res.material_values(base_mat, machine_id).items() if k in defs}
    if material_layer:
        if not (prof.global_changes.get("material_print_temperature") or prof.extruder_changes.get("material_print_temperature")):
            notes.append(f"Temperatures not set in the profile; using Cura's generic '{base_mat}' values for this printer "
                         f"({material_layer.get('default_material_print_temperature', 0):g} / "
                         f"{material_layer.get('default_material_bed_temperature', 0):g} °C). Check them.")
    else:
        notes.append(f"Material '{mat_id}' unknown; temperatures fall back to Cura defaults.")

    var = res.variant(machine_id, prof.variant)
    variant_layer = {k: v for k, v in (var.values if var else {}).items() if k in defs}
    variant_name = var.general.get("name") if var else None
    quality_layer: Dict[str, Any] = {}
    found = res.find_quality(machine_id, qtype, material=base_mat, variant=variant_name)
    for q in found:
        quality_layer.update(q.values)
    if not found and qtype not in ("not_supported", "empty"):
        notes.append(f"Base quality '{qtype}' not found for {machine_id}; layer height etc. come from the profile only.")

    qc = dict(prof.global_changes)
    qc.update(prof.extruder_changes)  # single extruder: per-extruder values win
    layers = [_layer_from_values(prof.machine_changes), variant_layer, material_layer, quality_layer, qc, {}]
    r = Resolver(defs, layers)
    values = r.all_values()
    explicit = {k: values.get(k) for k in qc if k in defs}
    unknown = [k for k in qc if k not in defs]
    if unknown:
        notes.append("Settings not known to this Cura version (ignored): " + ", ".join(sorted(unknown)))
    if r.errors:
        notes.append(f"{len(r.errors)} Cura formulas could not be evaluated and used their default value "
                     f"(e.g. {', '.join(sorted(r.errors)[:4])}).")
    return ResolvedCura(values, explicit, machine_id, qtype, mat_id, r, notes)


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def setting_version() -> int:
    with open(os.path.join(DATA_DIR, "definitions", "fdmprinter.def.json"), encoding="utf-8") as fh:
        return int(json.load(fh)["metadata"].get("setting_version", 27))


def format_cura_value(v: Any) -> str:
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        s = f"{v:.6f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return str(v)


def choose_quality(res: Resources, machine: str, layer_height: float, quality_type: Optional[str] = None,
                   material: Optional[str] = None, variant: Optional[str] = None) -> Tuple[str, List[str]]:
    """Pick the quality type a custom profile is based on: the one with the closest layer height.

    With a material/nozzle given (a real printer in an installed Cura) only quality types that
    exist for that combination are considered, otherwise Cura greys the profile out.
    """
    notes: List[str] = []
    available = res.quality_types(machine)
    md = res.machine_metadata(machine)
    if material:
        dia = None
        base = _generic_material_for(material, res.generic_materials, None)
        var = res.variant(machine, variant)
        vname = var.general.get("name") if var else None
        usable = [t for t in available if len(res.find_quality(machine, t, material=base, variant=vname)) > 1]
        if usable:
            available = usable
    if quality_type and quality_type in available:
        qt = quality_type
    else:
        lh = float(layer_height or 0.2)
        best, best_d = None, 1e9
        for t in available:
            qlh = None
            for q in res.find_quality(machine, t):
                raw = q.values.get("layer_height")
                try:
                    qlh = float(raw)
                except (TypeError, ValueError):
                    pass
            d = abs((qlh if qlh is not None else 0.2) - lh)
            if d < best_d:
                best, best_d = t, d
        qt = best or md.get("preferred_quality_type") or "normal"
        if not available:
            notes.append(f"No quality types known for '{machine}'; using '{qt}'. Cura may refuse the import.")
    return qt, notes


def formula_deps(expr: str, defs: Dict[str, dict]) -> set:
    """Setting keys a Cura formula reads directly."""
    deps = set()
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return deps
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in defs:
            deps.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in defs:
            deps.add(node.value)
    return deps


def minimal_changes(res: Resources, machine: str, quality_type: str, values: Dict[str, Any],
                    material: Optional[str] = None) -> Dict[str, Any]:
    """Leave out values Cura derives from *other values in this same profile*.

    Only those are safe to drop: anything else could be changed behind our back by the
    material, nozzle or quality profile the user has selected in Cura, so it is written
    explicitly and the converted numbers always win.
    """
    strv = {k: format_cura_value(v) for k, v in values.items()}
    prof = CuraProfile(machine=machine, quality_type=quality_type, global_changes=dict(strv))
    base = resolve_profile(prof, res, machine=machine, material=material, quality_type=quality_type)
    defs = base.resolver.defs
    layers = base.resolver.layers
    kept = dict(layers[QC_LAYER])
    touch = res.touchable_keys(machine)
    pinned: set = set()

    def same(a: Any, b: Any) -> bool:
        if isinstance(a, float) or isinstance(b, float):
            try:
                return abs(float(a) - float(b)) < 1e-4
            except (TypeError, ValueError):
                return False
        return a == b

    for k in list(kept):
        expr = defs.get(k, {}).get("value")
        if not isinstance(expr, str) or k in touch or k in pinned:
            continue
        deps = formula_deps(expr, defs) - {k}
        if not deps or not deps <= (set(kept) - {k}):
            continue
        trial = dict(kept)
        trial.pop(k)
        lay = list(layers)
        lay[QC_LAYER] = trial
        try:
            if same(Resolver(defs, lay).get(k), base.values.get(k)):
                kept = trial
                pinned |= deps
        except CuraError:
            pass
    return {k: values[k] for k in values if k in kept}


def build_curaprofile(name: str, values: Dict[str, Any], res: Resources, machine: str,
                      qt: str) -> bytes:
    qdef = res.quality_definition(machine)
    sv = setting_version()
    ic = InstCfg(
        general={"version": "4", "name": name, "definition": qdef},
        metadata={"type": "quality_changes", "quality_type": qt, "setting_version": str(sv),
                  "intent_category": "default"},
        values={k: format_cura_value(v) for k, v in values.items()},
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "profile"
        zf.writestr(f"{qdef}_{safe}", write_inst_cfg(ic))
    return buf.getvalue()
