# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""List what a slicer install holds: profiles, materials, printers, plug-ins, scripts, app settings.

An Item names the files that belong together (a Cura printer is a machine stack, its
extruder stacks and the containers they point at; an Orca preset is a .json plus a .info).
Nothing here changes any file.
"""
from __future__ import annotations

import configparser
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote_plus, unquote_plus

from .slicers import Install

KIND_LABEL = {
    "profile": "Print profiles",
    "material": "Filaments / materials",
    "printer": "Printers",
    "plugin": "Plug-ins",
    "script": "Post-processing scripts",
    "settings": "App settings",
    "other": "Other user files",
}
KIND_ORDER = list(KIND_LABEL)

# never backed up: logs, caches, downloaded system data, the slicers' own backups
IGNORE_DIRS = {"__pycache__", "cache", "log", "logs", "ota", "snapshots", ".thumbnails"}
IGNORE_FILE_RE = re.compile(r"(\.pyc|\.qmlc|\.log|\.log\.\d+|\.lock|\.tmp|\.bak|~)$|^cura\.log|^stdout\.log$|^stderr\.log$|^cookies\.db")
ORCA_SKIP_TOP = {"system", "printers", "ota", "log", "cache"}      # re-created/downloaded by Orca
PRUSA_SKIP_TOP = {"cache", "snapshots"}
CURA_SKIP_TOP = {"cache", "plugins-removed-by-slicerswap"}      # the second: plug-ins SlicerSwap moved aside


@dataclass
class Item:
    kind: str
    name: str
    files: List[Tuple[str, str]]              # (root, path relative to that root, '/' separated)
    detail: str = ""
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.name}"


def _rel(path: str, root: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def _walk(root_dir: str, sub: str = "") -> List[str]:
    """Relative paths of all backup-worthy files under root_dir/sub."""
    out = []
    start = os.path.join(root_dir, sub) if sub else root_dir
    if os.path.isfile(start):
        return [sub]
    for dp, dns, fns in os.walk(start):
        dns[:] = sorted(d for d in dns if d not in IGNORE_DIRS)
        for fn in sorted(fns):
            if IGNORE_FILE_RE.search(fn) or fn.startswith("."):
                continue
            out.append(_rel(os.path.join(dp, fn), root_dir))
    return out


def _read_cfg(path: str) -> Dict[str, Dict[str, str]]:
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            cp.read_string(fh.read())
    except (OSError, configparser.Error):
        return {}
    return {s: dict(cp.items(s)) for s in cp.sections()}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# ---------------------------------------------------------------------------
# Cura
# ---------------------------------------------------------------------------

CURA_CONTAINER_DIRS = ("user", "quality_changes", "definition_changes", "variants", "materials", "quality", "intent")


def _cura_find_container(data: str, cid: str) -> List[str]:
    """Files in the user data folder that hold container <cid> (ids are URL-quoted in file names)."""
    if not cid or cid.startswith("empty"):
        return []
    q = quote_plus(cid)
    hits = []
    for sub in CURA_CONTAINER_DIRS:
        for ext in (".inst.cfg", ".xml.fdm_material"):
            p = os.path.join(data, sub, q + ext)
            if os.path.isfile(p):
                hits.append(f"{sub}/{q}{ext}")
    for sub in ("definitions", "extruders"):
        p = os.path.join(data, sub, q + ".def.json")
        if os.path.isfile(p):
            hits.append(f"{sub}/{q}.def.json")
    return hits


def cura_machines(inst: Install) -> List[Dict[str, Any]]:
    """Printers set up in this Cura: name, id, definition, extruder definition(s), file lists."""
    data = inst.roots["data"]
    mdir = os.path.join(data, "machine_instances")
    out = []
    if not os.path.isdir(mdir):
        return out
    extruders = []
    edir = os.path.join(data, "extruders")
    if os.path.isdir(edir):
        for fn in sorted(os.listdir(edir)):
            if fn.endswith(".extruder.cfg"):
                cfg = _read_cfg(os.path.join(edir, fn))
                extruders.append((fn, cfg))
    for fn in sorted(os.listdir(mdir)):
        if not fn.endswith(".global.cfg"):
            continue
        cfg = _read_cfg(os.path.join(mdir, fn))
        gen, cont = cfg.get("general", {}), cfg.get("containers", {})
        mid = gen.get("id") or unquote_plus(fn[:-11])
        ordered = [cont[k] for k in sorted(cont, key=lambda x: int(x) if x.isdigit() else 99)]
        files = [("data", f"machine_instances/{fn}")]
        for cid in ordered:
            files += [("data", f) for f in _cura_find_container(data, cid)]
        ex_defs, ex_ids, material, variant = [], [], None, None
        for efn, ecfg in extruders:
            if ecfg.get("metadata", {}).get("machine") != mid:
                continue
            files.append(("data", f"extruders/{efn}"))
            econt = ecfg.get("containers", {})
            eordered = [econt[k] for k in sorted(econt, key=lambda x: int(x) if x.isdigit() else 99)]
            for cid in eordered:
                files += [("data", f) for f in _cura_find_container(data, cid)]
            if eordered:
                ex_defs.append(eordered[-1])
                ex_ids.append(ecfg.get("general", {}).get("id", ""))
                if ecfg.get("metadata", {}).get("position", "0") == "0" and len(eordered) >= 8:
                    material, variant = eordered[4], eordered[5]
        seen: Set[Tuple[str, str]] = set()
        files = [f for f in files if not (f in seen or seen.add(f))]
        out.append({"name": gen.get("name", mid), "id": mid, "definition": ordered[-1] if ordered else "",
                    "extruder_definitions": ex_defs, "extruder_ids": ex_ids, "files": files, "containers": ordered,
                    "material": material, "variant": variant, "metadata": cfg.get("metadata", {})})
    return out


def cura_log_path(inst: Install) -> str:
    return os.path.join(inst.roots["data"], "cura.log")


# Cura's package list. Its own writer keeps these four keys; anything else is left untouched.
PACKAGE_KEYS = {"installed": dict, "to_install": dict, "to_remove": list, "dismissed": list}
MAX_PACKAGES = 50_000_000


class PackagesDamaged(Exception):
    """Cura's package list exists but cannot be read safely: writing it would wipe Cura's record of other plug-ins."""

    def __init__(self, path: str, problem: str):
        super().__init__(f"{path} {problem}")
        self.path, self.problem = path, problem


def read_packages_file(p: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """(content, problem). problem is None when the file is fine; an empty file is fine (nothing to lose)."""
    try:
        with open(p, "rb") as fh:
            raw = fh.read(MAX_PACKAGES + 1)
    except OSError as e:
        return {}, f"could not be opened ({e.strerror or e})"
    if len(raw) > MAX_PACKAGES:
        return {}, "is far larger than Cura ever makes it"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return {}, "is not readable text (it may be damaged)"
    if not text.strip():
        return {}, None
    try:
        pk = json.loads(text)
    except (ValueError, RecursionError) as e:
        return {}, f"is damaged ({str(e)[:120]})"
    if not isinstance(pk, dict):
        return {}, "does not hold a package list Cura would recognise"
    for key, typ in PACKAGE_KEYS.items():
        if key in pk and not isinstance(pk[key], typ):
            return {}, f"has an unexpected '{key}' entry"
    return pk, None


def cura_packages(inst: Install, strict: bool = False) -> Tuple[str, Dict[str, Any]]:
    """(path, content) of Cura's package bookkeeping file; content is {} when Cura has not made one yet.
    A file that exists but cannot be read gives {} for display; with strict=True it raises PackagesDamaged,
    which every caller that WRITES the file uses, so a damaged list is never replaced by a near-empty one."""
    for root in ("data", "config"):
        p = os.path.join(inst.roots[root], "packages.json")
        if os.path.isfile(p):
            pk, problem = read_packages_file(p)
            if problem and strict:
                raise PackagesDamaged(p, problem)
            return p, pk
    return os.path.join(inst.roots["data"], "packages.json"), {}


def packages_problem(inst: Install) -> Optional[str]:
    """A one-line warning when Cura's package list cannot be read, else None."""
    try:
        cura_packages(inst, strict=True)
    except PackagesDamaged as e:
        return damaged_text(e)
    return None


