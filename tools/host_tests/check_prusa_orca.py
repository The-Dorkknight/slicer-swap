#!/usr/bin/env python3
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Ask the REAL PrusaSlicer and OrcaSlicer whether they accept what SlicerSwap writes.

For each program this converts the test profiles, slices a small cube with the program's own
command line, and compares every value SlicerSwap wrote with what the program reports back
(PrusaSlicer: the settings block at the end of the G-code; OrcaSlicer: --export-settings).
It then installs the presets into a throwaway settings folder and checks the files are in place.

    python3 tools/host_tests/check_prusa_orca.py --prusa /usr/bin/prusa-slicer --orca /path/to/OrcaSlicer

Nothing is read from or written to your real slicer settings: everything happens in a temp folder.
OrcaSlicer needs a display even for its command line (use xvfb-run on a machine without one).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from slicerswap import install, slicers  # noqa: E402
from slicerswap.convert import Options, convert  # noqa: E402
from slicerswap.slicer_fmt import PRUSA_ADDED_IN, _parse_ini_lines, _ver  # noqa: E402

DATA = os.path.join(ROOT, "tests", "data")
CUBE = """solid cube
facet normal 0 0 -1\nouter loop\nvertex 0 0 0\nvertex 0 20 0\nvertex 20 20 0\nendloop\nendfacet
facet normal 0 0 -1\nouter loop\nvertex 0 0 0\nvertex 20 20 0\nvertex 20 0 0\nendloop\nendfacet
facet normal 0 0 1\nouter loop\nvertex 0 0 10\nvertex 20 20 10\nvertex 0 20 10\nendloop\nendfacet
facet normal 0 0 1\nouter loop\nvertex 0 0 10\nvertex 20 0 10\nvertex 20 20 10\nendloop\nendfacet
facet normal 0 -1 0\nouter loop\nvertex 0 0 0\nvertex 20 0 0\nvertex 20 0 10\nendloop\nendfacet
facet normal 0 -1 0\nouter loop\nvertex 0 0 0\nvertex 20 0 10\nvertex 0 0 10\nendloop\nendfacet
facet normal 0 1 0\nouter loop\nvertex 0 20 0\nvertex 20 20 10\nvertex 20 20 0\nendloop\nendfacet
facet normal 0 1 0\nouter loop\nvertex 0 20 0\nvertex 0 20 10\nvertex 20 20 10\nendloop\nendfacet
facet normal -1 0 0\nouter loop\nvertex 0 0 0\nvertex 0 0 10\nvertex 0 20 10\nendloop\nendfacet
facet normal -1 0 0\nouter loop\nvertex 0 0 0\nvertex 0 20 10\nvertex 0 20 0\nendloop\nendfacet
facet normal 1 0 0\nouter loop\nvertex 20 0 0\nvertex 20 20 10\nvertex 20 0 10\nendloop\nendfacet
facet normal 1 0 0\nouter loop\nvertex 20 0 0\nvertex 20 20 0\nvertex 20 20 10\nendloop\nendfacet
endsolid cube
"""
SOURCES = {
    "cura": ([os.path.join(DATA, "cura_fast_petg.inst.cfg")], {"cura_machine": "creality_ender3"}),
    "prusa": ([os.path.join(DATA, "prusa_simple.ini")], {}),
    "orca": ([os.path.join(DATA, f"orca_{k}.json") for k in ("process", "filament", "machine")], {}),
}
failures = []


def say(ok, text):
    print(("  ok    " if ok else "  FAIL  ") + text)
    if not ok:
        failures.append(text)


def norm(v):
    if isinstance(v, list):
        v = v[0] if v else ""
    v = str(v).strip().strip('"')
    try:
        return "%g" % float(v.rstrip("%")) + ("%" if v.endswith("%") else "")
    except ValueError:
        return v


def run(cmd, env=None, timeout=300):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return p.returncode, (p.stdout + p.stderr)


def check_prusa(exe, work, src, version):
    files, extra = SOURCES[src]
    out = os.path.join(work, f"prusa_from_{src}")
    name = f"From {src}"
    convert(files, Options(target="prusa", name=name, outdir=out, **extra))
    cfg = os.path.join(out, f"{name}.prusa_config.ini")
    gcode = os.path.join(out, "cube.gcode")
    code, log = run([exe, "--datadir", os.path.join(work, "prusa_data"), "--load", cfg, "--export-gcode",
                     "--output", gcode, os.path.join(work, "cube.stl")])
    sliced = code == 0 and os.path.isfile(gcode) and os.path.getsize(gcode) > 2000
    say(sliced, f"PrusaSlicer slices a cube with the profile converted from {src}" + ("" if sliced else f"\n{log[-600:]}"))
    if not sliced:
        return
    ours = {k: v for _s, k, v in _parse_ini_lines(open(cfg, encoding="utf-8").read())}
    got = {}
    for line in open(gcode, encoding="utf-8", errors="replace"):
        if line.startswith("; ") and " = " in line:
            k, v = line[2:].rstrip("\n").split(" = ", 1)
            got[k] = v.replace("\\n", "\n")
    bad, newer = [], []
    for k, v in ours.items():
        if k not in got and k in PRUSA_ADDED_IN and _ver(version) < _ver(PRUSA_ADDED_IN[k]):
            newer.append(f"{k} ({PRUSA_ADDED_IN[k]}+)")       # this PrusaSlicer is older than the setting
        elif k not in got:
            bad.append(f"{k}: not reported back")
        elif not (norm(v) == norm(got[k]) or norm(v).split(",")[0] == norm(got[k]).split(",")[0]):
            bad.append(f"{k}: wrote {norm(v)[:40]!r}, PrusaSlicer has {norm(got[k])[:40]!r}")
    known = len(ours) - len(newer)
    say(not bad, f"PrusaSlicer kept {known - len(bad)} of {known} values (from {src})" + "".join(f"\n          {b}" for b in bad))
    if newer:
        print(f"        note: ignored by this older PrusaSlicer, as the report says: {', '.join(newer)}")


