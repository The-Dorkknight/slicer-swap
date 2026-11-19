# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Back up and restore slicer items as a .slicerpack file.

A .slicerpack is a zip: slicerpack.json (what is inside, with a SHA-256 per file) plus
files/<root>/<path> copies. Restoring only ever writes into the chosen slicer's own data
folders, keeps a safety copy of every file it replaces, and reads everything back afterwards.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import platform
import re
import stat
import tempfile
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from . import __version__
from . import plugcheck
from .inventory import Item, PackagesDamaged, cura_packages, damaged_text, inventory
from .slicers import SLICER_NAMES, Install, _version_key, is_running, user_data_dir

FORMAT = 1
MANIFEST = "slicerpack.json"
EXT = ".slicerpack"


class PackError(Exception):
    pass


# ---------------------------------------------------------------------------
# secrets
# ---------------------------------------------------------------------------

CURA_SECRET_PREFS = ("ultimaker_auth_data",)
CURA_SECRET_META = ("um_cloud_cluster_id", "um_network_key", "um_linked_to_account", "host_guid", "group_name",
                    "group_size", "connection_type", "octoprint_api_key", "octoprint_id", "removal_warning",
                    "is_online", "capabilities")
INI_SECRET_KEYS = ("printhost_apikey", "printhost_password", "printhost_user", "octoprint_apikey")
ORCA_CONF_SECRET_SECTIONS = ("access_code", "user_access_code", "user")


def redact(slicer: str, relpath: str, data: bytes) -> Tuple[bytes, int]:
    """Blank passwords, API keys and account logins. Returns (data, number of values removed)."""
    low = relpath.lower()
    n = 0
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data, 0
    if slicer == "cura" and (low.endswith(".cfg")):
        keys = CURA_SECRET_PREFS + (CURA_SECRET_META if low.endswith((".global.cfg", ".extruder.cfg")) else ())
        out = []
        for line in text.splitlines(keepends=True):
            k = line.split("=", 1)[0].strip() if "=" in line else ""
            if k in keys:
                n += 1
                continue
            out.append(line)
        text = "".join(out)
    elif low.endswith(".ini"):
        out = []
        for line in text.splitlines(keepends=True):
            k = line.split("=", 1)[0].strip() if "=" in line else ""
            if k in INI_SECRET_KEYS and line.split("=", 1)[1].strip():
                n += 1
                line = f"{k} = \n"
            out.append(line)
        text = "".join(out)
    elif low.endswith((".json", ".conf")) and slicer == "orca":
        try:
            j = json.loads(text)
        except ValueError:
            return data, 0
        if isinstance(j, dict):
            for k in INI_SECRET_KEYS:
                if j.get(k):
                    j[k] = ""
                    n += 1
            if low.endswith("orcaslicer.conf"):
                for k in ORCA_CONF_SECRET_SECTIONS:
                    if j.get(k):
                        j.pop(k)
                        n += 1
            if n:
                text = json.dumps(j, indent=4, ensure_ascii=False)
    return (text.encode("utf-8"), n) if n else (data, 0)


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------

def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_rel(rel: str) -> str:
    rel = rel.replace("\\", "/")
    if rel.startswith("/") or re.match(r"^[A-Za-z]:", rel) or ".." in rel.split("/") or not rel:
        raise PackError(f"Unsafe path in backup: {rel!r}")
    return rel


def default_name(inst: Install, full: bool = False) -> str:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
    return f"{SLICER_NAMES[inst.slicer]}-{inst.version or 'backup'}-{'full-' if full else ''}{stamp}{EXT}"


