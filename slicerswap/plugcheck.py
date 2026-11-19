# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Checks on Cura plug-ins: a known fault that stops Cura starting, and what Cura's own files say after a start.

The fault: Cura recolours tool-bar icons by inserting fill="#rrggbb" straight after every "<svg " in the
icon file (UM/ColorImage.py). If the icon's <svg> tag already has a fill attribute, the result is invalid
XML and Cura's SVG loader takes Cura down with a segmentation fault while the window is being built.
Cura has by then already logged "Loaded plugin ...", so the log alone looks fine.
Reproduced in Cura 5.13.0 with the icon of Hybrid Supports 0.1.0-wip.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

MAX_FILE = 2_000_000          # bigger files are not icons, panels or metadata
SCAN_EXT = (".svg", ".py", ".qml")
ICON_KEY = re.compile(r"""["']icon["']\s*:\s*["']([^"']+)["']""")
SVG_REF = re.compile(r"""["']([^"']*\.svg)["']""", re.I)


# ---------------------------------------------------------------------------
# the icon fault
# ---------------------------------------------------------------------------

def svg_breaks_recolouring(data: bytes) -> bool:
    """True if this SVG is fine as it is but becomes invalid once Cura has inserted its fill attribute."""
    if b"<svg " not in data or len(data) > MAX_FILE:
        return False
    try:
        ET.fromstring(data)
    except ET.ParseError:
        return False                      # not well-formed to begin with: a different problem, cannot judge
    try:
        ET.fromstring(data.replace(b"<svg ", b'<svg fill="#000000" '))
    except ET.ParseError:
        return True
    return False


@dataclass
class Fault:
    path: str            # file inside the plug-in
    where: str           # "toolbar": used as a tool-bar icon (stops Cura starting) | "panel": recoloured in a panel
    text: str


def icon_faults(files: Dict[str, bytes]) -> List[Fault]:
    """Icon faults in one plug-in. files: {path inside the plug-in (forward slashes): content} for .svg/.py/.qml."""
    bad = {p: d for p, d in files.items() if p.lower().endswith(".svg") and svg_breaks_recolouring(d)}
    if not bad:
        return []
    by_base: Dict[str, List[str]] = {}
    for p in bad:
        by_base.setdefault(p.rsplit("/", 1)[-1], []).append(p)
    toolbar, panel = set(), set()
    for p, d in files.items():
        low = p.lower()
        if not low.endswith((".py", ".qml")):
            continue
        text = d.decode("utf-8", "replace")
        if low.endswith(".py"):
            for ref in ICON_KEY.findall(text):          # getMetaData(): {"tool": {"icon": "tool_icon.svg"}}
                toolbar.update(by_base.get(ref.replace("\\", "/").rsplit("/", 1)[-1], []))
        elif "ColorImage" in text:
            for ref in SVG_REF.findall(text):
                panel.update(by_base.get(ref.replace("\\", "/").rsplit("/", 1)[-1], []))
    out = [Fault(p, "toolbar", f"its tool-bar icon {p.rsplit('/', 1)[-1]} has a fill on the <svg> tag") for p in sorted(toolbar)]
    out += [Fault(p, "panel", f"the icon {p.rsplit('/', 1)[-1]} in one of its panels has a fill on the <svg> tag")
            for p in sorted(panel - toolbar)]
    return out


def stops_cura(faults: Iterable[Fault]) -> List[Fault]:
    return [f for f in faults if f.where == "toolbar"]


def reason(faults: List[Fault]) -> str:
    """Why, in one sentence, for a plug-in that is already installed."""
    hard = stops_cura(faults)
    if not hard:
        return ""
    icon = hard[0].path.rsplit("/", 1)[-1]
    return (f"its tool-bar icon ({icon}) has a fill attribute on the <svg> tag. Cura adds its own fill there, which makes "
            f"the file invalid and crashes Cura while its window is being built.")


def headline(name: str, faults: List[Fault]) -> str:
    """The short version, for a message box."""
    if stops_cura(faults):
        return f"'{name}' would stop Cura from starting.\n\nIts tool-bar icon has a fault that crashes Cura. It needs a fixed version from its author."
    return f"'{name}' has an icon fault that may crash Cura when one of its panels opens." if faults else ""