def check_orca(exe, work, src):
    files, extra = SOURCES[src]
    out = os.path.join(work, f"orca_from_{src}")
    name = f"From {src}"
    convert(files, Options(target="orca", name=name, outdir=out, **extra))
    tmp = os.path.join(out, "cli")
    res = os.path.join(out, "result")
    os.makedirs(tmp)
    os.makedirs(res)
    ours = {}
    for kind in ("machine", "process", "filament"):
        j = json.load(open(os.path.join(out, f"{name}.orca_{kind}.json"), encoding="utf-8"))
        ours[kind] = dict(j)
        # OrcaSlicer 2.4's command line (not its window) insists on these two; test copies only
        j["from"] = "system"
        if kind != "machine":
            j["compatible_printers"] = [name]
        json.dump(j, open(os.path.join(tmp, f"{kind}.json"), "w", encoding="utf-8"), indent=1)
    settings = os.path.join(res, "settings.json")
    code, log = run([exe, "--datadir", os.path.join(work, "orca_data"),
                     "--load-settings", f"{tmp}/machine.json;{tmp}/process.json", "--load-filaments", f"{tmp}/filament.json",
                     "--slice", "0", "--outputdir", res, "--export-3mf", "out.3mf", "--export-settings", settings,
                     os.path.join(work, "cube.stl")])
    sliced = code == 0 and os.path.isfile(os.path.join(res, "out.3mf"))
    say(sliced, f"OrcaSlicer slices a cube with the presets converted from {src}" + ("" if sliced else f" (exit {code})\n{log[-600:]}"))
    if not sliced or not os.path.isfile(settings):
        return
    got = json.load(open(settings, encoding="utf-8"))
    skip = {"type", "name", "from", "instantiation", "inherits", "print_settings_id", "filament_settings_id",
            "printer_settings_id", "compatible_printers", "compatible_printers_condition", "version"}
    bad, n = [], 0
    for kind, j in ours.items():
        for k, v in j.items():
            if k in skip:
                continue
            n += 1
            if k not in got:
                bad.append(f"{k}: not a setting OrcaSlicer knows")
            elif norm(v) != norm(got[k]):
                bad.append(f"{k}: wrote {norm(v)[:40]!r}, OrcaSlicer has {norm(got[k])[:40]!r}")
    say(not bad, f"OrcaSlicer kept {n - len(bad)} of {n} values (from {src})" + "".join(f"\n          {b}" for b in bad))


def check_install(slicer, work, src):
    """Install into a throwaway settings folder and read everything back."""
    files, extra = SOURCES[src]
    folder = os.path.join(work, f"{slicer}_install_home")
    if slicer == "prusa":
        os.makedirs(os.path.join(folder, "print"), exist_ok=True)
        open(os.path.join(folder, "PrusaSlicer.ini"), "a").close()
    else:
        os.makedirs(os.path.join(folder, "user", "default"), exist_ok=True)
        with open(os.path.join(folder, "OrcaSlicer.conf"), "w") as fh:
            json.dump({"header": "OrcaSlicer 2.4.2", "app": {}}, fh)
    inst = slicers.from_folder(folder)
    name = f"Installed from {src}"
    _rep, result = install.send_converted(files, Options(target=slicer, name=name, outdir=work, **extra), inst, allow_running=True)
    say(result.verified and all(os.path.isfile(f) for f in result.files),
        f"{slicers.SLICER_NAMES[slicer]}: {len(result.files)} preset files installed from {src} and read back")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prusa", help="PrusaSlicer program (e.g. /usr/bin/prusa-slicer)")
    ap.add_argument("--orca", help="OrcaSlicer program (AppRun of an unpacked AppImage works)")
    ap.add_argument("--keep", action="store_true", help="Keep the temp folder and print where it is")
    a = ap.parse_args()
    if not a.prusa and not a.orca:
        ap.error("give --prusa and/or --orca")
    work = tempfile.mkdtemp(prefix="slicerswap-hosttest-")
    with open(os.path.join(work, "cube.stl"), "w") as fh:
        fh.write(CUBE)
    try:
        if a.prusa:
            code, log = run([a.prusa, "--help"])
            first = (log.strip().splitlines() or ["?"])[0]
            version = ".".join(str(x) for x in _ver(first.split("-", 1)[-1]))
            print(f"PrusaSlicer: {first}  (version {version})")
            for src in ("cura", "orca", "prusa"):
                check_prusa(a.prusa, work, src, version)
                check_install("prusa", work, src)
        if a.orca:
            print("OrcaSlicer:", a.orca)
            for src in ("cura", "prusa", "orca"):
                check_orca(a.orca, work, src)
                check_install("orca", work, src)
    finally:
        if a.keep:
            print("Kept:", work)
        else:
            shutil.rmtree(work, ignore_errors=True)
    print()
    print("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
