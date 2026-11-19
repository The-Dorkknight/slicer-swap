# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""PrusaSlicer and OrcaSlicer <-> canonical.

PrusaSlicer keeps presets as INI (one file, or a bundle with [print:..]
sections). OrcaSlicer keeps one JSON file per preset (process / filament /
machine) with an 'inherits' chain. Both share the same G-code macro language
and many option types, so they live together here.
"""
from __future__ import annotations

import configparser
import glob
import io
import json
import math
import os
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from . import gcode
from .cura_engine import zread
from .mapping import (FLAVOR, INFILL, INFILL_ALIASES, ROWS, SEAM, SEAM_ALIASES, SUPPORT_PATTERN, SURFACE,
                      Report, enum_to_canon, enum_to_native)

IDX = {"prusa": 4, "orca": 5}
NAME = {"prusa": "PrusaSlicer", "orca": "OrcaSlicer"}

# PrusaSlicer settings added after 2.7.2 (the oldest version SlicerSwap was run against). An older PrusaSlicer
# loads the preset and ignores these. Versions checked against the PrintConfig.cpp of each release tag.
PRUSA_ADDED_IN = {"chamber_temperature": "2.8.0", "chamber_minimal_temperature": "2.8.0",
                  "first_layer_infill_speed": "2.9.1"}


def _ver(v: str) -> List[int]:
    return [int(x) for x in re.findall(r"\d+", (v or "").split("+")[0].split("-")[0])[:3]]


def too_new_for(slicer: str, native: Dict[str, Dict[str, Any]], version: Optional[str] = None) -> List[Tuple[str, str]]:
    """[(key, version it appeared in)] for written settings the target version does not have (all newer ones if unknown)."""
    if slicer != "prusa":
        return []
    have = _ver(version) if version else None
    return sorted((k, PRUSA_ADDED_IN[k]) for sec in native.values() for k in sec
                  if k in PRUSA_ADDED_IN and (not have or have < _ver(PRUSA_ADDED_IN[k])))


# FloatOrPercent options: what the percentage is relative to
PCT_BASE = {
    "prusa": {
        "external_perimeter_speed": "perimeter_speed", "small_perimeter_speed": "perimeter_speed",
        "solid_infill_speed": "infill_speed", "top_solid_infill_speed": "solid_infill_speed",
        "support_material_interface_speed": "support_material_speed", "first_layer_speed": "perimeter_speed",
        "first_layer_infill_speed": "infill_speed",
        "support_material_xy_spacing": "external_perimeter_extrusion_width",
        "first_layer_height": "layer_height",
    },
    "orca": {
        "sparse_infill_acceleration": "default_acceleration", "internal_solid_infill_acceleration": "default_acceleration",
        "bridge_acceleration": "outer_wall_acceleration", "initial_layer_travel_speed": "travel_speed",
        "small_perimeter_speed": "outer_wall_speed",
    },
}

# Keys never worth reporting as "not converted"
IGNORE_PREFIX = ("compatible_", "print_host", "printhost", "inherits", "post_process", "notes", "filament_notes",
                 "printer_notes", "thumbnails", "output_filename", "filename_format", "host_type", "printer_vendor",
                 "printer_model", "printer_variant", "bed_custom", "default_print_profile", "default_filament_profile",
                 "print_settings_id", "filament_settings_id", "printer_settings_id", "physical_printer", "renamed_from",
                 "setting_id", "from", "instantiation", "version", "type", "name", "is_custom", "user_id", "updated_time",
                 "filament_vendor", "filament_cost", "filament_density", "filament_colour", "extruder_colour",
                 "wipe_tower", "prime_tower", "gcode_substitutions", "template_custom_gcode", "color_change_gcode",
                 "pause_print_gcode", "upward_compatible", "bbl_", "scan_first_layer", "machine_load_filament",
                 "machine_unload_filament", "auxiliary_fan", "printer_structure", "nozzle_type", "printable_area",
                 "bed_exclude_area", "head_wrap", "extruder_clearance", "best_object_pos", "print_compatible",
                 "filament_ids", "filament_settings", "different_settings", "include", "base_id", "alias")


# ---------------------------------------------------------------------------
# value helpers
# ---------------------------------------------------------------------------

def _types(slicer: str) -> Dict[str, dict]:
    return gcode.native_types(slicer)


def _first(v: Any) -> Any:
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _num(v: Any) -> Optional[float]:
    v = _first(v)
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v).strip().strip('"')
    if s in ("", "nil"):
        return None
    if "," in s and not s.endswith("%"):
        s = s.split(",")[0]
    try:
        return float(s.rstrip("%"))
    except ValueError:
        return None


def _bool(v: Any) -> Optional[bool]:
    v = _first(v)
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().split(",")[0].strip().lower()
    if s == "nil":
        return None
    return s in ("1", "true", "yes")


def _str(v: Any) -> Optional[str]:
    v = _first(v)
    if v is None:
        return None
    s = str(v)
    return s.split(";")[0].strip().strip('"') if ";" in s and "\n" not in s else s.strip().strip('"')


class Native:
    """A merged native config with percent resolution."""

    def __init__(self, slicer: str, cfg: Dict[str, Any]):
        self.slicer = slicer
        self.cfg = cfg
        self.used: set = set()

    def has(self, k: str) -> bool:
        return k in self.cfg and _first(self.cfg[k]) not in (None, "nil", "")

    def raw(self, k: str) -> Any:
        self.used.add(k)
        return self.cfg.get(k)

    def num(self, k: str, default: Optional[float] = None) -> Optional[float]:
        raw = self.raw(k)
        r = _first(raw)
        val = _num(raw)
        if val is None:
            return default
        if isinstance(r, str) and r.strip().endswith("%"):
            base = PCT_BASE.get(self.slicer, {}).get(k)
            if base is None and ("width" in k or "line_width" in k):
                base = "nozzle_diameter"
            if base is not None:
                b = self.width(base) if "width" in base else self.num(base)
                if b is not None:
                    return val / 100.0 * b
        return val

    def width(self, k: str) -> Optional[float]:
        """Extrusion width; 0 or missing = slicer auto (about 1.125 x nozzle)."""
        v = self.num(k)
        noz = self.num("nozzle_diameter", 0.4) or 0.4
        if v is None or v == 0:
            if self.slicer == "prusa" and k != "extrusion_width":
                d = self.num("extrusion_width")
                if d:
                    return d
            return round(1.125 * noz, 3)
        return v

    def bool(self, k: str, default: Optional[bool] = None) -> Optional[bool]:
        b = _bool(self.raw(k))
        return default if b is None else b

    def str(self, k: str, default: Optional[str] = None) -> Optional[str]:
        s = _str(self.raw(k))
        return default if s is None else s


# ---------------------------------------------------------------------------
# reading files
# ---------------------------------------------------------------------------

def _prusa_unescape(v: str) -> str:
    out, i = [], 0
    while i < len(v):
        c = v[i]
        if c == "\\" and i + 1 < len(v):
            n = v[i + 1]
            out.append({"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"'}.get(n, "\\" + n))
            i += 2
            continue
        out.append(c)
        i += 1
    s = "".join(out)
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"' and "\n" in s:
        s = s[1:-1]
    return s


def _parse_ini_lines(text: str) -> List[Tuple[Optional[str], str, str]]:
    """(section, key, value) triples; tolerates '; key = value' 3MF metadata lines."""
    out, sec = [], None
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("[") and s.endswith("]") and "=" not in s:
            sec = s[1:-1].strip()
            continue
        if s.startswith(";"):
            s = s[1:].strip()
            if "=" not in s:
                continue
        elif s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        out.append((sec, k.strip(), _prusa_unescape(v.strip())))
    return out


def prusa_vendor_dirs() -> List[str]:
    home = os.path.expanduser("~")
    cands = [os.path.join(home, ".config/PrusaSlicer"), os.path.join(home, ".PrusaSlicer"),
             os.path.join(home, "Library/Application Support/PrusaSlicer"),
             os.path.join(home, ".var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer"),
             os.path.join(os.environ.get("APPDATA", ""), "PrusaSlicer")]
    return [c for c in cands if os.path.isdir(c)]


def orca_dirs() -> List[str]:
    home = os.path.expanduser("~")
    cands = [os.path.join(home, ".config/OrcaSlicer"), os.path.join(home, "Library/Application Support/OrcaSlicer"),
             os.path.join(home, ".var/app/io.github.softfever.OrcaSlicer/config/OrcaSlicer"),
             os.path.join(os.environ.get("APPDATA", ""), "OrcaSlicer")]
    return [c for c in cands if os.path.isdir(c)]


def read_prusa(paths: List[str], rep: Report) -> Dict[str, Any]:
    """Accepts exported config .ini, config bundles, and PrusaSlicer .3mf projects."""
    sections: Dict[str, Dict[str, str]] = {}   # "print:Name" -> values
    flat: Dict[str, str] = {}
    selected: Dict[str, str] = {}
    for p in paths:
        if zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as zf:
                cfg_name = next((n for n in zf.namelist() if n.lower().endswith("slic3r_pe.config")), None)
                if not cfg_name:
                    raise ValueError(f"{os.path.basename(p)}: no PrusaSlicer config inside this 3MF")
                text = zread(zf, cfg_name).decode("utf-8", "replace")
        else:
            with open(p, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        for sec, k, v in _parse_ini_lines(text):
            if sec is None:
                flat[k] = v
            elif sec == "presets":
                selected[k] = v
            else:
                sections.setdefault(sec, {})[k] = v
    if flat and not sections:
        return flat

    # bundle: resolve inherits, pick the selected presets
    vendor: Dict[str, Dict[str, str]] = {}

    def lookup(kind: str, name: str) -> Optional[Dict[str, str]]:
        key = f"{kind}:{name}"
        if key in sections:
            return sections[key]
        if not vendor:
            for d in prusa_vendor_dirs():
                for f in glob.glob(os.path.join(d, "vendor", "*.ini")):
                    try:
                        with open(f, encoding="utf-8", errors="replace") as fh:
                            text_v = fh.read()
                        for sec, k, v in _parse_ini_lines(text_v):
                            if sec and ":" in sec:
                                vendor.setdefault(sec, {})[k] = v
                    except OSError:
                        pass
            vendor.setdefault("__loaded__", {})
        return vendor.get(key)

    def resolved(kind: str, name: str, depth: int = 0) -> Dict[str, str]:
        sec = lookup(kind, name)
        if sec is None:
            rep.note(f"PrusaSlicer preset '{name}' ({kind}) not found; its inherited values are missing.")
            return {}
        out: Dict[str, str] = {}
        for parent in [x.strip().strip('"') for x in sec.get("inherits", "").split(";") if x.strip()]:
            if depth < 20:
                out.update(resolved(kind, parent, depth + 1))
        out.update(sec)
        return out

    merged = dict(flat)
    for kind, alias in (("printer", "printer"), ("filament", "filament"), ("print", "print")):
        name = selected.get(alias)
        if not name:
            cands = [s.split(":", 1)[1] for s in sections if s.startswith(kind + ":") and not s.split(":", 1)[1].startswith("*")]
            if not cands:
                continue
            name = cands[0]
            if len(cands) > 1:
                rep.note(f"Bundle has {len(cands)} {kind} presets; converting '{name}'. "
                         "Export a single preset to choose another.")
        merged.update(resolved(kind, name.split(";")[0]))
    return merged


def _index_json_dir(dirs: List[str]) -> Dict[str, str]:
    """preset name -> path, by file name and by the 'name' field inside."""
    idx: Dict[str, str] = {}
    for d in dirs:
        for f in glob.glob(os.path.join(d, "**", "*.json"), recursive=True):
            idx.setdefault(os.path.splitext(os.path.basename(f))[0], f)
            try:
                with open(f, encoding="utf-8") as fh:
                    head = fh.read(2048)
                m = re.search(r'"name"\s*:\s*"((?:[^"\\]|\\.)*)"', head)
                if m:
                    idx.setdefault(json.loads('"' + m.group(1) + '"'), f)
            except (OSError, ValueError):
                pass
    return idx


def _orca_system_index() -> Dict[str, str]:
    """name -> path for every Orca preset JSON we can find on this computer."""
    return _index_json_dir(orca_dirs())


def read_orca(paths: List[str], rep: Report, extra_dirs: Optional[List[str]] = None) -> Dict[str, Any]:
    """Accepts process/filament/machine .json, .orca_printer/.orca_filament/.zip bundles, Orca .3mf projects."""
    docs: List[dict] = []
    for p in paths:
        if zipfile.is_zipfile(p):
            with zipfile.ZipFile(p) as zf:
                proj = next((n for n in zf.namelist() if n.endswith("project_settings.config")), None)
                if proj:
                    d = json.loads(zread(zf, proj).decode("utf-8"))
                    d.setdefault("type", "project")
                    docs.append(d)
                    continue
                for n in zf.namelist():
                    if n.endswith(".json") and "bundle_structure" not in n:
                        try:
                            docs.append(json.loads(zread(zf, n).decode("utf-8")))
                        except ValueError:
                            pass
        else:
            with open(p, encoding="utf-8") as fh:
                docs.append(json.load(fh))
    by_name = {d.get("name"): d for d in docs if d.get("name")}
    sys_idx: Optional[Dict[str, str]] = None
    extra_idx: Dict[str, str] = _index_json_dir(extra_dirs or [])

    def find(name: str) -> Optional[dict]:
        nonlocal sys_idx
        if name in by_name:
            return by_name[name]
        f = extra_idx.get(name)
        if f is None:
            if sys_idx is None:
                sys_idx = _orca_system_index()
            f = sys_idx.get(name)
        if f:
            try:
                with open(f, encoding="utf-8") as fh:
                    d = json.load(fh)
                by_name[name] = d
                return d
            except (OSError, ValueError):
                return None
        return None

    def resolved(d: dict, depth: int = 0) -> dict:
        out: dict = {}
        parent = d.get("inherits")
        if parent and depth < 20:
            pd = find(parent)
            if pd is None:
                rep.note(f"Orca preset '{d.get('name')}' inherits '{parent}', which wasn't found on this computer. "
                         "Only the values stored in the file are used; point 'Orca profiles folder' at OrcaSlicer's "
                         "resources/profiles (or system) folder to fill the rest.")
            else:
                out.update(resolved(pd, depth + 1))
        out.update(d)
        return out

    order = {"machine": 0, "filament": 1, "process": 2, "project": 3}
    merged: Dict[str, Any] = {}
    for d in sorted(docs, key=lambda x: order.get(x.get("type"), 4)):
        merged.update(resolved(d))
    return merged


# ---------------------------------------------------------------------------
# native -> canonical
# ---------------------------------------------------------------------------

def to_canon(slicer: str, cfg: Dict[str, Any], rep: Report, name: str = "Imported") -> Dict[str, Any]:
    n = Native(slicer, cfg)
    C: Dict[str, Any] = {"name": name}
    col = IDX[slicer]
    for row in ROWS:
        canon, _sec, kind, key = row[0], row[1], row[2], row[col]
        if not key or not n.has(key):
            continue
        if kind == "bool":
            C[canon] = n.bool(key)
        elif kind == "int":
            v = n.num(key)
            C[canon] = int(round(v)) if v is not None else None
        elif kind == "str":
            C[canon] = n.str(key)
        elif kind == "gcode":
            raw = n.raw(key)
            C[canon] = (raw[0] if raw else "") if isinstance(raw, list) else (raw or "")
        elif "line_width" in canon or canon == "line_width":
            C[canon] = n.width(key)
        elif kind == "pct" and _types(slicer).get(key, {}).get("type") == "coFloatOrPercent":
            raw = _first(n.raw(key))
            v = _num(raw)
            if v is not None and not str(raw).strip().endswith("%"):
                # absolute mm: turn into a percentage of the (inner wall) line width
                w = n.width("perimeter_extrusion_width" if slicer == "prusa" else "inner_wall_line_width") or 0.45
                v = round(v / w * 100.0, 2)
            C[canon] = v
        else:
            C[canon] = n.num(key)
    # 0 = "same as retraction speed" in both slicers
    if C.get("deretract_speed") in (0, 0.0) and C.get("retract_speed"):
        C["deretract_speed"] = C["retract_speed"]
    if slicer == "prusa":
        _prusa_specials(n, C, rep)
    else:
        _orca_specials(n, C, rep)
    # filament presets may override the printer's retraction
    for canon, pk, ok in FILAMENT_RETRACT:
        key = pk if slicer == "prusa" else ok
        if key and n.has(key):
            val = n.bool(key) if canon == "retract_layer_change" else n.num(key)
            if val is not None:
                if C.get(canon) != val:
                    rep.note(f"Filament preset overrides {canon}: {C.get(canon)} -> {val}")
                C[canon] = val

    # effective shell layers: Prusa/Orca also enforce a minimum thickness
    lh = C.get("layer_height") or 0.2
    for lay, th in (("top_layers", "top_thickness_min"), ("bottom_layers", "bottom_thickness_min")):
        if C.get(th) and C.get(lay) is not None:
            need = math.ceil(round(C[th] / lh, 4))
            if need > C[lay]:
                rep.approx(f"{lay}: {C[lay]} layers raised to {need} to honour the {C[th]:g} mm minimum thickness")
                C[lay] = need

    # acceleration / jerk: 0 means "don't set" in Prusa/Orca
    da = C.get("accel_default") or 0
    C["accel_enabled"] = da > 0
    for k in [r[0] for r in ROWS if r[0].startswith("accel_") and r[0] != "accel_default"]:
        if C.get(k) is not None and C[k] == 0:
            C[k] = da
    if slicer == "orca":
        dj = C.get("jerk_default") or 0
        C["jerk_enabled"] = dj > 0
        for k in [r[0] for r in ROWS if r[0].startswith("jerk_") and r[0] != "jerk_default"]:
            if C.get(k) is not None and C[k] == 0:
                C[k] = dj
    # first layer speed 0 in Prusa = use normal speeds
    for k in ("speed_first_layer_infill",):
        if C.get(k) in (0, 0.0):
            C[k] = C.get("speed_first_layer")

    for k, v in cfg.items():
        if k in n.used or k.startswith(IGNORE_PREFIX) or k in _CONSUMED_EXTRA:
            continue
        rep.not_converted[k] = _first(v) if not isinstance(v, str) else v
    C["_src_values"] = dict(cfg)
    return {k: v for k, v in C.items() if v is not None}


FILAMENT_RETRACT = [
    ("retract_length", "filament_retract_length", "filament_retraction_length"),
    ("zhop", "filament_retract_lift", "filament_z_hop"),
    ("retract_speed", "filament_retract_speed", "filament_retraction_speed"),
    ("deretract_speed", "filament_deretract_speed", "filament_deretraction_speed"),
    ("retract_extra_prime", "filament_retract_restart_extra", "filament_retract_restart_extra"),
    ("retract_min_travel", "filament_retract_before_travel", "filament_retraction_minimum_travel"),
    ("retract_layer_change", "filament_retract_layer_change", "filament_retract_when_changing_layer"),
    ("zhop_above", "filament_retract_lift_above", "filament_retract_lift_above"),
    ("zhop_below", "filament_retract_lift_below", "filament_retract_lift_below"),
]

_CONSUMED_EXTRA = {"printer_technology", "support_material_auto", "wipe", "first_layer_speed_over_raft"}


def _bed_from_points(pts: List[str]) -> Tuple[float, float, bool]:
    xs, ys = [], []
    for p in pts:
        try:
            x, y = p.lower().split("x")
            xs.append(float(x))
            ys.append(float(y))
        except ValueError:
            pass
    if not xs:
        return 220.0, 220.0, False
    w, d = max(xs) - min(xs), max(ys) - min(ys)
    centre = min(xs) < -1 and min(ys) < -1
    return w, d, centre


def _common_specials(n: Native, C: Dict[str, Any], rep: Report, keys: Dict[str, str]):
    slicer = n.slicer
    C["first_layer_line_width"] = n.width(keys["first_layer_width"])
    pat = n.str(keys["infill_pattern"])
    C["infill_pattern"] = enum_to_canon(INFILL, pat, slicer, INFILL_ALIASES)
    if pat and C["infill_pattern"] is None:
        rep.approx(f"Infill pattern '{pat}' unknown; using grid")
        C["infill_pattern"] = "grid"
    for canon, k in (("top_pattern", keys["top_pattern"]), ("bottom_pattern", keys["bottom_pattern"])):
        p = n.str(k)
        c = enum_to_canon(SURFACE, p, slicer)
        C[canon] = c or ("lines" if p else None)
        if p and not c:
            rep.approx(f"{canon} '{p}' -> lines")
    seam = n.str("seam_position")
    C["seam"] = enum_to_canon(SEAM, seam, slicer, SEAM_ALIASES) or "aligned"
    sp = n.str(keys["support_pattern"])
    C["support_pattern"] = enum_to_canon(SUPPORT_PATTERN, sp, slicer) or "lines"
    if sp in ("default",):
        C["support_pattern"] = "lines" if slicer == "orca" else C["support_pattern"]
    C["bridge_flow"] = n.num(keys["bridge_flow"])
    C["elephant_foot"] = n.num("elefant_foot_compensation")
    C["avoid_crossing"] = n.bool(keys["avoid_crossing"])
    fz = n.str("fuzzy_skin", "none")
    C["fuzzy_skin"] = {"none": "none", "external": "external", "all": "all", "allwalls": "all",
                       "hole": "external", "disabled_fuzzy": "none"}.get(fz, "none")
    if fz in ("hole", "allwalls"):
        rep.approx(f"Fuzzy skin '{fz}' -> '{C['fuzzy_skin']}'")
    flav = n.str("gcode_flavor", "marlin2")
    C["gcode_flavor"] = flav if flav in FLAVOR else "marlin2"
    C["start_gcode"] = n.str(keys["start_gcode"], "") or ""
    C["end_gcode"] = n.str(keys["end_gcode"], "") or ""
    # raw gcode must keep newlines and semicolons: re-read untouched
    for canon, k in (("start_gcode", keys["start_gcode"]), ("end_gcode", keys["end_gcode"])):
        raw = n.cfg.get(k)
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        C[canon] = raw or ""
    C["zhop"] = n.num(keys["zhop"], 0.0)
    C["max_jerk_x"] = n.num("machine_max_jerk_x")
    C["max_jerk_y"] = n.num("machine_max_jerk_y")
    C["filament_type"] = n.str("filament_type", "PLA")
    C["fan_min"] = n.num(keys["fan_min"])
    C["fan_max"] = n.num(keys["fan_max"])
    C["fan_off_first_layers"] = int(n.num(keys["fan_off"], 0) or 0)


def _prusa_specials(n: Native, C: Dict[str, Any], rep: Report):
    _common_specials(n, C, rep, {
        "first_layer_width": "first_layer_extrusion_width", "infill_pattern": "fill_pattern",
        "top_pattern": "top_fill_pattern", "bottom_pattern": "bottom_fill_pattern",
        "support_pattern": "support_material_pattern", "bridge_flow": "bridge_flow_ratio",
        "avoid_crossing": "avoid_crossing_perimeters", "start_gcode": "start_gcode", "end_gcode": "end_gcode",
        "zhop": "retract_lift", "fan_min": "min_fan_speed", "fan_max": "max_fan_speed", "fan_off": "disable_fan_first_layers"})
    C["infill_every_layers"] = int(n.num("infill_every_layers", 1) or 1)
    C["wall_outer_first"] = n.bool("external_perimeters_first", False)
    C["wall_generator"] = n.str("perimeter_generator", "arachne")
    # support: 2.x = bool + auto flag; 3.0 = enum none/enforcers_only/everywhere
    sm = n.str("support_material", "0")
    auto = n.bool("support_material_auto", True)
    if sm in ("everywhere",):
        C["support_enabled"] = True
    elif sm in ("enforcers_only",):
        C["support_enabled"] = False
        rep.approx("Support 'enforcers only' -> support off (enforcer volumes don't transfer)")
    else:
        C["support_enabled"] = _bool(sm) and auto
        if _bool(sm) and not auto:
            rep.approx("Support 'enforcers only' -> support off (enforcer volumes don't transfer)")
    style = n.str("support_material_style", "grid")
    C["support_style"] = "tree" if style in ("tree", "organic") else "normal"
    if style == "snug":
        rep.approx("Support style 'snug' -> normal support")
    C["support_buildplate_only"] = n.bool("support_material_buildplate_only", False)
    th = n.num("support_material_threshold", 0) or 0
    if th > 0:
        C["support_overhang_angle"] = 90 - th
    else:
        C["support_overhang_angle"] = 45.0
        rep.approx("PrusaSlicer support threshold 0 = automatic; written as 45° overhang angle")
    C["support_gap"] = n.num("support_material_spacing")
    t = int(n.num("support_material_interface_layers", 0) or 0)
    b = n.num("support_material_bottom_interface_layers", -1)
    C["support_interface_top_layers"] = t
    C["support_interface_bottom_layers"] = t if (b is None or b < 0) else int(b)
    # adhesion
    skirts = int(n.num("skirts", 0) or 0)
    brim_type = n.str("brim_type", "outer_only")
    brim_w = n.num("brim_width", 0) or 0
    raft = int(n.num("raft_layers", 0) or 0)
    _adhesion(C, rep, skirts, brim_type, brim_w, raft)
    C["ironing_enabled"] = n.bool("ironing", False)
    C["ironing_topmost_only"] = n.str("ironing_type", "top") == "topmost"
    if n.str("ironing_type", "top") == "solid":
        rep.approx("Ironing 'all solid surfaces' -> top surfaces")
    C["one_at_a_time"] = n.bool("complete_objects", False)
    C["draft_shield"] = n.str("draft_shield", "disabled") in ("enabled", "limited")
    # filament
    C["bed_temp"] = n.num("bed_temperature")
    C["bed_temp_first_layer"] = n.num("first_layer_bed_temperature")
    C["flow_ratio"] = n.num("extrusion_multiplier")
    cooling = n.bool("cooling", True)
    always = n.bool("fan_always_on", False)
    C["fan_enabled"] = bool(cooling or always)
    if not always:
        C["fan_min"] = 0.0 if C.get("fan_min") is not None else None
        if cooling:
            rep.approx("PrusaSlicer 'keep fan always on' is off: fan only runs on short layers; regular fan speed = 0%")
    if not cooling and not always:
        C["fan_max"] = 0.0
    C["bridge_fan"] = n.num("bridge_fan_speed")
    # printer
    pts = n.raw("bed_shape")
    pts = pts.split(",") if isinstance(pts, str) else (pts or [])
    C["bed_x"], C["bed_y"], C["bed_origin_center"] = _bed_from_points(pts)
    usage = n.str("machine_limits_usage", "time_estimate_only")
    if usage == "emit_to_gcode":
        rep.note("PrusaSlicer writes machine limits (M201/M203/M204/M205) into G-code; Cura doesn't. Check firmware limits.")


def _orca_specials(n: Native, C: Dict[str, Any], rep: Report):
    _common_specials(n, C, rep, {
        "first_layer_width": "initial_layer_line_width", "infill_pattern": "sparse_infill_pattern",
        "top_pattern": "top_surface_pattern", "bottom_pattern": "bottom_surface_pattern",
        "support_pattern": "support_base_pattern", "bridge_flow": "bridge_flow",
        "avoid_crossing": "reduce_crossing_wall", "start_gcode": "machine_start_gcode", "end_gcode": "machine_end_gcode",
        "zhop": "z_hop", "fan_min": "fan_min_speed", "fan_max": "fan_max_speed", "fan_off": "close_fan_the_first_x_layers"})
    if n.bool("infill_combination", False):
        noz = n.num("nozzle_diameter", 0.4) or 0.4
        lh = C.get("layer_height") or 0.2
        C["infill_every_layers"] = max(1, int(noz // lh))
        rep.approx(f"Orca 'combine infill' -> infill every {C['infill_every_layers']} layers")
    else:
        C["infill_every_layers"] = 1
    seq = n.str("wall_sequence", "inner wall/outer wall")
    C["wall_outer_first"] = seq != "inner wall/outer wall"
    if seq == "inner-outer-inner wall":
        rep.approx("Wall order inner-outer-inner -> outer first")
    C["wall_generator"] = n.str("wall_generator", "arachne")
    st = n.str("support_type", "normal(auto)")
    C["support_enabled"] = bool(n.bool("enable_support", False)) and "auto" in st
    if n.bool("enable_support", False) and "manual" in st:
        rep.approx("Orca manual (painted) supports -> support off; painted areas don't transfer")
    C["support_style"] = "tree" if st.startswith("tree") else "normal"
    C["support_buildplate_only"] = n.bool("support_on_build_plate_only", False)
    th = n.num("support_threshold_angle", 30) or 0
    C["support_overhang_angle"] = 90 - th if th > 0 else 45.0
    if th <= 0:
        rep.approx("Orca support threshold 0 = automatic; written as 45° overhang angle")
    C["support_gap"] = n.num("support_base_pattern_spacing")
    C["support_interface_top_layers"] = int(n.num("support_interface_top_layers", 0) or 0)
    b = n.num("support_interface_bottom_layers", -1)
    C["support_interface_bottom_layers"] = C["support_interface_top_layers"] if (b is None or b < 0) else int(b)
    brim_type = n.str("brim_type", "auto_brim")
    brim_w = n.num("brim_width", 0) or 0
    if brim_type in ("auto_brim", "brim_ears", "painted"):
        rep.approx(f"Orca brim type '{brim_type}' -> plain outer brim of {brim_w:g} mm")
        brim_type = "outer_only" if brim_w > 0 else "no_brim"
    _adhesion(C, rep, int(n.num("skirt_loops", 0) or 0), brim_type, brim_w, int(n.num("raft_layers", 0) or 0))
    it = n.str("ironing_type", "no ironing")
    C["ironing_enabled"] = it != "no ironing"
    C["ironing_topmost_only"] = it == "topmost"
    C["one_at_a_time"] = n.str("print_sequence", "by layer") == "by object"
    C["draft_shield"] = n.str("draft_shield", "disabled") == "enabled"
    # bed temperature depends on the selected plate type
    plate = n.str("curr_bed_type") or n.str("bed_type") or n.str("default_bed_type") or ""
    plate_keys = {"Cool Plate": "cool_plate_temp", "Engineering Plate": "eng_plate_temp",
                  "High Temp Plate": "hot_plate_temp", "Textured PEI Plate": "textured_plate_temp",
                  "Textured Cool Plate": "textured_cool_plate_temp", "Supertack Plate": "supertack_plate_temp"}
    pk = plate_keys.get(plate)
    if not pk:
        pk = next((k for k in ("textured_plate_temp", "hot_plate_temp", "cool_plate_temp", "eng_plate_temp")
                   if (n.num(k) or 0) > 0), "hot_plate_temp")
        rep.note(f"Orca bed temperature is per plate type; using '{pk}' values.")
    C["bed_temp"] = n.num(pk)
    C["bed_temp_first_layer"] = n.num(pk + "_initial_layer", C["bed_temp"])
    for k in plate_keys.values():
        for suffix in ("", "_initial_layer"):
            n.used.add(k + suffix)
    n.used.update({"curr_bed_type", "default_bed_type", "bed_type"})
    C["flow_ratio"] = n.num("filament_flow_ratio")
    C["fan_enabled"] = (C.get("fan_max") or 0) > 0
    if not n.bool("reduce_fan_stop_start_freq", False):
        rep.approx("Orca 'keep fan always on' is off; fan min speed used as the regular speed")
    if n.bool("enable_overhang_bridge_fan", True):
        C["bridge_fan"] = n.num("overhang_fan_speed")
    pts = n.raw("printable_area") or []
    if isinstance(pts, str):
        pts = pts.split(",")
    C["bed_x"], C["bed_y"], C["bed_origin_center"] = _bed_from_points(pts)
    if n.bool("emit_machine_limits_to_gcode", False):
        rep.note("Orca writes machine limits into the G-code; check firmware limits on the target.")
    if not n.bool("slow_down_for_layer_cooling", True):
        C["slowdown_layer_time"] = 0.0
    if (n.num("pressure_advance") or 0) > 0 and n.bool("enable_pressure_advance", False):
        rep.note(f"Pressure advance {n.num('pressure_advance'):g} is set in Orca's filament; Cura/Prusa need it in firmware or start G-code.")


def _adhesion(C, rep, skirts, brim_type, brim_w, raft):
    has_brim = brim_type not in ("no_brim", None) and brim_w > 0
    if raft > 0:
        C["adhesion_type"] = "raft"
    elif has_brim:
        C["adhesion_type"] = "brim"
    elif skirts > 0:
        C["adhesion_type"] = "skirt"
    else:
        C["adhesion_type"] = "none"
    if sum(bool(x) for x in (raft > 0, has_brim, skirts > 0)) > 1:
        rep.approx(f"Source uses more than one of skirt/brim/raft; Cura allows one, chose '{C['adhesion_type']}'")
    C["skirt_loops"] = skirts
    C["brim_width"] = brim_w if has_brim else 0.0
    C["brim_outer_only"] = brim_type in ("outer_only", None) or not has_brim
    C["raft_layers"] = raft


# ---------------------------------------------------------------------------
# canonical -> native
# ---------------------------------------------------------------------------

def _fmt_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        s = f"{v:.4f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    return str(v)


def _native_value(slicer: str, key: str, v: Any, pct: bool = False) -> Any:
    """Format a value as the slicer's file format wants it for this option type."""
    t = _types(slicer).get(key, {}).get("type", "coString")
    if t in ("coPercent", "coPercents") or (pct and t in ("coFloatOrPercent", "coFloatsOrPercents")):
        s = _fmt_scalar(float(v)) + "%"
    elif t in ("coInt", "coInts"):
        s = str(int(round(float(v))))
    elif t in ("coBool", "coBools"):
        s = "1" if v else "0"
    else:
        s = _fmt_scalar(v)
    vector = t.endswith("s") and t not in ("coString",)
    if slicer == "orca":
        return [s] if vector else s
    return s