def create(inst: Install, items: Iterable[Item], out_path: str, redact_secrets: bool = True,
           note: str = "", full: bool = False, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Write a .slicerpack with these items. Returns the manifest."""
    items = list(items)
    if not items:
        raise PackError("Nothing selected to back up.")
    manifest: Dict[str, Any] = {
        "format": FORMAT, "tool": f"SlicerSwap {__version__}",
        "created": datetime.datetime.now().replace(microsecond=0).isoformat(),
        "slicer": inst.slicer, "slicer_version": inst.version, "platform": platform.system(),
        "full": bool(full), "redacted": bool(redact_secrets), "note": note, "items": [],
    }
    if extra:
        manifest.update(extra)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    tmp = out_path + ".part"
    written: Dict[Tuple[str, str], Dict[str, Any]] = {}
    n_redacted = 0
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for it in items:
            entry = {"kind": it.kind, "name": it.name, "detail": it.detail, "meta": it.meta, "files": []}
            for root, rel in it.files:
                rel = _safe_rel(rel)
                src = os.path.join(inst.roots[root], *rel.split("/"))
                if not os.path.isfile(src):
                    continue
                if (root, rel) not in written:
                    with open(src, "rb") as fh:
                        data = fh.read()
                    red = 0
                    if redact_secrets:
                        data, red = redact(inst.slicer, rel, data)
                        n_redacted += red
                    mode = stat.S_IMODE(os.stat(src).st_mode)
                    zi = zipfile.ZipInfo(f"files/{root}/{rel}", date_time=datetime.datetime.fromtimestamp(
                        os.path.getmtime(src)).timetuple()[:6])
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zi.external_attr = (mode & 0xFFFF) << 16
                    zf.writestr(zi, data)
                    written[(root, rel)] = {"root": root, "path": rel, "sha256": _sha(data), "size": len(data),
                                            "exec": bool(mode & 0o111), **({"redacted": red} if red else {})}
                entry["files"].append(written[(root, rel)])
            if entry["files"]:
                manifest["items"].append(entry)
        manifest["redacted_values"] = n_redacted
        if inst.slicer == "cura":
            faulty = _faulty_plugins(zf, manifest)
            if faulty:
                manifest["warnings"] = [f"{why} It is in this backup as it is; a restore will leave it out."
                                        for why in faulty.values()]
        zf.writestr(MANIFEST, json.dumps(manifest, indent=1, ensure_ascii=False))
    if not manifest["items"]:
        os.remove(tmp)
        raise PackError("None of the selected items has files to back up.")
    os.replace(tmp, out_path)
    problems = verify(out_path)
    if problems:
        raise PackError("Backup failed its own check: " + "; ".join(problems[:3]))
    return manifest


def _faulty_plugins(zf: zipfile.ZipFile, manifest: Dict[str, Any]) -> Dict[str, str]:
    """{item id: explanation} for Cura plug-ins in a backup that would stop Cura from starting."""
    out: Dict[str, str] = {}
    names = set(zf.namelist())
    for it in manifest.get("items", []):
        if it.get("kind") != "plugin":
            continue
        files: Dict[str, bytes] = {}
        for f in it.get("files", []):
            name = f"files/{f['root']}/{f['path']}"
            if f["path"].lower().endswith(plugcheck.SCAN_EXT) and f.get("size", 0) <= plugcheck.MAX_FILE and name in names:
                files[f["path"]] = zf.read(name)
        faults = plugcheck.icon_faults(files)
        if plugcheck.stops_cura(faults):
            out[item_id(it)] = plugcheck.explain(it.get("name", "?"), faults)
    return out


def faulty_plugins(path: str) -> Dict[str, str]:
    """{item id: explanation} for the plug-ins in this backup that a restore leaves out."""
    m = read_manifest(path)
    if m["slicer"] != "cura":
        return {}
    with zipfile.ZipFile(path) as zf:
        return _faulty_plugins(zf, m)


# ---------------------------------------------------------------------------
# read / verify
# ---------------------------------------------------------------------------

def read_manifest(path: str) -> Dict[str, Any]:
    if not zipfile.is_zipfile(path):
        raise PackError("Not a .slicerpack file (not a zip archive).")
    with zipfile.ZipFile(path) as zf:
        if MANIFEST not in zf.namelist():
            raise PackError("Not a .slicerpack file (slicerpack.json missing).")
        try:
            m = json.loads(zf.read(MANIFEST).decode("utf-8"))
        except ValueError as exc:
            raise PackError(f"Backup list is damaged: {exc}")
    if not isinstance(m, dict) or m.get("format") != FORMAT or m.get("slicer") not in SLICER_NAMES:
        raise PackError("This .slicerpack was made by a newer or different version and can't be read.")
    items = m.get("items")
    if not isinstance(items, list) or not all(isinstance(it, dict) for it in items):
        raise PackError("Backup list is damaged: it has no list of items.")
    for it in items:
        it.setdefault("kind", "other")
        it.setdefault("name", "?")
        it.setdefault("meta", {})
        files = it.setdefault("files", [])
        if not isinstance(files, list) or not isinstance(it["meta"], dict):
            raise PackError(f"Backup list is damaged at '{it.get('name')}'.")
        for f in files:
            if not isinstance(f, dict) or not isinstance(f.get("path"), str) or not isinstance(f.get("sha256"), str):
                raise PackError(f"Backup list is damaged at '{it.get('name')}'.")
            _safe_rel(f["path"])
            if f.get("root") not in ("config", "data", "cache"):
                raise PackError(f"Unknown folder '{f.get('root')}' in backup.")
    if "snapshot" in m and not isinstance(m["snapshot"], dict):
        raise PackError("Backup list is damaged (safety copy details).")
    return m


def verify(path: str) -> List[str]:
    """Check every file against the hash in the list. Returns problems (empty = good)."""
    problems = []
    m = read_manifest(path)
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        for it in m["items"]:
            for f in it["files"]:
                name = f"files/{f['root']}/{f['path']}"
                if name not in names:
                    problems.append(f"missing {f['path']}")
                elif _sha(zf.read(name)) != f["sha256"]:
                    problems.append(f"damaged {f['path']}")
    return problems


def item_id(entry: Dict[str, Any]) -> str:
    return f"{entry['kind']}:{entry['name']}"


# ---------------------------------------------------------------------------
# plan / restore
# ---------------------------------------------------------------------------

@dataclass
class Action:
    item: str
    root: str
    path: str
    status: str      # new | same | differs | unsafe (a plug-in that would stop Cura starting: never written)
    target: str


@dataclass
class RestoreResult:
    written: List[str] = field(default_factory=list)
    unchanged: int = 0
    replaced: int = 0
    created: int = 0
    snapshot: Optional[str] = None
    verified: bool = False
    notes: List[str] = field(default_factory=list)
    skipped: int = 0     # plug-ins left out because they would stop Cura from starting


def _target(inst: Install, root: str, rel: str) -> str:
    base = os.path.abspath(inst.roots[root])
    dst = os.path.abspath(os.path.join(base, *_safe_rel(rel).split("/")))
    if os.path.commonpath([base, dst]) != base:
        raise PackError(f"Refusing to write outside the slicer folder: {rel}")
    return dst


def check_compatible(manifest: Dict[str, Any], inst: Install, allow_newer: bool = False) -> List[str]:
    """Raise if the backup can't go into this install; return warnings otherwise."""
    notes = []
    if manifest["slicer"] != inst.slicer:
        raise PackError(f"This backup is from {SLICER_NAMES[manifest['slicer']]}; it can't be restored into "
                        f"{SLICER_NAMES[inst.slicer]}. Use the Convert tab to move profiles between slicers.")
    pv, iv = manifest.get("slicer_version") or "", inst.version or ""
    if pv and iv and _version_key(pv)[:2] > _version_key(iv)[:2]:
        msg = (f"The backup was made with {SLICER_NAMES[inst.slicer]} {pv}, which is newer than this {iv}. "
               f"Older versions often can't read newer files.")
        if inst.slicer == "cura" and not allow_newer:
            raise PackError(msg + " Cura itself refuses this too. Tick 'allow newer' to try anyway.")
        notes.append(msg)
    elif pv and iv and _version_key(pv)[:2] < _version_key(iv)[:2]:
        notes.append(f"Backup is from version {pv}; {SLICER_NAMES[inst.slicer]} {iv} upgrades older files when it starts.")
    return notes


def plan(path: str, inst: Install, item_ids: Optional[Iterable[str]] = None,
         allow_faulty: bool = False) -> Tuple[Dict[str, Any], List[Action]]:
    """What a restore would do, without doing it."""
    m = read_manifest(path)
    if m["slicer"] != inst.slicer:
        check_compatible(m, inst)       # raises with the explanation
    wanted = set(item_ids) if item_ids is not None else None
    unsafe = {} if allow_faulty else faulty_plugins(path)
    actions: List[Action] = []
    seen = set()
    for it in m["items"]:
        iid = item_id(it)
        if wanted is not None and iid not in wanted:
            continue
        for f in it["files"]:
            if (f["root"], f["path"]) in seen:
                continue
            seen.add((f["root"], f["path"]))
            dst = _target(inst, f["root"], f["path"])
            if iid in unsafe:
                status = "unsafe"
            elif not os.path.isfile(dst):
                status = "new"
            else:
                with open(dst, "rb") as fh:
                    status = "same" if _sha(fh.read()) == f["sha256"] else "differs"
            actions.append(Action(iid, f["root"], f["path"], status, dst))
    return m, actions


def _atomic_write(dst: str, data: bytes, executable: bool = False):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".slicerswap-", dir=os.path.dirname(dst))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o755 if executable else 0o644)
        os.replace(tmp, dst)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def snapshot_dir() -> str:
    return os.path.join(user_data_dir(), "safety-copies")


