#!/usr/bin/env python3
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Ask the REAL Cura whether it accepts what SlicerSwap does to its settings folder.

In a throwaway home folder (your own Cura settings are never touched) this:

  1. restores a small backup (one Ender-3 printer + Cura's preferences) with SlicerSwap,
  2. converts a PrusaSlicer and an OrcaSlicer profile and installs both into that Cura,
  3. installs a demo plug-in through Cura's own package manager,
  4. starts the real Cura with a small test plug-in (SSWTestHook) that reports what Cura itself sees,
  5. checks: the printer is there, both profiles are listed and selectable, the plug-in was
     loaded (from Cura's log and package list), and every value SlicerSwap meant to set is the
     value Cura reports after the profile is switched on.

    python3 tools/host_tests/check_cura.py --cura /path/to/UltiMaker-Cura.AppImage

Linux only (it relies on XDG_* folders to give Cura a private home). Cura needs a display;
on a machine without one use:  xvfb-run -s "-screen 0 1440x900x24" python3 tools/host_tests/check_cura.py ...
Cura takes a minute or two to start the first time.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, ROOT)
from slicerswap import cura_engine as ce, cura_fmt, install, inventory, pack, slicers  # noqa: E402
from slicerswap.convert import Options, read_canonical  # noqa: E402
from slicerswap.mapping import Report  # noqa: E402

DATA = os.path.join(ROOT, "tests", "data")
FIXTURE = os.path.join(DATA, "cura_ender3_printer.slicerpack")
PRINTER = "Creality Ender-3 / Ender-3 v2"
PROFILES = {
    "From Prusa (host test)": [os.path.join(DATA, "prusa_simple.ini")],
    "From Orca (host test)": [os.path.join(DATA, f"orca_{k}.json") for k in ("process", "filament", "machine")],
}
failures = []


def say(ok, text):
    print(("  ok    " if ok else "  FAIL  ") + text, flush=True)
    if not ok:
        failures.append(text)


def start_cura(exe, env, extra, out, timeout):
    """Run Cura until the test hook has written its report and Cura has closed again."""
    e = dict(env)
    e.update(extra)
    e.update({"SSW_OUT": out, "SSW_QUIT": "1"})
    if os.path.exists(out):
        os.remove(out)
    log = open(out + ".console.txt", "w")
    proc = subprocess.Popen([exe], env=e, cwd=os.path.dirname(os.path.abspath(exe)), stdout=log, stderr=subprocess.STDOUT)
    end = time.time() + timeout
    while time.time() < end and not os.path.isfile(out) and proc.poll() is None:
        time.sleep(2)
    try:
        proc.wait(timeout=90)       # the hook asks Cura to close ~25 s later, after Cura has saved
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
    log.close()
    if not os.path.isfile(out):
        return None
    with open(out, encoding="utf-8") as fh:
        return json.load(fh)


def intended_values(files, dump):
    """Every Cura value the conversion means to produce (not only the ones written to the profile)."""
    res = ce.Resources()
    src, C, _rep = read_canonical(files, Options(target="cura"), res)
    keep = ce.minimal_changes
    ce.minimal_changes = lambda res, machine, qt, values, material=None, **_k: values
    try:
        mat = [c for c in dump["stack"] if "generic" in c]
        variant = dump["stack"][5] if len(dump["stack"]) > 5 else None
        vals, qt = cura_fmt.build_values(C, res, "creality_ender3", Report(), src,
                                         material=mat[0] if mat else None,
                                         variant=None if not variant or variant.startswith("empty") else variant)
    finally:
        ce.minimal_changes = keep
    return vals, qt


def resolver_agreement(profile_files, dump):
    """How well SlicerSwap's own re-implementation of Cura's setting formulas matches the real thing."""
    res = ce.Resources()
    prof = ce.CuraProfile(machine="creality_ender3")
    for f in profile_files:
        with open(f, encoding="utf-8") as fh:
            ce._apply(ce.read_inst_cfg_text(fh.read()), prof)
    mat = [c for c in dump["stack"] if "generic" in c]
    prof.material = mat[0] if mat else None
    variant = dump["stack"][5] if len(dump["stack"]) > 5 else None
    prof.variant = None if not variant or variant.startswith("empty") else variant
    rc = ce.resolve_profile(prof, res, machine="creality_ender3")
    same, diffs = 0, []
    for k, rec in dump["values"].items():
        t = rec.get("t")
        if "err" in rec or k not in rc.values or t in ("extruder", "optional_extruder", "polygon", "polygons", "[int]"):
            continue
        real, mine = (rec["e"] if rec.get("pe") else rec["g"]), rc.values[k]
        try:
            if t in ("float", "int"):
                ok = abs(float(real) - float(mine)) < 1e-3
            elif t == "bool":
                ok = (str(real).lower() in ("true", "1")) == bool(mine)
            else:
                ok = str(real) == str(mine)
        except (TypeError, ValueError):
            ok = str(real) == str(mine)
        if ok:
            same += 1
        else:
            diffs.append(k)
    return same, diffs


def compare(vals, dump):
    bad = []
    for k, want in sorted(vals.items()):
        rec = dump["values"].get(k)
        if rec is None:
            bad.append(f"{k}: Cura has no such setting")
            continue
        real = rec["e"] if rec.get("pe") else rec["g"]
        try:
            if isinstance(want, bool):
                ok = (str(real).lower() in ("true", "1")) == want
            elif isinstance(want, str):
                ok = str(real) == want
            else:
                ok = abs(float(real) - float(want)) < 1e-3
        except (TypeError, ValueError):
            ok = str(real) == str(want)
        if not ok:
            bad.append(f"{k}: meant {want!r}, Cura has {real!r}")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cura", required=True, help="Cura program: the AppImage, or AppRun of an unpacked AppImage")
    ap.add_argument("--cura-version", default="5.13", help="Settings folder name this Cura uses (default 5.13)")
    ap.add_argument("--timeout", type=int, default=420, help="Seconds to wait for each Cura start")
    ap.add_argument("--keep", action="store_true", help="Keep the throwaway home and print where it is")
    a = ap.parse_args()
    if platform_not_linux():
        ap.error("this check only runs on Linux")
    home = tempfile.mkdtemp(prefix="slicerswap-curatest-")
    env = dict(os.environ)
    env.update({"HOME": home, "XDG_CONFIG_HOME": f"{home}/.config", "XDG_DATA_HOME": f"{home}/.local/share",
                "XDG_CACHE_HOME": f"{home}/.cache"})
    for d in (".config", ".local/share", ".cache"):
        os.makedirs(os.path.join(home, d))
    v = a.cura_version
    inst = slicers.Install("cura", v, {"config": f"{home}/.config/cura/{v}", "data": f"{home}/.local/share/cura/{v}",
                                       "cache": f"{home}/.cache/cura/{v}"})
    try:
        print("1. Restore the printer backup into an empty Cura folder")
        res = pack.restore(FIXTURE, inst, None, allow_running=True, allow_newer=True)
        say(res.verified and res.created >= 7, f"restored {res.created} files, each read back and compared with the backup")
        machines = inventory.cura_machines(inst)
        say([m["name"] for m in machines] == [PRINTER], "SlicerSwap finds the restored printer")

        print("2. Convert two profiles and install them into that Cura")
        installed = {}
        for name, files in PROFILES.items():
            _rep, r = install.send_converted(files, Options(target="cura", name=name, outdir=home), inst, allow_running=True)
            say(r.verified and len(r.files) == 2, f"'{name}': {len(r.files)} profile files written and read back")
            installed[name] = list(r.files)

        print("3. Hand the demo plug-in to Cura's package manager")
        r = install.install_cura_plugin(inst, os.path.join(DATA, "DemoCuraPlugin"), allow_running=True)
        state, why = install.check_cura_plugin(inst, "DemoCuraPlugin")
        say(r.verified and state == "waiting", f"queued for Cura's next start ({why})")
        shutil.copytree(os.path.join(HERE, "SSWTestHook"), os.path.join(inst.roots["data"], "plugins", "SSWTestHook"))

        print("4. Start the real Cura (first start: Cura installs the plug-in; this takes a while)")
        first = start_cura(a.cura, env, {}, os.path.join(home, "run1.json"), a.timeout)
        say(first is not None and not first.get("errors"), "Cura started and the test hook reported back"
            + ("" if first else " - no report; see run1.json.console.txt in the kept folder (use --keep)"))
        if first is None:
            return finish(a, home)
        print(f"        Cura {first.get('cura_version')}, active printer: {first.get('active_machine')}")
        say(first.get("active_machine") == PRINTER and PRINTER in first.get("machines", []), "Cura shows the restored printer")
        groups = {g["name"]: g for g in first.get("quality_changes_groups", [])}
        for name in PROFILES:
            g = groups.get(name)
            say(bool(g and g["available"] and g["has_global"] and g["extruders"]),
                f"Cura lists '{name}' as a selectable custom profile" + (f" (based on '{g['quality_type']}')" if g else ""))

        print("5. Start Cura again per profile, switch the profile on and read every setting back")
        for i, (name, files) in enumerate(PROFILES.items()):
            dump_path = os.path.join(home, f"dump{i}.json")
            rep = start_cura(a.cura, env, {"SSW_ACTIVATE": name, "SSW_DUMP": dump_path, "SSW_PLUGINS": "DemoCuraPlugin"},
                             os.path.join(home, f"run{i + 2}.json"), a.timeout)
            if rep is None or not os.path.isfile(dump_path):
                say(False, f"'{name}': no report from Cura")
                continue
            say(rep.get("activated") == name and not rep.get("errors"), f"Cura switched to '{name}'")
            with open(dump_path, encoding="utf-8") as fh:
                dump = json.load(fh)
            vals, qt = intended_values(files, dump)
            bad = compare(vals, dump)
            say(not bad, f"'{name}': Cura agrees on {len(vals) - len(bad)} of {len(vals)} intended values (quality '{qt}')"
                + "".join(f"\n          {b}" for b in bad))
            same, diffs = resolver_agreement(installed[name], dump)
            print(f"        for information: SlicerSwap's own Cura calculator matches Cura on {same} of {same + len(diffs)} "
                  f"settings of this printer" + (f" (differs: {', '.join(sorted(diffs)[:8])})" if diffs else ""))
            if i == 0:
                say("DemoCuraPlugin" in rep.get("active_plugins_user", []) and "DemoCuraPlugin" in rep.get("user_packages", []),
                    "Cura itself reports the demo plug-in as active and in its package list")
        state, why = install.check_cura_plugin(inst, "DemoCuraPlugin")
        say(state == "loaded", f"SlicerSwap's own check, from Cura's log: {state} - {why}")
    except Exception:      # a crash in SlicerSwap is a failed check too; still clean up and report
        import traceback
        traceback.print_exc()
        failures.append("the check itself stopped with an error")
    return finish(a, home)


def platform_not_linux():
    return not sys.platform.startswith("linux")


def finish(a, home):
    if a.keep:
        print("Kept:", home)
    else:
        shutil.rmtree(home, ignore_errors=True)
    print()
    print("ALL CHECKS PASSED" if not failures else f"{len(failures)} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