def explain(name: str, faults: List[Fault]) -> str:
    """One paragraph for the person at the keyboard."""
    hard = stops_cura(faults)
    if hard:
        icon = hard[0].path.rsplit("/", 1)[-1]
        return (f"'{name}' would stop Cura from starting: its tool-bar icon ({icon}) has a fill attribute on the <svg> tag. "
                f"Cura adds its own fill there to recolour tool icons, which makes the file invalid and crashes Cura "
                f"while its window is being built. It needs a fixed version from its author "
                f"(the fix is to remove fill from the <svg> tag of {icon}).")
    if faults:
        icon = faults[0].path.rsplit("/", 1)[-1]
        return (f"'{name}' has an icon ({icon}) with a fill attribute on the <svg> tag that one of its panels asks Cura "
                f"to recolour. The same fault in a tool-bar icon crashes Cura; this one may crash Cura when that panel opens.")
    return ""


def _wanted(rel: str) -> bool:
    return rel.lower().endswith(SCAN_EXT) and "__pycache__" not in rel


def faults_in_dir(folder: str) -> List[Fault]:
    files: Dict[str, bytes] = {}
    for dp, dns, fns in os.walk(folder):
        dns[:] = [d for d in dns if d not in ("__pycache__", ".git")]
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            try:
                if _wanted(rel) and os.path.getsize(full) <= MAX_FILE:
                    with open(full, "rb") as fh:
                        files[rel] = fh.read()
            except OSError:
                pass
    return icon_faults(files)


def faults_in_zip(zf: zipfile.ZipFile, prefix: str = "", names: Optional[Iterable[str]] = None) -> List[Fault]:
    """prefix: folder inside the zip that holds the plug-in ('' = top level)."""
    files: Dict[str, bytes] = {}
    for n in (names if names is not None else zf.namelist()):
        if not n.startswith(prefix) or n.endswith("/"):
            continue
        rel = n[len(prefix):]
        try:
            if _wanted(rel) and zf.getinfo(n).file_size <= MAX_FILE:
                files[rel] = zf.read(n)
        except KeyError:
            pass
    return icon_faults(files)


# ---------------------------------------------------------------------------
# what Cura's log says about its last start
# ---------------------------------------------------------------------------

LOG_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_EVENTS = [
    # (pattern with the plug-in id as group 1, kind)
    (re.compile(r"Loaded plugin (\S+)(?: (\S+))?\s*$"), "loaded"),
    (re.compile(r"Plugin \[([^\]]+)\] has been disabled"), "disabled"),
    (re.compile(r"Plugin \[([^\]]+)\] with supported sdk versions"), "incompatible"),
    (re.compile(r"Plugin \[([^\]]+)\] failed to register"), "error"),
    (re.compile(r"Plugin (\S+) did not return any objects"), "error"),
    (re.compile(r"Error loading plugin (\S+?):?\s*$"), "error"),
    (re.compile(r"Import error (?:when importing|loading module) (\S+)"), "error"),
    (re.compile(r"Plugin (\S+) was not loaded because it could not be verified"), "error"),
    (re.compile(r"Failed to parse plugin\.json for plugin (\S+)"), "error"),
    (re.compile(r"Plug-in (\S+) has (?:no getMetaData function|a getMetaData function with the wrong signature)"), "error"),
]


@dataclass
class Session:
    """Cura's most recent start, as far as cura.log tells."""
    start: Optional[str] = None          # "YYYY-MM-DD HH:MM:SS"
    booted: Optional[str] = None         # when Cura said its start-up was complete
    closed: bool = False                 # Cura said it was closing normally
    last: Optional[str] = None           # time of the last line
    events: Dict[str, Tuple[str, str, str]] = field(default_factory=dict)   # plugin id -> (kind, time, detail)
    logger_seen: bool = False            # the log plug-in loads once per start

    def finished_after(self, when: str) -> bool:
        """Did Cura get through its start-up after logging something at `when`?
        Yes if it said so, if it later closed normally, or if it kept running for a minute afterwards
        (a start-up crash ends the log within seconds)."""
        if self.booted or self.closed:
            return True
        try:
            fmt = "%Y-%m-%d %H:%M:%S"
            gap = datetime.datetime.strptime(self.last, fmt) - datetime.datetime.strptime(when, fmt)
            return gap.total_seconds() >= 60
        except (TypeError, ValueError):
            return False