def damaged_text(e: "PackagesDamaged") -> str:
    bak = e.path + ".bak"
    hint = ""
    if os.path.isfile(bak) and read_packages_file(bak)[1] is None:
        hint = (f" A good copy from SlicerSwap's last change is next to it: close Cura, rename "
                f"{os.path.basename(bak)} to packages.json, then try again.")
    else:
        hint = (" Cura still loads your plug-ins from their folders. For a fresh list: close Cura and rename "
                "packages.json; plug-ins from the Marketplace may then need reinstalling to show under Manage packages.")
    return (f"Cura's list of installed plug-ins ({e.path}) {e.problem}. SlicerSwap will not change it, "
            f"because rewriting it would wipe Cura's record of your other plug-ins." + hint)


def cura_plugins(inst: Install) -> List[Dict[str, Any]]:
    """User-installed Cura plug-ins: one entry per plug-in folder (Marketplace packages nest one level deeper)."""
    pdir = os.path.join(inst.roots["data"], "plugins")
    _path, pk = cura_packages(inst)
    installed = pk.get("installed", {}) if isinstance(pk, dict) else {}
    pending = pk.get("to_install", {}) if isinstance(pk, dict) else {}
    removing = set(pk.get("to_remove", [])) if isinstance(pk, dict) else set()
    out = []
    if os.path.isdir(pdir):
        for top in sorted(os.listdir(pdir)):
            tdir = os.path.join(pdir, top)
            if not os.path.isdir(tdir) or top in IGNORE_DIRS:
                continue
            pj = None
            for cand in [os.path.join(tdir, "plugin.json")] + \
                        [os.path.join(tdir, d, "plugin.json") for d in sorted(os.listdir(tdir))]:
                if os.path.isfile(cand):
                    pj = cand
                    break
            if not pj:
                continue
            try:
                with open(pj, encoding="utf-8") as fh:
                    meta = json.load(fh)
            except (OSError, ValueError):
                meta = {}
            plugin_id = os.path.basename(os.path.dirname(pj))
            out.append({"folder": top, "plugin_id": plugin_id, "path": os.path.dirname(pj), "name": meta.get("name", plugin_id),
                        "version": str(meta.get("version", "")), "author": meta.get("author", ""),
                        "packaged": os.path.dirname(pj) != tdir, "package": installed.get(top),
                        "state": "will be removed when Cura starts" if top in removing else "installed"})
    for pid, entry in pending.items():
        info = entry.get("package_info", {}) if isinstance(entry, dict) else {}
        out.append({"folder": None, "plugin_id": pid, "path": None, "name": info.get("display_name", pid),
                    "version": str(info.get("package_version", "")), "author": (info.get("author") or {}).get("display_name", ""),
                    "packaged": True, "package": entry, "state": "waiting: installs when Cura starts"})
    return out