def restore(path: str, inst: Install, item_ids: Optional[Iterable[str]] = None, allow_running: bool = False,
            allow_newer: bool = False, make_snapshot: bool = True,
            progress: Optional[Callable[[str], None]] = None, allow_faulty: bool = False) -> RestoreResult:
    """Put the chosen items of a backup into this install.
    A plug-in with the icon fault that stops Cura starting is left out (allow_faulty is for tests)."""
    say = progress or (lambda s: None)
    m, actions = plan(path, inst, item_ids, allow_faulty)
    res = RestoreResult()
    res.notes += check_compatible(m, inst, allow_newer)
    if not actions:
        raise PackError("Nothing selected to restore.")
    skipped = {a.item for a in actions if a.status == "unsafe"}
    if skipped:
        why = faulty_plugins(path)
        for iid in sorted(skipped):
            res.notes.append("NOT restored: " + why.get(iid, iid))
            say(f"left out  {iid.split(':', 1)[-1]} (it would stop Cura from starting)")
        actions = [a for a in actions if a.status != "unsafe"]
        res.skipped = len(skipped)
    if not allow_running and is_running(inst.slicer):
        raise PackError(f"{SLICER_NAMES[inst.slicer]} is open. Close it first: it saves its settings on exit "
                        f"and would overwrite what is restored.")
    todo = [a for a in actions if a.status != "same"]
    res.unchanged = len(actions) - len(todo)
    wanted = {a.item for a in actions}

    # 0. every file to be written is checked first, so a damaged backup changes nothing at all
    meta = {(f["root"], f["path"]): f for it in m["items"] for f in it["files"]}
    with zipfile.ZipFile(path) as zf:
        have = set(zf.namelist())
        for a in todo:
            n = f"files/{a.root}/{a.path}"
            if n not in have:
                raise PackError(f"Backup is incomplete: {a.path} is listed but missing. Nothing was changed.")
            h = hashlib.sha256()
            try:
                with zf.open(n) as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
            except (zipfile.BadZipFile, OSError, EOFError, zlib.error) as exc:
                raise PackError(f"Backup file is damaged: {a.path} ({exc}). Nothing was changed.") from None
            if h.hexdigest() != meta[(a.root, a.path)]["sha256"]:
                raise PackError(f"Backup file is damaged: {a.path}. Nothing was changed.")

    # Cura keeps a list of installed packages; plug-ins from the backup have to be added to it
    pk_path, pk_new = None, None
    if inst.slicer == "cura":
        pkgs = {it["meta"]["folder"]: it["meta"]["package"] for it in m["items"]
                if item_id(it) in wanted and it["kind"] == "plugin" and (it.get("meta") or {}).get("package")}
        try:
            pk_path, cur = cura_packages(inst, strict=True) if pkgs else (None, {})
        except PackagesDamaged as e:
            # the plug-in folders are still restored (Cura loads them from their folders); its list is left alone
            pkgs, pk_path = {}, None
            res.notes.append("Plug-ins were restored as folders only. " + damaged_text(e))
        if pkgs:
            new = json.loads(json.dumps(cur)) if cur else {}
            new.setdefault("installed", {})
            new.setdefault("to_install", {})
            new.setdefault("to_remove", [])
            new.setdefault("dismissed", [])
            for pid, entry in pkgs.items():
                new["installed"][pid] = entry
                new["to_remove"] = [x for x in new["to_remove"] if x != pid]
            if new != cur:
                pk_new = json.dumps(new, indent=4).encode("utf-8")

    # 1. safety copy of everything about to be replaced
    if make_snapshot and (todo or pk_new):
        replaced = [a for a in todo if a.status == "differs"]
        by_path = {(f["root"], f["path"]): f["sha256"] for it in m["items"] for f in it["files"]}
        created = [[a.root, a.path, by_path[(a.root, a.path)]] for a in todo if a.status == "new"]
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        os.makedirs(snapshot_dir(), exist_ok=True)
        snap, n = os.path.join(snapshot_dir(), f"{inst.slicer}-before-restore-{stamp}{EXT}"), 2
        while os.path.exists(snap):
            snap, n = os.path.join(snapshot_dir(), f"{inst.slicer}-before-restore-{stamp}-{n}{EXT}"), n + 1
        sm = {"format": FORMAT, "tool": f"SlicerSwap {__version__}", "created": datetime.datetime.now().replace(microsecond=0).isoformat(),
              "slicer": inst.slicer, "slicer_version": inst.version, "platform": platform.system(), "full": False,
              "redacted": False, "note": f"Safety copy made before restoring {os.path.basename(path)}",
              "snapshot": {"created": created, "target": inst.roots, "restored_from": os.path.basename(path)},
              "items": []}
        files = []
        with zipfile.ZipFile(snap, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for a in replaced:
                with open(a.target, "rb") as fh:
                    data = fh.read()
                zf.writestr(f"files/{a.root}/{a.path}", data)
                files.append({"root": a.root, "path": a.path, "sha256": _sha(data), "size": len(data),
                              "exec": os.access(a.target, os.X_OK)})
            if pk_new is not None and pk_path and os.path.isfile(pk_path):
                root = "data" if os.path.dirname(pk_path) == os.path.abspath(inst.roots["data"]) else "config"
                with open(pk_path, "rb") as fh:
                    data = fh.read()
                zf.writestr(f"files/{root}/packages.json", data)
                files.append({"root": root, "path": "packages.json", "sha256": _sha(data), "size": len(data), "exec": False})
            elif pk_new is not None:
                sm["snapshot"]["created"].append(["data", "packages.json", _sha(pk_new)])
            if files:
                sm["items"].append({"kind": "other", "name": "Files replaced by the restore", "detail": "", "meta": {}, "files": files})
            zf.writestr(MANIFEST, json.dumps(sm, indent=1))
        res.snapshot = snap
        say(f"Safety copy saved: {snap}")

    # 2. write
    try:
        with zipfile.ZipFile(path) as zf:
            for a in todo:
                data = zf.read(f"files/{a.root}/{a.path}")
                f = meta[(a.root, a.path)]
                if _sha(data) != f["sha256"]:
                    raise PackError(f"Backup file is damaged: {a.path}.")
                _atomic_write(a.target, data, f.get("exec", False))
                res.written.append(a.target)
                if a.status == "new":
                    res.created += 1
                else:
                    res.replaced += 1
                say(f"{'added' if a.status == 'new' else 'replaced'}  {a.path}")
        if pk_new is not None and pk_path:
            _atomic_write(pk_path, pk_new)
            res.written.append(pk_path)
            say("updated  packages.json (Cura's list of installed plug-ins)")
    except (OSError, PackError, zipfile.BadZipFile) as exc:
        back = (" Press 'Undo last restore' (or run: slicerswap undo " + inst.slicer + ") to put back everything "
                "changed so far." if res.snapshot else "")
        raise PackError(f"The restore stopped after {len(res.written)} file(s): {exc}.{back}") from None

    # 3. read back
    bad = []
    for a in todo:
        with open(a.target, "rb") as fh:
            if _sha(fh.read()) != meta[(a.root, a.path)]["sha256"]:
                bad.append(a.path)
    if bad:
        raise PackError("These files did not read back correctly after writing: " + ", ".join(bad[:5]))
    res.verified = True
    if m.get("redacted_values"):
        res.notes.append(f"This backup was made without passwords and API keys ({m['redacted_values']} left out): "
                         "sign in / re-enter printer keys in the slicer.")
    return res


def list_snapshots(slicer: Optional[str] = None) -> List[str]:
    d = snapshot_dir()
    if not os.path.isdir(d):
        return []
    def order(f: str):
        # name-stamp-HHMMSS[-N].slicerpack: newest first, and -2, -3 ... -10 after the plain one of the same second
        mt = re.search(r"(\d{8}-\d{6})(?:-(\d+))?" + re.escape(EXT) + "$", f)
        return (mt.group(1), int(mt.group(2) or 1)) if mt else ("", 0)
    return sorted((os.path.join(d, f) for f in os.listdir(d)
                   if f.endswith(EXT) and (slicer is None or f.startswith(slicer + "-"))
                   and not os.path.exists(os.path.join(d, f + ".undone"))),
                  key=lambda p: order(os.path.basename(p)), reverse=True)


def undo(snapshot: str, inst: Install, allow_running: bool = False,
         progress: Optional[Callable[[str], None]] = None) -> RestoreResult:
    """Put back the files a restore replaced, and remove the files it added (only if still unchanged)."""
    say = progress or (lambda s: None)
    m = read_manifest(snapshot)
    info = m.get("snapshot")
    if not info:
        raise PackError("That file is an ordinary backup, not a safety copy made before a restore.")
    if m["slicer"] != inst.slicer:
        raise PackError("That safety copy belongs to a different slicer.")
    if not allow_running and is_running(inst.slicer):
        raise PackError(f"{SLICER_NAMES[inst.slicer]} is open. Close it first.")
    done_mark = snapshot + ".undone"
    if os.path.exists(done_mark):
        try:
            with open(done_mark, encoding="utf-8") as fh:
                when = fh.read().strip()
        except OSError:
            when = "earlier"
        raise PackError(f"That restore was already undone ({when}). Undoing it again would overwrite changes "
                        f"made since then, so nothing was changed.")
    res = RestoreResult()
    with zipfile.ZipFile(snapshot) as zf:
        for it in m["items"]:
            for f in it["files"]:
                dst = _target(inst, f["root"], f["path"])
                _atomic_write(dst, zf.read(f"files/{f['root']}/{f['path']}"), f.get("exec", False))
                res.replaced += 1
                res.written.append(dst)
                say(f"put back  {f['path']}")
    # files the restore added: remove only when they still are exactly what was written
    for entry in info.get("created", []):
        root, rel = entry[0], entry[1]
        want = entry[2] if len(entry) > 2 else None
        dst = _target(inst, root, rel)
        if not os.path.isfile(dst):
            continue
        with open(dst, "rb") as fh:
            cur = _sha(fh.read())
        if want and cur == want:
            os.remove(dst)
            res.created += 1
            say(f"removed  {rel}")
        else:
            res.notes.append(f"Left in place (changed since the restore): {rel}")
    try:
        with open(done_mark, "w", encoding="utf-8") as fh:
            fh.write(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    except OSError as exc:
        res.notes.append(f"Could not mark the safety copy as used ({exc}); do not undo with it again.")
    res.verified = True
    return res


def describe(manifest: Dict[str, Any]) -> str:
    kinds: Dict[str, int] = {}
    for it in manifest.get("items", []):
        kinds[it["kind"]] = kinds.get(it["kind"], 0) + 1
    from .inventory import KIND_LABEL, KIND_ORDER
    one = {"profile": "print profile", "material": "material", "printer": "printer", "plugin": "plug-in",
           "script": "script", "settings": "set of app settings", "other": "group of other files"}
    many = {"profile": "print profiles", "material": "materials", "printer": "printers", "plugin": "plug-ins",
            "script": "scripts", "settings": "sets of app settings", "other": "groups of other files"}
    parts = [f"{kinds[k]} {(one if kinds[k] == 1 else many)[k]}" for k in KIND_ORDER if k in kinds]
    return (f"{SLICER_NAMES[manifest['slicer']]} {manifest.get('slicer_version', '')} backup of "
            f"{manifest.get('created', '?').replace('T', ' ')}: " + ", ".join(parts) +
            ("; passwords and keys left out" if manifest.get("redacted") else "; includes passwords/keys if any"))