def from_canon(slicer: str, C: Dict[str, Any], rep: Report, src: str,
               target_version: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Return {"print": {...}, "filament": {...}, "printer": {...}} native key/values.
    target_version: version of the slicer the presets are going into, when known."""
    out: Dict[str, Dict[str, Any]] = {"print": {}, "filament": {}, "printer": {}}
    col = IDX[slicer]
    types = _types(slicer)
    present = lambda k: C.get(k) is not None

    def put(sec: str, key: str, value: Any, canon: Optional[str] = None, pct: bool = False):
        if key not in types:
            rep.note(f"Internal: {NAME[slicer]} has no option '{key}' (skipped)")
            return
        out[sec][key] = _native_value(slicer, key, value, pct)
        if canon:
            rep.converted[canon] = C.get(canon, value)

    for canon, sec, kind, *keys in ROWS:
        key = keys[col - 3]
        if not present(canon):
            continue
        if key is None:
            if C[canon] not in (0, 0.0, False, ""):
                rep.target_missing.append(f"{canon} = {C[canon]}")
            continue
        val = C[canon]
        if kind == "gcode":
            txt, notes = gcode.translate(val, src, slicer, C.get("_src_values"))
            out[sec][key] = txt
            rep.converted[canon] = txt
            rep.gcode_notes.extend(notes)
            continue
        if canon.startswith("accel_") and C.get("accel_enabled") is False:
            val = 0
        if canon.startswith("jerk_") and C.get("jerk_enabled") is False:
            val = 0
        put(sec, key, val, canon, pct=(kind == "pct"))

    def en(table, canon_key, label):
        nat, ap = enum_to_native(table, C.get(canon_key), slicer)
        if nat and ap:
            rep.approx(f"{label} '{C.get(canon_key)}' -> {NAME[slicer]} '{nat}'")
        return nat

    p, f, m = "print", "filament", "printer"
    if slicer == "prusa":
        if present("first_layer_line_width"):
            put(p, "first_layer_extrusion_width", C["first_layer_line_width"], "first_layer_line_width")
        v = en(INFILL, "infill_pattern", "Infill pattern")
        if v:
            put(p, "fill_pattern", v, "infill_pattern")
        if present("infill_every_layers"):
            put(p, "infill_every_layers", C["infill_every_layers"], "infill_every_layers")
        for canon, key in (("top_pattern", "top_fill_pattern"), ("bottom_pattern", "bottom_fill_pattern")):
            v = en(SURFACE, canon, canon)
            if v:
                put(p, key, v, canon)
        if present("wall_outer_first"):
            put(p, "external_perimeters_first", C["wall_outer_first"], "wall_outer_first")
        if present("wall_generator"):
            put(p, "perimeter_generator", C["wall_generator"], "wall_generator")
        v = en(SEAM, "seam", "Seam")
        if v:
            put(p, "seam_position", v, "seam")
        if present("support_enabled"):
            put(p, "support_material", C["support_enabled"], "support_enabled")
            put(p, "support_material_auto", True)
            put(p, "support_material_style", "organic" if C.get("support_style") == "tree" else "grid", "support_style")
            put(p, "support_material_buildplate_only", bool(C.get("support_buildplate_only")), "support_buildplate_only")
        if present("support_overhang_angle"):
            put(p, "support_material_threshold", max(1, int(round(90 - C["support_overhang_angle"]))), "support_overhang_angle")
        v = en(SUPPORT_PATTERN, "support_pattern", "Support pattern")
        if v:
            put(p, "support_material_pattern", v, "support_pattern")
        if present("support_gap"):
            put(p, "support_material_spacing", C["support_gap"], "support_gap")
        if present("support_interface_top_layers"):
            put(p, "support_material_interface_layers", C["support_interface_top_layers"], "support_interface_top_layers")
        if present("support_interface_bottom_layers"):
            put(p, "support_material_bottom_interface_layers", C["support_interface_bottom_layers"], "support_interface_bottom_layers")
        at = C.get("adhesion_type")
        if at:
            rep.converted["adhesion_type"] = at
            put(p, "skirts", int(C.get("skirt_loops") or 1) if at == "skirt" else 0, "skirt_loops")
            put(p, "brim_width", C.get("brim_width") or 0 if at == "brim" else 0, "brim_width")
            put(p, "brim_type", ("outer_only" if C.get("brim_outer_only", True) else "outer_and_inner") if at == "brim" else "no_brim")
            put(p, "raft_layers", int(C.get("raft_layers") or 0) if at == "raft" else 0, "raft_layers")
        if present("bridge_flow"):
            put(p, "bridge_flow_ratio", C["bridge_flow"], "bridge_flow")
        if present("ironing_enabled"):
            put(p, "ironing", C["ironing_enabled"], "ironing_enabled")
            put(p, "ironing_type", "topmost" if C.get("ironing_topmost_only") else "top", "ironing_topmost_only")
        if present("elephant_foot"):
            put(p, "elefant_foot_compensation", C["elephant_foot"], "elephant_foot")
        if present("one_at_a_time"):
            put(p, "complete_objects", C["one_at_a_time"], "one_at_a_time")
        if present("draft_shield"):
            put(p, "draft_shield", "enabled" if C["draft_shield"] else "disabled", "draft_shield")
        if present("avoid_crossing"):
            put(p, "avoid_crossing_perimeters", C["avoid_crossing"], "avoid_crossing")
        if present("fuzzy_skin"):
            put(p, "fuzzy_skin", C["fuzzy_skin"], "fuzzy_skin")
        # filament
        if present("bed_temp"):
            put(f, "bed_temperature", C["bed_temp"], "bed_temp")
        if present("bed_temp_first_layer"):
            put(f, "first_layer_bed_temperature", C["bed_temp_first_layer"], "bed_temp_first_layer")
        if present("flow_ratio"):
            put(f, "extrusion_multiplier", C["flow_ratio"], "flow_ratio")
        if present("fan_max"):
            fmin = float(C.get("fan_min") or 0)
            on = C.get("fan_enabled", True)
            put(f, "cooling", bool(on), "fan_enabled")
            put(f, "fan_always_on", bool(on and fmin > 0))
            put(f, "min_fan_speed", fmin if on else 0, "fan_min")
            put(f, "max_fan_speed", float(C["fan_max"]) if on else 0, "fan_max")
        if present("fan_off_first_layers"):
            put(f, "disable_fan_first_layers", C["fan_off_first_layers"], "fan_off_first_layers")
        if present("bridge_fan"):
            put(f, "bridge_fan_speed", C["bridge_fan"], "bridge_fan")
        if present("filament_type"):
            put(f, "filament_type", C["filament_type"], "filament_type")
        # printer
        if present("bed_x") and present("bed_y"):
            put(m, "bed_shape", _bed_points(C), "bed_x")
            rep.converted["bed_y"] = C["bed_y"]
        if present("zhop"):
            put(m, "retract_lift", C["zhop"], "zhop")
        for ax in ("x", "y"):
            if present(f"max_jerk_{ax}"):
                put(m, f"machine_max_jerk_{ax}", C[f"max_jerk_{ax}"], f"max_jerk_{ax}")
        put(m, "machine_limits_usage", "time_estimate_only")
        put(m, "printer_technology", "FFF")
    else:  # orca
        if present("first_layer_line_width"):
            put(p, "initial_layer_line_width", C["first_layer_line_width"], "first_layer_line_width")
        v = en(INFILL, "infill_pattern", "Infill pattern")
        if v:
            put(p, "sparse_infill_pattern", v, "infill_pattern")
        if present("infill_every_layers"):
            put(p, "infill_combination", int(C["infill_every_layers"]) > 1, "infill_every_layers")
            if int(C["infill_every_layers"]) > 1:
                rep.approx(f"Infill every {C['infill_every_layers']} layers -> Orca 'combine infill' (uses its own max height)")
        for canon, key in (("top_pattern", "top_surface_pattern"), ("bottom_pattern", "bottom_surface_pattern")):
            v = en(SURFACE, canon, canon)
            if v:
                put(p, key, v, canon)
        if present("wall_outer_first"):
            put(p, "wall_sequence", "outer wall/inner wall" if C["wall_outer_first"] else "inner wall/outer wall", "wall_outer_first")
        if present("wall_generator"):
            put(p, "wall_generator", C["wall_generator"], "wall_generator")
        v = en(SEAM, "seam", "Seam")
        if v:
            put(p, "seam_position", v, "seam")
        if present("support_enabled"):
            put(p, "enable_support", C["support_enabled"], "support_enabled")
            put(p, "support_type", "tree(auto)" if C.get("support_style") == "tree" else "normal(auto)", "support_style")
            put(p, "support_on_build_plate_only", bool(C.get("support_buildplate_only")), "support_buildplate_only")
        if present("support_overhang_angle"):
            put(p, "support_threshold_angle", max(1, int(round(90 - C["support_overhang_angle"]))), "support_overhang_angle")
        v = en(SUPPORT_PATTERN, "support_pattern", "Support pattern")
        if v:
            put(p, "support_base_pattern", v, "support_pattern")
        if present("support_gap"):
            put(p, "support_base_pattern_spacing", C["support_gap"], "support_gap")
        if present("support_interface_top_layers"):
            put(p, "support_interface_top_layers", C["support_interface_top_layers"], "support_interface_top_layers")
        if present("support_interface_bottom_layers"):
            put(p, "support_interface_bottom_layers", C["support_interface_bottom_layers"], "support_interface_bottom_layers")
        at = C.get("adhesion_type")
        if at:
            rep.converted["adhesion_type"] = at
            put(p, "skirt_loops", int(C.get("skirt_loops") or 1) if at == "skirt" else 0, "skirt_loops")
            put(p, "brim_width", C.get("brim_width") or 0 if at == "brim" else 0, "brim_width")
            put(p, "brim_type", ("outer_only" if C.get("brim_outer_only", True) else "outer_and_inner") if at == "brim" else "no_brim")
            put(p, "raft_layers", int(C.get("raft_layers") or 0) if at == "raft" else 0, "raft_layers")
        if present("bridge_flow"):
            put(p, "bridge_flow", C["bridge_flow"], "bridge_flow")
        if present("ironing_enabled"):
            it = "no ironing"
            if C["ironing_enabled"]:
                it = "topmost" if C.get("ironing_topmost_only") else "top"
            put(p, "ironing_type", it, "ironing_enabled")
        if present("elephant_foot"):
            put(p, "elefant_foot_compensation", C["elephant_foot"], "elephant_foot")
        if present("one_at_a_time"):
            put(p, "print_sequence", "by object" if C["one_at_a_time"] else "by layer", "one_at_a_time")
        if present("draft_shield"):
            put(p, "draft_shield", "enabled" if C["draft_shield"] else "disabled", "draft_shield")
        if present("avoid_crossing"):
            put(p, "reduce_crossing_wall", C["avoid_crossing"], "avoid_crossing")
        if present("fuzzy_skin"):
            put(p, "fuzzy_skin", C["fuzzy_skin"], "fuzzy_skin")
        # filament: write every plate type so the selected plate doesn't matter
        if present("bed_temp"):
            for k in ("hot_plate_temp", "cool_plate_temp", "textured_plate_temp", "eng_plate_temp",
                      "textured_cool_plate_temp", "supertack_plate_temp"):
                put(f, k, C["bed_temp"])
                fl = C.get("bed_temp_first_layer", C["bed_temp"])
                put(f, k + "_initial_layer", fl)
            rep.converted["bed_temp"] = C["bed_temp"]
            rep.converted["bed_temp_first_layer"] = C.get("bed_temp_first_layer", C["bed_temp"])
        if present("flow_ratio"):
            put(f, "filament_flow_ratio", C["flow_ratio"], "flow_ratio")
        if present("fan_max"):
            on = C.get("fan_enabled", True)
            fmin = float(C.get("fan_min") or 0) if on else 0
            put(f, "fan_min_speed", fmin, "fan_min")
            put(f, "fan_max_speed", max(fmin, float(C["fan_max"])) if on else 0, "fan_max")
            put(f, "reduce_fan_stop_start_freq", bool(on and fmin > 0), "fan_enabled")
        if present("fan_off_first_layers"):
            put(f, "close_fan_the_first_x_layers", C["fan_off_first_layers"], "fan_off_first_layers")
        if present("bridge_fan"):
            put(f, "enable_overhang_bridge_fan", True)
            put(f, "overhang_fan_speed", C["bridge_fan"], "bridge_fan")
        if present("slowdown_layer_time"):
            put(f, "slow_down_for_layer_cooling", float(C["slowdown_layer_time"]) > 0)
        if present("filament_type"):
            put(f, "filament_type", C["filament_type"], "filament_type")
        if present("bed_x") and present("bed_y"):
            out[m]["printable_area"] = _bed_points(C).split(",")
            rep.converted["bed_x"], rep.converted["bed_y"] = C["bed_x"], C["bed_y"]
        if present("zhop"):
            put(m, "z_hop", C["zhop"], "zhop")
        for ax in ("x", "y"):
            if present(f"max_jerk_{ax}"):
                put(m, f"machine_max_jerk_{ax}", C[f"max_jerk_{ax}"], f"max_jerk_{ax}")
        put(m, "emit_machine_limits_to_gcode", False)

    # shared printer bits
    if present("gcode_flavor"):
        v = en(FLAVOR, "gcode_flavor", "G-code flavour")
        if v:
            put(m, "gcode_flavor", v, "gcode_flavor")
    sk, ek = ("start_gcode", "end_gcode") if slicer == "prusa" else ("machine_start_gcode", "machine_end_gcode")
    for canon, key in (("start_gcode", sk), ("end_gcode", ek)):
        if C.get(canon):
            txt, notes = gcode.translate(C[canon], src, slicer, C.get("_src_values"))
            out[m][key] = txt
            rep.converted[canon] = txt
            rep.gcode_notes.extend(notes)
    newer = too_new_for(slicer, out, target_version)
    if newer:
        listed = ", ".join(f"{k} (PrusaSlicer {v}+)" for k, v in newer)
        if target_version:
            rep.note(f"Your PrusaSlicer {target_version} is older than these settings and ignores them: {listed}.")
        else:
            rep.note(f"Only newer PrusaSlicer versions have these settings; older ones ignore them: {listed}.")
    return out


def _bed_points(C: Dict[str, Any]) -> str:
    w, d = float(C["bed_x"]), float(C["bed_y"])
    x0, y0 = (-w / 2, -d / 2) if C.get("bed_origin_center") else (0.0, 0.0)
    pts = [(x0, y0), (x0 + w, y0), (x0 + w, y0 + d), (x0, y0 + d)]
    return ",".join(f"{_fmt_scalar(a)}x{_fmt_scalar(b)}" for a, b in pts)


# ---------------------------------------------------------------------------
# file writers
# ---------------------------------------------------------------------------

def _prusa_escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n")


def write_prusa(native: Dict[str, Dict[str, Any]], name: str, outdir: str,
                inherits: Optional[Dict[str, str]] = None) -> List[str]:
    from . import __version__
    os.makedirs(outdir, exist_ok=True)
    safe = _safe(name)
    header = f"# generated by SlicerSwap {__version__}\n"
    # 1) config bundle: shows up as three named presets (File > Import > Import Config Bundle)
    b = io.StringIO()
    b.write(header + "\n")
    for kind in ("print", "filament", "printer"):
        b.write(f"[{kind}:{name}]\n")
        if inherits and inherits.get(kind):
            b.write(f"inherits = {inherits[kind]}\n")
        for k in sorted(native[kind]):
            b.write(f"{k} = {_prusa_escape(str(native[kind][k]))}\n")
        b.write("\n")
    b.write("[presets]\n")
    for kind in ("print", "filament", "printer"):
        b.write(f"{kind} = {name}\n")
    p1 = os.path.join(outdir, safe + ".prusa_bundle.ini")
    with open(p1, "w", encoding="utf-8") as fh:
        fh.write(b.getvalue())
    # 2) flat config (File > Import > Import Config)
    flat = {}
    for kind in ("printer", "filament", "print"):
        flat.update(native[kind])
    p2 = os.path.join(outdir, safe + ".prusa_config.ini")
    with open(p2, "w", encoding="utf-8") as fh:
        fh.write(header)
        for k in sorted(flat):
            fh.write(f"{k} = {_prusa_escape(str(flat[k]))}\n")
    return [p1, p2]


def write_orca(native: Dict[str, Dict[str, Any]], name: str, outdir: str,
               inherits: Optional[Dict[str, str]] = None) -> List[str]:
    from . import __version__
    os.makedirs(outdir, exist_ok=True)
    safe = _safe(name)
    files = []
    spec = (("print", "process", "print_settings_id", f"{name}"),
            ("filament", "filament", "filament_settings_id", f"{name}"),
            ("printer", "machine", "printer_settings_id", f"{name}"))
    for kind, otype, idkey, pname in spec:
        doc: Dict[str, Any] = {
            "type": otype, "name": pname, "from": "User", "instantiation": "true",
            "inherits": (inherits or {}).get(kind, ""),
            idkey: [pname] if otype == "filament" else pname,
        }
        if otype in ("process", "filament"):
            doc["compatible_printers"] = []
            doc["compatible_printers_condition"] = ""
        doc.update(dict(sorted(native[kind].items())))
        path = os.path.join(outdir, f"{safe}.orca_{otype}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=4, ensure_ascii=False)
        files.append(path)
    return files


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._ ()+-]+", "_", name).strip() or "profile"