def _inventory_cura(inst: Install) -> List[Item]:
    data, cfg = inst.roots["data"], inst.roots["config"]
    items: List[Item] = []
    claimed: Set[Tuple[str, str]] = set()

    # printers
    for m in cura_machines(inst):
        n_ex = len(m["extruder_definitions"])
        items.append(Item("printer", m["name"], m["files"],
                          f"{m['definition']} · {_plural(n_ex, 'extruder')}",
                          {"definition": m["definition"], "id": m["id"]}))
        claimed.update(m["files"])

    # custom profiles (a global container plus one per extruder share a name)
    qdir = os.path.join(data, "quality_changes")
    groups: Dict[str, Dict[str, Any]] = {}
    if os.path.isdir(qdir):
        for fn in sorted(os.listdir(qdir)):
            if not fn.endswith(".inst.cfg"):
                continue
            c = _read_cfg(os.path.join(qdir, fn))
            name = c.get("general", {}).get("name", unquote_plus(fn[:-9]))
            g = groups.setdefault(name, {"files": [], "n": 0, "definition": "", "quality_type": ""})
            g["files"].append(("data", f"quality_changes/{fn}"))
            g["n"] += len(c.get("values", {}))
            g["definition"] = c.get("general", {}).get("definition", g["definition"])
            g["quality_type"] = c.get("metadata", {}).get("quality_type", g["quality_type"])
    for name, g in groups.items():
        items.append(Item("profile", name, g["files"],
                          f"for {g['definition']} · based on '{g['quality_type']}' · {_plural(g['n'], 'setting')}",
                          {"definition": g["definition"], "quality_type": g["quality_type"]}))
        claimed.update(g["files"])

    # custom materials
    mdir = os.path.join(data, "materials")
    if os.path.isdir(mdir):
        for fn in sorted(os.listdir(mdir)):
            if not fn.endswith(".xml.fdm_material"):
                continue
            try:
                with open(os.path.join(mdir, fn), encoding="utf-8", errors="replace") as fh:
                    head = fh.read(4000)
            except OSError:
                head = ""
            tag = lambda t: (re.search(rf"<{t}>([^<]*)</{t}>", head) or [None, ""])[1].strip()
            label = " ".join(x for x in (tag("brand"), tag("material"), tag("color")) if x) or unquote_plus(fn[:-17])
            f = ("data", f"materials/{fn}")
            items.append(Item("material", label, [f], unquote_plus(fn[:-17])))
            claimed.add(f)

    # plug-ins
    for p in cura_plugins(inst):
        if not p["folder"]:
            continue
        files = [("data", r) for r in _walk(data, f"plugins/{p['folder']}")]
        how = "Cura package" if p["package"] else ("package folder" if p["packaged"] else "plug-in folder")
        items.append(Item("plugin", p["name"], files, f"version {p['version'] or '?'} · {how} · {_plural(len(files), 'file')}",
                          {"folder": p["folder"], "plugin_id": p["plugin_id"], "package": p["package"]}))
        claimed.update(files)

    # post-processing scripts (Cura looks in both folders)
    for root, base in (("config", cfg), ("data", data)):
        sdir = os.path.join(base, "scripts")
        if os.path.isdir(sdir):
            for fn in sorted(os.listdir(sdir)):
                if fn.endswith(".py"):
                    f = (root, f"scripts/{fn}")
                    if f not in claimed and not (root == "data" and cfg == data and ("config", f[1]) in claimed):
                        items.append(Item("script", fn[:-3], [f], f"scripts/{fn}"))
                        claimed.add(f)

    # app settings
    sfiles = [("config", "cura.cfg")] if os.path.isfile(os.path.join(cfg, "cura.cfg")) else []
    for r in _walk(data, "setting_visibility") if os.path.isdir(os.path.join(data, "setting_visibility")) else []:
        sfiles.append(("data", r))
    if sfiles:
        items.append(Item("settings", "Cura preferences", sfiles, "cura.cfg: window, visible settings, active printer"))
        claimed.update(sfiles)

    # everything else the user added (custom definitions, themes, unreferenced containers ...)
    rest: List[Tuple[str, str]] = []
    roots = [("data", data)] + ([("config", cfg)] if os.path.abspath(cfg) != os.path.abspath(data) else [])
    for root, base in roots:
        if not os.path.isdir(base):
            continue
        for r in _walk(base):
            top = r.split("/", 1)[0]
            if top in CURA_SKIP_TOP or r in ("packages.json", "plugins.json") or top == "plugins":
                continue
            f = (root, r)
            if f not in claimed and not (root == "config" and ("data", r) in claimed):
                rest.append(f)
    if rest:
        items.append(Item("other", "Other Cura files", rest, _plural(len(rest), "file") + " not covered above"))
    return items


