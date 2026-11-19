#!/usr/bin/env python3
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Ask the REAL Cura about plug-ins: the good case, updates, and the fault that stops Cura starting.

In a throwaway home folder (your own Cura settings are never touched) this proves, step by step:

  1. SlicerSwap refuses a plug-in whose tool-bar icon has fill on its <svg> tag.
  2. A sound tool plug-in installed by SlicerSwap is loaded by Cura, and Cura finishes starting.
  3. Installing a newer version over it gives exactly one copy, the new one.
  4. The fault is real: with the faulty plug-in copied in by hand, Cura dies while starting, although its
     log says "Loaded plugin". SlicerSwap shows the faulty one red BEFORE Cura is started, and after the
     crash it does not show the other plug-ins green.
  5. Removing the faulty plug-in with SlicerSwap lets Cura start again.
  6. The same when the faulty plug-in is on Cura's package list: SlicerSwap asks Cura to remove it, and
     Cura does so before the point where it used to crash.
  7. A plug-in switched off in Cura, and plug-ins Cura cannot load, are reported with Cura's own reason.
  8. A damaged packages.json is left alone (install refused, remove still works), and real Cura still starts
     and loads plug-ins from their folders.

    python3 tools/host_tests/check_cura_plugins.py --cura /path/to/UltiMaker-Cura.AppImage
    python3 tools/host_tests/check_cura_plugins.py --cura ... --also /path/to/SomePlugin   (must load too)

Linux only. Cura needs a display (xvfb-run works). Cura is started eight times; allow six minutes.
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
from slicerswap import install, inventory, pack, plugcheck, slicers  # noqa: E402

DATA = os.path.join(ROOT, "tests", "data")
FIXTURE = os.path.join(DATA, "cura_ender3_printer.slicerpack")
TOOL = os.path.join(DATA, "DemoToolPlugin")
DEMO = os.path.join(DATA, "DemoCuraPlugin")
failures = []


def say(ok, text):
    print(("  ok    " if ok else "  FAIL  ") + text, flush=True)
    if not ok:
        failures.append(text)


def start_cura(exe, env, out, timeout, watch=""):
    """Run Cura until the test hook reports and Cura closes, or until Cura dies. -> (report or None, exit code, seconds)"""
    e = dict(env)
    e.update({"SSW_OUT": out, "SSW_QUIT": "1", "SSW_QUIT_MS": "8000", "SSW_PLUGINS": watch})
    if os.path.exists(out):
        os.remove(out)
    began = time.time()
    with open(out + ".console.txt", "w") as log:
        proc = subprocess.Popen([exe], env=e, cwd=os.path.dirname(os.path.abspath(exe)), stdout=log, stderr=subprocess.STDOUT)
        end = began + timeout
        while time.time() < end and not os.path.isfile(out) and proc.poll() is None:
            time.sleep(1)
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    rep = None
    if os.path.isfile(out):
        with open(out, encoding="utf-8") as fh:
            rep = json.load(fh)
    return rep, proc.returncode, time.time() - began


def variant(tmp, src, name, edit):
    """A copy of a test plug-in under another folder name, changed by edit(folder)."""
    dst = os.path.join(tmp, "variants", name)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    edit(dst)
    return dst


def rewrite(path, old, new, count=1):
    with open(path, "rb") as fh:
        data = fh.read()
    assert old in data, (path, old)
    with open(path, "wb") as fh:
        fh.write(data.replace(old, new, count))


def set_meta(folder, **changes):
    p = os.path.join(folder, "plugin.json")
    with open(p, encoding="utf-8") as fh:
        meta = json.load(fh)
    meta.update(changes)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=4)


def make_faulty(folder):
    rewrite(os.path.join(folder, "demo_tool.svg"), b"<svg ", b'<svg fill="none" stroke="#000" ')
    set_meta(folder, name="Faulty Icon Tool")
    rewrite(os.path.join(folder, "__init__.py"), b"SlicerSwap Demo Tool", b"Faulty Icon Tool", 2)