def read_session(log_path: str) -> Optional[Session]:
    """None when there is no log. Only the end of a large log is read."""
    if not os.path.isfile(log_path):
        return None
    try:
        with open(log_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 6_000_000))
            lines = fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None
    s = Session()
    for i, line in enumerate(lines):
        m = LOG_TIME.match(line)
        if not m:
            continue
        t = s.last = m.group(1)
        if "UM.Application.initialize" in line and re.search(r"\]: Initializing \S", line):
            if not (s.start == t and not s.events):      # (several such lines belong to one start)
                s = Session(start=t, last=t)             # a new start: forget the one before
            continue
        if "Loaded plugin FileLogger" in line or "Loaded plugin ConsoleLogger" in line:
            if s.start is None or (s.logger_seen and "FileLogger" in line):
                s = Session(start=t, last=t)             # a log without the "Initializing" line
            s.logger_seen = True
            continue
        if "Booting Cura took" in line:
            s.booted = t
        elif "CuraApplication.closeApplication" in line or "Tell the app to exit" in line:
            s.closed = True
        if "lugin" not in line and "lug-in" not in line and "mport error" not in line:
            continue
        msg = line.split("]: ", 1)[-1]
        for rx, kind in _EVENTS:
            hit = rx.search(msg)
            if not hit:
                continue
            pid = hit.group(1)
            if kind == "loaded":
                detail = hit.group(2) or ""
            else:                                        # Cura's own words, plus the traceback's last line if there is one
                # Cura writes a traceback as further lines carrying the same "module.function [line]:" stamp
                stamp = re.search(r"\] (\S+ \[\d+\]): ", line)
                tail = []
                for nxt in lines[i + 1:i + 60] if (kind == "error" and stamp) else []:
                    if stamp.group(1) + ": " not in nxt:
                        break
                    tail.append(nxt.split("]: ", 1)[-1].strip())
                tail = [l for l in tail if l and l != "NoneType: None" and not l.startswith("Exception: ")]
                detail = re.sub(r"^Exception: ", "", msg.strip())[:300] + (f" ... {tail[-1][:200]}" if tail else "")
                if kind == "error" and s.events.get(pid, ("",))[0] == "error":
                    break                                # Cura often logs a second, vaguer error: keep the first (the cause)
            s.events[pid] = (kind, t, detail)
            break
    return s


def crash_note(data_root: str, since: Optional[str]) -> str:
    """Text of Cura's own crash record if its last start ended in one (Cura rewrites stderr.log on every start)."""
    home = os.path.expanduser("~")
    cands = [os.path.join(os.path.dirname(os.path.abspath(data_root)), "stderr.log")]
    if sys.platform == "darwin":
        cands.append(os.path.join(home, "Library", "Logs", "cura", "stderr.log"))
    elif os.name != "nt":
        cands.append(os.path.join(home, ".local", "share", "cura", "stderr.log"))
    for p in cands:
        try:
            if since:
                began = datetime.datetime.strptime(since, "%Y-%m-%d %H:%M:%S")
                if datetime.datetime.fromtimestamp(os.path.getmtime(p)) < began - datetime.timedelta(seconds=5):
                    continue                             # an older start's file
            with open(p, "rb") as fh:
                text = fh.read(MAX_FILE).decode("utf-8", "replace")
        except (OSError, ValueError):
            continue
        m = re.search(r"Fatal Python error: ([^\r\n]+)", text)
        if m:
            return m.group(1).strip()
    return ""


def disabled_plugins(config_root: str, data_root: str) -> List[str]:
    """Plug-ins switched off inside Cura (Marketplace > Manage packages)."""
    for root in (config_root, data_root):
        try:
            with open(os.path.join(root, "plugins.json"), encoding="utf-8") as fh:
                d = json.load(fh).get("disabled", [])
            if isinstance(d, list):
                return [str(x) for x in d]
        except (OSError, ValueError, AttributeError):
            continue
    return []
