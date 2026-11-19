# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Find the slicers installed on this computer and where each keeps its user data.

Folder layouts were checked against real installs of Cura 5.13, PrusaSlicer 2.7.2 and
OrcaSlicer 2.4.2 on Linux; the macOS and Windows locations come from each program's source.
"""
from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

SLICER_NAMES = {"cura": "Cura", "prusa": "PrusaSlicer", "orca": "OrcaSlicer"}
# executable names (lower case, without .exe) that mean "this slicer is open"
PROCESS_NAMES = {"cura": ("ultimaker-cura", "ultimaker_cura", "ultimaker cura", "cura", "cura_app.py"),
                 "prusa": ("prusa-slicer", "prusaslicer", "prusa-slicer-console"),
                 "orca": ("orca-slicer", "orcaslicer", "orca_slicer")}


@dataclass
class Install:
    """One copy of a slicer's user data (one per Cura version, one per PrusaSlicer/Orca data folder)."""
    slicer: str
    version: str
    roots: Dict[str, str]          # logical name -> folder. cura: config, data, cache. prusa/orca: data
    flavour: str = "standard"      # standard | flatpak | custom

    @property
    def label(self) -> str:
        extra = "" if self.flavour == "standard" else f" ({self.flavour})"
        return f"{SLICER_NAMES[self.slicer]} {self.version}{extra}".replace("  ", " ").strip()

    @property
    def key(self) -> str:
        return f"{self.slicer}:{self.version}:{self.flavour}:{self.roots.get('data', '')}"

    @property
    def main_folder(self) -> str:
        return self.roots.get("data") or next(iter(self.roots.values()))

    def path(self, root: str, *parts: str) -> str:
        return os.path.join(self.roots[root], *parts)


def _version_key(v: str):
    return [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v)]


# ---------------------------------------------------------------------------
# Cura
# ---------------------------------------------------------------------------

def _cura_base_dirs(env: Dict[str, str], home: str, system: str):
    """[(config base, data base, cache base, flavour)] - each holds one folder per Cura version."""
    out = []
    if system == "Windows":
        app = env.get("APPDATA") or os.path.join(home, "AppData", "Roaming")
        local = env.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        out.append((os.path.join(app, "cura"), os.path.join(app, "cura"), os.path.join(local, "cura"), "standard"))
    elif system == "Darwin":
        base = os.path.join(home, "Library", "Application Support", "cura")
        out.append((base, base, None, "standard"))
    else:
        cfg = env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
        data = env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
        cache = env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
        out.append((os.path.join(cfg, "cura"), os.path.join(data, "cura"), os.path.join(cache, "cura"), "standard"))
        fp = os.path.join(home, ".var", "app", "com.ultimaker.cura")
        out.append((os.path.join(fp, "config", "cura"), os.path.join(fp, "data", "cura"),
                    os.path.join(fp, "cache", "cura"), "flatpak"))
    return out


def _cura_install(version: str, cfg: str, data: str, cache_base: Optional[str], system: str, flavour: str) -> Install:
    if cache_base is None:
        cache = os.path.join(cfg, "cache")
    elif system == "Windows":
        cache = os.path.join(cache_base, version, "cache")
    else:
        cache = os.path.join(cache_base, version)
    return Install("cura", version, {"config": cfg, "data": data, "cache": cache}, flavour)


def _detect_cura(env, home, system) -> List[Install]:
    found = []
    for cfg_base, data_base, cache_base, flavour in _cura_base_dirs(env, home, system):
        versions = set()
        for base in (cfg_base, data_base):
            if os.path.isdir(base):
                versions.update(d for d in os.listdir(base)
                                if re.match(r"^\d+\.\d+", d) and os.path.isdir(os.path.join(base, d)))
        for v in versions:
            cfg, data = os.path.join(cfg_base, v), os.path.join(data_base, v)
            if os.path.isfile(os.path.join(cfg, "cura.cfg")) or os.path.isdir(os.path.join(data, "machine_instances")):
                found.append(_cura_install(v, cfg, data, cache_base, system, flavour))
    found.sort(key=lambda i: _version_key(i.version), reverse=True)
    return found


# ---------------------------------------------------------------------------
# PrusaSlicer / OrcaSlicer
# ---------------------------------------------------------------------------