# ---------------------------------------------------------------------------
# PrusaSlicer
# ---------------------------------------------------------------------------

PRUSA_DIRS = (("print", "profile", "print settings"), ("sla_print", "profile", "SLA print settings"),
              ("filament", "material", "filament"), ("sla_material", "material", "SLA material"),
              ("printer", "printer", "printer preset"), ("physical_printer", "printer", "physical printer (network connection)"))


def _ini_value(path: str, key: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith(key + " ="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


def _inventory_prusa(inst: Install) -> List[Item]:
    data = inst.roots["data"]
    items: List[Item] = []
    claimed: Set[Tuple[str, str]] = set()
    names: Dict[str, int] = {}
    for sub, kind, what in PRUSA_DIRS:
        d = os.path.join(data, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".ini"):
                continue
            base = fn[:-4]
            inherits = _ini_value(os.path.join(d, fn), "inherits")
            detail = what + (f" · based on {inherits}" if inherits else "")
            label = base
            if (kind, base) in [(i.kind, i.name) for i in items]:
                label = f"{base} ({what})"
            f = ("data", f"{sub}/{fn}")
            items.append(Item(kind, label, [f], detail, {"folder": sub, "inherits": inherits}))
            claimed.add(f)
    if os.path.isfile(os.path.join(data, "PrusaSlicer.ini")):
        f = ("data", "PrusaSlicer.ini")
        items.append(Item("settings", "PrusaSlicer preferences", [f], "PrusaSlicer.ini: window, selected presets, installed printer models"))
        claimed.add(f)
    rest = []
    for r in _walk(data):
        if r.split("/", 1)[0] in PRUSA_SKIP_TOP:
            continue
        if ("data", r) not in claimed:
            rest.append(("data", r))
    if rest:
        n_vendor = sum(1 for _r, r in rest if r.startswith("vendor/"))
        items.append(Item("other", "Other PrusaSlicer files", rest,
                          f"{_plural(len(rest), 'file')}: vendor bundles ({n_vendor}), custom shapes ..."))
    return items


# ---------------------------------------------------------------------------
# OrcaSlicer
# ---------------------------------------------------------------------------

ORCA_DIRS = (("process", "profile", "process"), ("filament", "material", "filament"), ("machine", "printer", "printer"))


def orca_user_dirs(inst: Install) -> List[str]:
    """Names of the folders under user/ ('default' when not signed in, an account id otherwise)."""
    udir = os.path.join(inst.roots["data"], "user")
    if not os.path.isdir(udir):
        return []
    return sorted(d for d in os.listdir(udir) if os.path.isdir(os.path.join(udir, d)))


def _inventory_orca(inst: Install) -> List[Item]:
    data = inst.roots["data"]
    items: List[Item] = []
    claimed: Set[Tuple[str, str]] = set()
    users = orca_user_dirs(inst)
    for uid in users:
        for sub, kind, what in ORCA_DIRS:
            base = os.path.join(data, "user", uid, sub)
            if not os.path.isdir(base):
                continue
            for r in _walk(data, f"user/{uid}/{sub}"):
                if not r.endswith(".json"):
                    continue
                name, inherits = os.path.basename(r)[:-5], ""
                try:
                    with open(os.path.join(data, r), encoding="utf-8") as fh:
                        j = json.load(fh)
                    name = j.get("name") or name
                    inherits = j.get("inherits") or ""
                except (OSError, ValueError):
                    pass
                files = [("data", r)]
                info = r[:-5] + ".info"
                if os.path.isfile(os.path.join(data, info)):
                    files.append(("data", info))
                label = name if len(users) == 1 else f"{name} [{uid}]"
                detail = what + (f" · based on {inherits}" if inherits else " · stand-alone")
                items.append(Item(kind, label, files, detail, {"user": uid, "folder": sub, "inherits": inherits}))
                claimed.update(files)
    pdir = os.path.join(data, "plugins")
    if os.path.isdir(pdir):
        files = [("data", r) for r in _walk(data, "plugins")]
        if files:
            items.append(Item("plugin", "Network plug-in files", files,
                              f"{_plural(len(files), 'file')} in plugins/ (the vendor network plug-in)"))
            claimed.update(files)
    if os.path.isfile(os.path.join(data, "OrcaSlicer.conf")):
        f = ("data", "OrcaSlicer.conf")
        items.append(Item("settings", "OrcaSlicer preferences", [f], "OrcaSlicer.conf: window, selected presets, chosen printer models"))
        claimed.add(f)
    rest = []
    for r in _walk(data):
        top = r.split("/", 1)[0]
        if top in ORCA_SKIP_TOP or top.startswith("user_backup"):
            continue
        if ("data", r) not in claimed:
            rest.append(("data", r))
    if rest:
        items.append(Item("other", "Other OrcaSlicer files", rest, _plural(len(rest), "file") + " not covered above"))
    return items


# ---------------------------------------------------------------------------

def inventory(inst: Install) -> List[Item]:
    fn = {"cura": _inventory_cura, "prusa": _inventory_prusa, "orca": _inventory_orca}[inst.slicer]
    items = fn(inst)
    # unique ids
    seen: Dict[str, int] = {}
    for it in items:
        if it.id in seen:
            seen[it.id] += 1
            it.name = f"{it.name} ({seen[it.id]})"
        seen[it.id] = seen.get(it.id, 1)
    items.sort(key=lambda i: (KIND_ORDER.index(i.kind), i.name.lower()))
    return items


def summary(items: Iterable[Item]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for it in items:
        out[it.kind] = out.get(it.kind, 0) + 1
    return out