def states(inst):
    return {p["plugin_id"]: (st, why) for p, st, why in install.cura_plugin_report(inst)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cura", required=True, help="Cura program: the AppImage, or AppRun of an unpacked AppImage")
    ap.add_argument("--cura-version", default="5.13", help="Settings folder name this Cura uses (default 5.13)")
    ap.add_argument("--also", action="append", default=[], metavar="PLUGIN",
                    help="Another plug-in (folder, zip or .curapackage) that must install and load as well")
    ap.add_argument("--timeout", type=int, default=420, help="Seconds to wait for each Cura start")
    ap.add_argument("--keep", action="store_true", help="Keep the throwaway home and print where it is")
    a = ap.parse_args()
    if not sys.platform.startswith("linux"):
        ap.error("this check only runs on Linux")
    home = tempfile.mkdtemp(prefix="slicerswap-plugintest-")
    env = dict(os.environ)
    env.update({"HOME": home, "XDG_CONFIG_HOME": f"{home}/.config", "XDG_DATA_HOME": f"{home}/.local/share",
                "XDG_CACHE_HOME": f"{home}/.cache"})
    for d in (".config", ".local/share", ".cache"):
        os.makedirs(os.path.join(home, d))
    v = a.cura_version
    inst = slicers.Install("cura", v, {"config": f"{home}/.config/cura/{v}", "data": f"{home}/.local/share/cura/{v}",
                                       "cache": f"{home}/.cache/cura/{v}"})
    plugins_dir = os.path.join(inst.roots["data"], "plugins")
    n = [0]

    def run(watch=""):
        n[0] += 1
        return start_cura(a.cura, env, os.path.join(home, f"run{n[0]}.json"), a.timeout, watch)

    try:
        pack.restore(FIXTURE, inst, None, allow_running=True, allow_newer=True)      # a Cura with one printer
        os.makedirs(plugins_dir, exist_ok=True)
        shutil.copytree(os.path.join(HERE, "SSWTestHook"), os.path.join(plugins_dir, "SSWTestHook"))
        faulty = variant(home, TOOL, "FaultyIconTool", make_faulty)

        print("1. A plug-in whose tool-bar icon would stop Cura is refused")
        try:
            install.install_cura_plugin(inst, faulty, allow_running=True)
            say(False, "SlicerSwap installed the faulty plug-in")
        except install.InstallError as exc:
            say("stop Cura from starting" in str(exc) and "demo_tool.svg" in str(exc), f"refused: {str(exc)[:110]}...")
        say("FaultyIconTool" not in inventory.cura_packages(inst)[1].get("to_install", {}), "nothing was queued in Cura's package list")

        print("2. A sound tool plug-in: installed by SlicerSwap, loaded by Cura, Cura finishes starting")
        extra = []
        r = install.install_cura_plugin(inst, TOOL, allow_running=True)
        say(r.verified and states(inst)["DemoToolPlugin"][0] == "waiting", "queued; SlicerSwap says 'waiting' until Cura has run")
        for src in a.also:
            info = install.read_plugin_source(src)
            install.install_cura_plugin(inst, src, allow_running=True)
            extra.append(info["plugin_id"])
        rep, code, secs = run("DemoToolPlugin," + ",".join(extra))
        say(rep is not None and code == 0, f"Cura started and closed normally ({secs:.0f} s, exit code {code})")
        if rep is None:
            return finish(a, home)
        print(f"        Cura {rep.get('cura_version')}")
        st = states(inst)
        say("DemoToolPlugin" in rep.get("active_plugins_user", []) and "DemoToolPlugin" in rep.get("user_packages", []),
            "Cura itself reports the tool plug-in as active and on its package list")
        say(st["DemoToolPlugin"][0] == "loaded", f"SlicerSwap: {st['DemoToolPlugin'][0]} - {st['DemoToolPlugin'][1]}")
        for pid in extra:
            say(pid in rep.get("active_plugins_user", []) and st.get(pid, ("",))[0] == "loaded",
                f"also loaded: {pid} - {st.get(pid, ('missing', ''))[1]}")

        print("3. A newer version installed over it: one copy, the new one")
        newer = variant(home, TOOL, "DemoToolPlugin", lambda d: set_meta(d, version="1.0.1"))
        pk_path = inventory.cura_packages(inst)[0]
        with open(pk_path, "rb") as fh:
            written_by_cura = fh.read()
        install.install_cura_plugin(inst, newer, allow_running=True)
        say(states(inst)["DemoToolPlugin"][0] == "waiting", "queued; SlicerSwap says 'waiting'")
        with open(pk_path + ".bak", "rb") as fh:
            say(fh.read() == written_by_cura, "the list Cura wrote was kept as packages.json.bak before SlicerSwap changed it")
        rep, code, secs = run("DemoToolPlugin")
        st = states(inst)
        copies = [p for p in inventory.cura_plugins(inst) if p["plugin_id"] == "DemoToolPlugin"]
        say(rep is not None and len(copies) == 1 and copies[0]["version"] == "1.0.1" and st["DemoToolPlugin"][0] == "loaded"
            and "1.0.1" in open(inventory.cura_log_path(inst), errors="replace").read().split("Loaded plugin DemoToolPlugin")[-1][:12],
            f"Cura loaded version 1.0.1; copies on disk: {len(copies)}")

        print("4. The fault is real: the faulty plug-in copied in by hand")
        shutil.copytree(faulty, os.path.join(plugins_dir, "FaultyIconTool"))
        st = states(inst)
        say(st["FaultyIconTool"][0] == "failed" and "STOPS CURA FROM STARTING" in st["FaultyIconTool"][1],
            "SlicerSwap shows it red before Cura is started: " + st["FaultyIconTool"][1][:60] + "...")
        rep, code, secs = run("DemoToolPlugin,FaultyIconTool")
        log = open(inventory.cura_log_path(inst), errors="replace").read()
        said_loaded = "Loaded plugin FaultyIconTool" in log.split("Initializing UltiMaker Cura")[-1]
        say(rep is None and code != 0, f"Cura died while starting ({secs:.0f} s, exit code {code})")
        say(said_loaded, "...although Cura's log says 'Loaded plugin FaultyIconTool' (why the log alone cannot be trusted)")
        crash = plugcheck.crash_note(inst.roots["data"], plugcheck.read_session(inventory.cura_log_path(inst)).start)
        say(bool(crash), f"Cura's own crash record: {crash or 'not found'}")
        st = states(inst)
        say(st["FaultyIconTool"][0] == "failed", "SlicerSwap still shows the faulty plug-in red")
        say(st["DemoToolPlugin"][0] == "unsure" and "NOT CONFIRMED" in st["DemoToolPlugin"][1],
            f"SlicerSwap does not show the sound plug-in green after the crash: {st['DemoToolPlugin'][0]} - {st['DemoToolPlugin'][1][:70]}...")

        print("5. Removing the faulty plug-in with SlicerSwap lets Cura start again")
        r = install.remove_cura_plugin(inst, "FaultyIconTool", allow_running=True)
        say(not os.path.exists(os.path.join(plugins_dir, "FaultyIconTool")) and os.path.isdir(r.files[0]), "moved aside, not deleted")
        rep, code, secs = run("DemoToolPlugin")
        say(rep is not None and code == 0 and states(inst)["DemoToolPlugin"][0] == "loaded",
            f"Cura starts again ({secs:.0f} s, exit code {code}) and the sound plug-in is green")

        print("6. The same with the faulty plug-in on Cura's package list")
        install.install_cura_plugin(inst, faulty, allow_running=True, allow_faulty=True)      # forced, as another installer would
        rep, code, secs = run("FaultyIconTool")
        say(rep is None and code != 0, f"Cura installed the package and died while starting ({secs:.0f} s, exit code {code})")
        st = states(inst)
        say(st.get("FaultyIconTool", ("",))[0] == "failed" and "STOPS CURA" in st["FaultyIconTool"][1], "SlicerSwap shows it red")
        install.remove_cura_plugin(inst, "FaultyIconTool", allow_running=True)
        say("FaultyIconTool" in inventory.cura_packages(inst)[1].get("to_remove", []), "SlicerSwap asked Cura to remove it")
        rep, code, secs = run("DemoToolPlugin,FaultyIconTool")
        gone = not os.path.exists(os.path.join(plugins_dir, "FaultyIconTool"))
        say(rep is not None and code == 0 and gone and "FaultyIconTool" not in rep.get("active_plugins_user", []),
            f"Cura removed it before the crash point and started normally ({secs:.0f} s, exit code {code})")

        print("7. Switched off, and not loadable: Cura's own reasons are passed on")
        with open(os.path.join(inst.roots["config"], "plugins.json"), "w") as fh:
            json.dump({"disabled": ["DemoToolPlugin"], "to_install": {}, "to_remove": []}, fh)
        variant(plugins_dir, DEMO, "RaisesOnRegister", lambda d: (
            set_meta(d, name="Raises On Register"),
            rewrite(os.path.join(d, "__init__.py"), b"def register(app):", b"def register(app):\n    raise RuntimeError('boom from the test')\n")))
        variant(plugins_dir, DEMO, "MissingModule", lambda d: (
            set_meta(d, name="Missing Module"),
            rewrite(os.path.join(d, "__init__.py"), b"def getMetaData", b"import module_that_does_not_exist_xyz\n\n\ndef getMetaData")))
        variant(plugins_dir, DEMO, "TooOld", lambda d: set_meta(d, name="Too Old", api=5, supported_sdk_versions=["5.0.0"]))
        for nm in ("RaisesOnRegister", "MissingModule", "TooOld"):      # variant() puts them under plugins/variants/
            shutil.move(os.path.join(plugins_dir, "variants", nm), os.path.join(plugins_dir, nm))
        shutil.rmtree(os.path.join(plugins_dir, "variants"), ignore_errors=True)
        rep, code, secs = run("DemoToolPlugin")
        say(rep is not None and code == 0, f"Cura starts with them present ({secs:.0f} s)")
        st = states(inst)
        for pid, expect in (("DemoToolPlugin", "Switched off"), ("RaisesOnRegister", "boom from the test"),
                            ("MissingModule", "module_that_does_not_exist_xyz"), ("TooOld", "different Cura version")):
            s, why = st.get(pid, ("missing", ""))
            say(s == "failed" and expect in why, f"{pid}: {s} - {why[:120]}")

        print("8. A damaged packages.json: SlicerSwap leaves it alone, and Cura still loads plug-ins from their folders")
        with open(os.path.join(inst.roots["config"], "plugins.json"), "w") as fh:
            json.dump({"disabled": [], "to_install": {}, "to_remove": []}, fh)
        for nm in ("RaisesOnRegister", "MissingModule", "TooOld"):
            shutil.rmtree(os.path.join(plugins_dir, nm), ignore_errors=True)
        pk_path, _pk = inventory.cura_packages(inst)
        with open(pk_path, "rb") as fh:
            whole = fh.read()
        say(b"DemoToolPlugin" in whole, "DemoToolPlugin is on Cura's package list before the damage")
        broken = whole[: len(whole) // 2]           # what a crash or full disk mid-write leaves behind
        with open(pk_path, "wb") as fh:
            fh.write(broken)
        try:
            install.install_cura_plugin(inst, DEMO)
            refused = ""
        except install.InstallError as exc:
            refused = str(exc)
        with open(pk_path, "rb") as fh:
            same = fh.read() == broken
        say(bool(refused) and "wipe" in refused and same, "SlicerSwap refuses to install and changes nothing: " + refused[:90])
        try:
            res = install.remove_cura_plugin(inst, "DemoToolPlugin")
            moved = res.files[0] if res.files else ""
        except install.InstallError as exc:
            moved = ""
            say(False, f"remove refused: {exc}")
        with open(pk_path, "rb") as fh:
            same = fh.read() == broken
        say(bool(moved) and same, "Remove still works as a rescue (folder moved aside, list untouched)")
        if moved:
            shutil.move(moved, os.path.join(plugins_dir, "DemoToolPlugin"))
        rep, code, secs = run("DemoToolPlugin")
        say(rep is not None and code == 0 and "DemoToolPlugin" in rep.get("active_plugins_user", []),
            f"Real Cura starts with the damaged list and still loads DemoToolPlugin from its folder ({secs:.0f} s)")
        with open(pk_path, "rb") as fh:
            after = fh.read()
        print(f"  info  Cura {'left the damaged file as it was' if after == broken else 'rewrote the file'} "
              f"({len(after)} bytes; damaged copy was {len(broken)} bytes)")
        warn = inventory.packages_problem(inst)
        say(bool(warn), "The Plug-ins tab warning is shown: " + (warn or "")[:80])
    except Exception:      # a crash in SlicerSwap is a failed check too; still clean up and report
        import traceback
        traceback.print_exc()
        failures.append("the check itself stopped with an error")
    return finish(a, home)


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