def _single_dir_candidates(app: str, flatpak_ids: List[str], env, home, system):
    out = []
    if system == "Windows":
        out.append((os.path.join(env.get("APPDATA") or os.path.join(home, "AppData", "Roaming"), app), "standard"))
    elif system == "Darwin":
        out.append((os.path.join(home, "Library", "Application Support", app), "standard"))
    else:
        out.append((os.path.join(env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), app), "standard"))
        for fid in flatpak_ids:
            out.append((os.path.join(home, ".var", "app", fid, "config", app), "flatpak"))
    return out


def prusa_version(folder: str) -> str:
    try:
        with open(os.path.join(folder, "PrusaSlicer.ini"), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = re.match(r"\s*version\s*=\s*(\S+)", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return ""


def orca_version(folder: str) -> str:
    try:
        with open(os.path.join(folder, "OrcaSlicer.conf"), encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        m = re.search(r'"header"\s*:\s*"OrcaSlicer\s+([^"]+)"', text)
        if m:
            return m.group(1).strip()
        m = re.search(r'"version"\s*:\s*"([^"]+)"', text)
        if m:
            return m.group(1)
    except OSError:
        pass
    return ""


def _detect_prusa(env, home, system) -> List[Install]:
    out = []
    for suffix in ("", "-alpha", "-beta"):
        for folder, flavour in _single_dir_candidates("PrusaSlicer" + suffix, ["com.prusa3d.PrusaSlicer"], env, home, system):
            if os.path.isfile(os.path.join(folder, "PrusaSlicer.ini")) or os.path.isdir(os.path.join(folder, "print")):
                fl = flavour if not suffix else (suffix[1:] if flavour == "standard" else f"{flavour} {suffix[1:]}")
                out.append(Install("prusa", prusa_version(folder), {"data": folder}, fl))
    return out


def _detect_orca(env, home, system) -> List[Install]:
    out = []
    for folder, flavour in _single_dir_candidates("OrcaSlicer", ["io.github.softfever.OrcaSlicer", "com.orcaslicer.OrcaSlicer"],
                                                  env, home, system):
        if os.path.isfile(os.path.join(folder, "OrcaSlicer.conf")) or os.path.isdir(os.path.join(folder, "user")):
            out.append(Install("orca", orca_version(folder), {"data": folder}, flavour))
    return out


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def detect(env: Optional[Dict[str, str]] = None, home: Optional[str] = None,
           system: Optional[str] = None) -> List[Install]:
    """Every slicer data folder found in the usual places."""
    env = dict(os.environ) if env is None else env
    home = home or os.path.expanduser("~")
    system = system or platform.system()
    return _detect_cura(env, home, system) + _detect_prusa(env, home, system) + _detect_orca(env, home, system)


def from_folder(folder: str) -> Optional[Install]:
    """Recognise a slicer data folder the user points at (portable installs, --datadir folders, other disks)."""
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder):
        return None
    has = lambda *p: os.path.exists(os.path.join(folder, *p))
    if has("OrcaSlicer.conf") or (has("user") and has("system")):
        return Install("orca", orca_version(folder), {"data": folder}, "custom")
    if has("PrusaSlicer.ini") or (has("print") and has("filament") and has("printer")):
        return Install("prusa", prusa_version(folder), {"data": folder}, "custom")
    is_cfg, is_data = has("cura.cfg"), has("machine_instances") or has("quality_changes") or has("cura.log")
    if is_cfg or is_data:
        version = os.path.basename(folder)
        cfg = data = folder
        norm = folder.replace("\\", "/")
        if is_cfg and not is_data and "/.config/" in norm:
            cand = norm.replace("/.config/", "/.local/share/")
            data = cand if os.path.isdir(cand) else folder
        elif is_data and not is_cfg and "/.local/share/" in norm:
            cand = norm.replace("/.local/share/", "/.config/")
            cfg = cand if os.path.isdir(cand) else folder
        cache = os.path.join(cfg, "cache")
        if "/.config/" in cfg.replace("\\", "/"):
            cache = cfg.replace("\\", "/").replace("/.config/", "/.cache/")
        return Install("cura", version if re.match(r"^\d+\.\d+", version) else "", {"config": cfg, "data": data, "cache": cache}, "custom")
    return None


def _matches_process(line: str, names) -> bool:
    """Is one of these programs the executable of this process-list line (not merely mentioned in an argument)?"""
    low = line.strip().strip('"').lower()
    exe = re.split(r" -| /| [a-z]:\\\\", low, maxsplit=1)[0].strip()
    cands = [exe]
    base = re.split(r"[/\\\\]", exe)[-1]
    if re.match(r"^(python[\d.]*|pythonw|sh|bash|env)(\.exe)?$", base):     # script run by an interpreter
        rest = low[len(exe):].strip().split(" ")
        cands = [rest[0]] if rest and rest[0] else []
    for c in cands:
        name = re.split(r"[/\\\\]", c)[-1]
        name = name[:-4] if name.endswith(".exe") else name
        if name in names:
            return True
    return False


def is_running(slicer: str) -> bool:
    """Best effort: is this slicer open right now? (False when we cannot tell.)"""
    names = PROCESS_NAMES.get(slicer, ())
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10).stdout
            lines = [l.split(",")[0] for l in out.splitlines()]
        else:
            out = subprocess.run(["ps", "-A", "-o", "args="], capture_output=True, text=True, timeout=10).stdout
            lines = out.splitlines()
    except (OSError, subprocess.SubprocessError):
        return False
    for line in lines:
        if "slicerswap" in line.lower():
            continue
        if _matches_process(line, names):
            return True
    return False


def find_cura_programs(version: str = "", home: Optional[str] = None) -> List[tuple]:
    """[(label, command list)] for Cura programs found on this computer; the one matching `version` first, then newest."""
    import glob
    import shutil
    home = home or os.path.expanduser("~")
    found: List[tuple] = []
    if os.name == "nt":
        for base in filter(None, [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")]):
            for exe in glob.glob(os.path.join(base, "*Cura*", "*Cura.exe")):
                found.append((os.path.basename(os.path.dirname(exe)), [exe]))
    elif sys.platform == "darwin":
        for base in ("/Applications", os.path.join(home, "Applications")):
            for app in glob.glob(os.path.join(base, "*Cura*.app")):
                found.append((os.path.basename(app)[:-4], ["open", "-a", app]))
    else:
        seen = set()
        for base in ("", "Applications", "Downloads", "Desktop", "AppImages", "bin", ".local/bin", "/opt"):
            base = base if os.path.isabs(base) else os.path.join(home, base)
            for pat in ("*[Cc]ura*.AppImage", "*/*[Cc]ura*.AppImage"):
                for f in glob.glob(os.path.join(base, pat)):
                    real = os.path.realpath(f)
                    if real not in seen and os.path.isfile(real):
                        seen.add(real)
                        found.append((os.path.basename(f), [f]))
        if os.path.isdir(os.path.join(home, ".var", "app", "com.ultimaker.cura")) and shutil.which("flatpak"):
            found.append(("Cura (Flatpak)", ["flatpak", "run", "com.ultimaker.cura"]))
        for name in ("cura", "UltiMaker-Cura", "ultimaker-cura"):
            exe = shutil.which(name)
            if exe and os.path.realpath(exe) not in seen:
                seen.add(os.path.realpath(exe))
                found.append((name, [exe]))
    found.sort(key=lambda f: _version_key(".".join(re.findall(r"\d+", f[0])[:3]) or "0"), reverse=True)
    if version:        # a Cura 5.13 settings folder belongs to a Cura 5.13.x program
        want = tuple(re.findall(r"\d+", version)[:2])
        found.sort(key=lambda f: tuple(re.findall(r"\d+", f[0])[:2]) != want)
    return found


def launch(command: List[str]) -> None:
    """Start a program and let it live on its own. Raises OSError with a message a person can act on."""
    exe = command[0]
    if os.path.isabs(exe) and exe.lower().endswith(".appimage") and not os.access(exe, os.X_OK):
        raise OSError(f"{exe} is not marked as a program. Right-click it > Properties > Permissions > "
                      "tick 'Allow executing file as program', then try again.")
    kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    if os.name == "posix":
        kwargs["start_new_session"] = True
    subprocess.Popen(command, **kwargs)


def user_data_dir() -> str:
    """Where SlicerSwap keeps its own files (safety copies made before a restore)."""
    home = os.path.expanduser("~")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    elif sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share")
    return os.path.join(base, "slicerswap")
