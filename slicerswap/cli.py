# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Command line interface. Run with no arguments to open the window."""
from __future__ import annotations

import argparse
import os
import sys

from . import VERSION_LINE
from .convert import FORMATS, Options, convert

COMMANDS = ("list", "backup", "restore", "undo", "plugin", "gui")

EPILOG = """other commands (each has its own --help):
  slicerswap list                         slicers found here and what they hold
  slicerswap backup cura -o my.slicerpack back up profiles, printers, plug-ins and settings
  slicerswap restore my.slicerpack        put a backup back (asks nothing: use --dry-run first)
  slicerswap undo cura                    undo the last restore
  slicerswap plugin install X.curapackage hand a plug-in to Cura; then: slicerswap plugin check
"""


def _pick_install(slicer, version=None, folder=None):
    from . import slicers
    if folder:
        inst = slicers.from_folder(folder)
        if inst is None:
            raise SystemExit(f"Error: {folder} is not a Cura, PrusaSlicer or OrcaSlicer settings folder.")
        if slicer and inst.slicer != slicer:
            raise SystemExit(f"Error: {folder} belongs to {slicers.SLICER_NAMES[inst.slicer]}, not {slicers.SLICER_NAMES[slicer]}.")
        return inst
    found = [i for i in slicers.detect() if (not slicer or i.slicer == slicer)
             and (not version or (i.version or "").startswith(version))]
    if not found:
        what = slicers.SLICER_NAMES.get(slicer, "slicer")
        raise SystemExit(f"Error: no {what} settings found on this computer"
                         f"{' for version ' + version if version else ''}. Use --folder to point at them.")
    if len(found) > 1:
        print(f"Several found; using {found[0].label} ({found[0].main_folder}). Use --slicer-version or --folder to choose another.",
              file=sys.stderr)
    return found[0]


def _add_target(p):
    p.add_argument("--slicer-version", dest="version", help="Slicer version to use when several are installed (e.g. 5.8)")
    p.add_argument("--folder", help="Settings folder to use instead of the detected one")


def _cmd_list(a) -> int:
    from . import inventory, slicers
    insts = [slicers.from_folder(a.folder)] if a.folder else slicers.detect()
    insts = [i for i in insts if i is not None]
    if not insts:
        print("No Cura, PrusaSlicer or OrcaSlicer settings found.")
        return 0
    for i in insts:
        print(f"{i.label}{'   [open now]' if slicers.is_running(i.slicer) else ''}")
        for root, path in i.roots.items():
            if root != "cache":
                print(f"    {root + ':':8s}{path}")
        items = inventory.inventory(i)
        for kind in inventory.KIND_ORDER:
            group = [it for it in items if it.kind == kind]
            if not group:
                continue
            print(f"  {inventory.KIND_LABEL[kind]} ({len(group)})")
            if kind != "other" or a.all:
                for it in group:
                    print(f"    - {it.name}   [{it.detail}]")
        print()
    return 0


def _cmd_backup(a) -> int:
    from . import inventory, pack
    inst = _pick_install(a.slicer, a.version, a.folder)
    items = inventory.inventory(inst)
    kinds = set(a.only) if a.only else {k for k in inventory.KIND_ORDER if (a.everything or k != "other")}
    chosen = [it for it in items if it.kind in kinds]
    if a.name:
        chosen = [it for it in chosen if any(n.lower() in it.name.lower() for n in a.name)]
    out = a.out or pack.default_name(inst, a.everything)
    if os.path.isdir(out):
        out = os.path.join(out, pack.default_name(inst, a.everything))
    m = pack.create(inst, chosen, out, redact_secrets=not a.keep_secrets, full=a.everything)
    print(f"Saved and checked: {out}")
    print(pack.describe(m) + ".")
    if m.get("redacted_values"):
        print(f"{m['redacted_values']} password/key value(s) left out (use --keep-secrets to include them).")
    for w in m.get("warnings", []):
        print("Warning:", w)
    return 0


def _cmd_restore(a) -> int:
    from . import pack
    m = pack.read_manifest(a.pack)
    inst = _pick_install(m["slicer"], a.version, a.folder)
    ids = None
    if a.item:
        ids = [pack.item_id(it) for it in m["items"] if any(n.lower() in it["name"].lower() for n in a.item)]
    elif not a.everything:
        ids = [pack.item_id(it) for it in m["items"] if it["kind"] not in ("other", "settings")]
    print(pack.describe(m) + ".")
    print(f"Target: {inst.label} ({inst.main_folder})")
    _m, actions = pack.plan(a.pack, inst, ids)
    for st, word in (("new", "add"), ("differs", "replace"), ("same", "identical, skip")):
        n = sum(1 for x in actions if x.status == st)
        print(f"  {word}: {n} file(s)")
    for iid, why in pack.faulty_plugins(a.pack).items():
        if any(x.item == iid for x in actions):
            print(f"  LEFT OUT: {why}")
    if a.dry_run:
        for x in actions:
            if x.status in ("new", "differs"):
                print(f"    {'add    ' if x.status == 'new' else 'replace'}  {x.path}")
        print("Dry run: nothing was changed.")
        return 0
    res = pack.restore(a.pack, inst, ids, allow_running=a.force_running, allow_newer=a.allow_newer,
                       progress=(print if a.verbose else None))
    print(f"Restored: {res.created} added, {res.replaced} replaced, {res.unchanged} identical. "
          f"{'Every file read back correctly.' if res.verified else 'NOT verified.'}")
    if res.snapshot:
        print(f"Safety copy of replaced files: {res.snapshot}   (undo with: slicerswap undo {m['slicer']})")
    for n in res.notes:
        print("Note:", n)
    return 0


def _cmd_undo(a) -> int:
    from . import pack
    inst = _pick_install(a.slicer, a.version, a.folder)
    snaps = pack.list_snapshots(a.slicer)
    if not snaps:
        print(f"No safety copy found in {pack.snapshot_dir()}.")
        return 1
    res = pack.undo(snaps[0], inst, allow_running=a.force_running, progress=print)
    os.replace(snaps[0], snaps[0] + ".used")
    print(f"Undone: {res.replaced} file(s) put back, {res.created} added file(s) removed.")
    for n in res.notes:
        print("Note:", n)
    return 0


def _cmd_plugin(a) -> int:
    from . import install, inventory
    inst = _pick_install("cura", a.version, a.folder)
    if a.action == "install":
        if not a.source:
            raise SystemExit("Error: give the plug-in file or folder to install.")
        res = install.install_cura_script(inst, a.source) if a.source.lower().endswith(".py") else \
            install.install_cura_plugin(inst, a.source, allow_running=a.force_running)
        for n in res.notes:
            print(n)
        for f in res.files:
            print("  wrote", f)
        return 0
    if a.action == "remove":
        if not a.source:
            raise SystemExit("Error: give the plug-in's name as shown by 'slicerswap plugin list'.")
        match = [p for p in inventory.cura_plugins(inst) if a.source in (p["folder"], p["plugin_id"], p["name"])]
        if not match:
            raise SystemExit(f"Error: no plug-in called '{a.source}' in {inst.label}.")
        res = install.remove_cura_plugin(inst, match[0]["folder"] or match[0]["plugin_id"], allow_running=a.force_running)
        for n in res.notes:
            print(n)
        return 0
    report = install.cura_plugin_report(inst)
    print(f"{inst.label}: {len(report)} user plug-in(s)")
    warn = inventory.packages_problem(inst)
    if warn:
        print("WARNING: " + warn)
    bad = 0
    for p, st, why in report:
        bad += st in ("failed", "unsure")
        print(f"  [{st:7s}] {p['name']} {p['version']}  -  {why}")
    if any(st == "loaded" for _p, st, _w in report):
        print(install.WHERE_HINT)
    return 1 if (a.action == "check" and bad) else 0


def _subcommand(argv) -> int:
    ap = argparse.ArgumentParser(prog="slicerswap")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="Show the slicers found and what they hold")
    p.add_argument("--folder", help="Look at this settings folder instead")
    p.add_argument("--all", action="store_true", help="Also list every 'other' file")
    p = sub.add_parser("backup", help="Save profiles, printers, plug-ins and settings to a .slicerpack")
    p.add_argument("slicer", choices=FORMATS)
    p.add_argument("-o", "--out", help="File (or folder) to write")
    p.add_argument("--only", nargs="+", choices=["profile", "material", "printer", "plugin", "script", "settings", "other"],
                   help="Kinds to include (default: everything except 'other')")
    p.add_argument("--name", nargs="+", help="Only items whose name contains one of these")
    p.add_argument("--everything", action="store_true", help="Full backup: also custom definitions, vendor bundles ...")
    p.add_argument("--keep-secrets", action="store_true", help="Keep passwords, API keys and logins in the backup")
    _add_target(p)
    p = sub.add_parser("restore", help="Put a .slicerpack back into the slicer it came from")
    p.add_argument("pack")
    p.add_argument("--item", nargs="+", help="Only items whose name contains one of these")
    p.add_argument("--everything", action="store_true", help="Also restore app settings and 'other' files")
    p.add_argument("--dry-run", action="store_true", help="Only show what would happen")
    p.add_argument("--allow-newer", action="store_true", help="Allow a backup from a newer Cura")
    p.add_argument("--force-running", action="store_true", help="Do it even if the slicer seems to be open")
    p.add_argument("-v", "--verbose", action="store_true")
    _add_target(p)
    p = sub.add_parser("undo", help="Undo the last restore into a slicer")
    p.add_argument("slicer", choices=FORMATS)
    p.add_argument("--force-running", action="store_true")
    _add_target(p)
    p = sub.add_parser("plugin", help="Cura plug-ins: install, check, list, remove")
    p.add_argument("action", choices=["install", "check", "list", "remove"])
    p.add_argument("source", nargs="?", help=".curapackage, zip, plug-in folder or .py script (install); name (remove)")
    p.add_argument("--force-running", action="store_true")
    _add_target(p)
    p = sub.add_parser("gui", help="Open the window")
    p.add_argument("--tab", choices=["slicers", "convert", "backup", "restore", "plugins"])
    p.add_argument("--folder", action="append", default=[], help="Extra slicer settings folder(s) to show")
    p.add_argument("files", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "gui":
        from .gui import run
        return run({"tab": a.tab, "folders": a.folder, "files": a.files})
    from .install import InstallError
    from .pack import PackError
    try:
        return {"list": _cmd_list, "backup": _cmd_backup, "restore": _cmd_restore, "undo": _cmd_undo,
                "plugin": _cmd_plugin}[a.cmd](a)
    except (PackError, InstallError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    for stream in (sys.stdout, sys.stderr):     # a console that can't show a character (old Windows code pages) must not crash us
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    if argv and argv[0] in COMMANDS:
        return _subcommand(argv)
    ap = argparse.ArgumentParser(
        prog="slicerswap", formatter_class=argparse.RawDescriptionHelpFormatter, epilog=EPILOG,
        description="Convert slicer profiles between Cura, PrusaSlicer and OrcaSlicer, back them up and install them. "
                    "Run with no arguments to open the window.")
    ap.add_argument("inputs", nargs="*", help="Profile file(s): .curaprofile/.inst.cfg/Cura .3mf, Prusa .ini/.3mf, "
                                               "Orca .json (process+filament+machine)/.3mf/.orca_printer")
    ap.add_argument("-t", "--to", dest="target", choices=FORMATS, help="Target slicer")
    ap.add_argument("-f", "--from", dest="source", choices=FORMATS, help="Source slicer (auto-detected by default)")
    ap.add_argument("-o", "--out", default=".", help="Output folder (default: current folder)")
    ap.add_argument("-n", "--name", help="Name for the new presets")
    ap.add_argument("--install", action="store_true", help="Put the result straight into the installed target slicer")
    ap.add_argument("--cura-printer", help="With --install --to cura: the printer (as named in Cura) the profile is for")
    ap.add_argument("--slicer-version", dest="slicer_version", help="With --install: slicer version when several are installed")
    ap.add_argument("--folder", help="With --install: settings folder to install into")
    ap.add_argument("--force-running", action="store_true", help="With --install: do it even if the slicer seems open")
    ap.add_argument("--cura-machine", help="Cura machine id, e.g. creality_ender3 (see --list-cura-machines)")
    ap.add_argument("--cura-material", help="Cura material id for Cura input, e.g. generic_petg_175")
    ap.add_argument("--cura-resources", help="Path to an installed Cura's resources folder (optional)")
    ap.add_argument("--orca-profiles", action="append", default=[], help="Folder(s) of Orca preset JSON used to resolve 'inherits'")
    ap.add_argument("--inherits-print", help="Make the new print/process preset inherit this system preset")
    ap.add_argument("--inherits-filament", help="...filament preset")
    ap.add_argument("--inherits-printer", help="...printer/machine preset")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="Force a canonical value, e.g. --set nozzle_temp=215 (repeatable)")
    ap.add_argument("--gui", action="store_true", help="Open the window pre-filled with these files and options")
    ap.add_argument("--list-cura-machines", action="store_true", help="List Cura machine ids and exit")
    ap.add_argument("--version", action="version", version=VERSION_LINE)
    a = ap.parse_args(argv)

    if a.list_cura_machines:
        from .cura_engine import Resources
        for mid, name in Resources(a.cura_resources).machines():
            print(f"{mid:40s} {name}")
        return 0
    if a.gui or not a.inputs or not a.target:
        from .gui import run  # open the window, pre-filled with any files/options given
        return run({"files": a.inputs, "target": a.target, "name": a.name, "out": a.out if a.out != "." else None,
                    "cura_machine": a.cura_machine, "orca_profiles": (a.orca_profiles or [None])[0],
                    "install_into": a.install, "folders": [a.folder] if a.folder else []})
    overrides = {}
    for kv in a.set:
        if "=" not in kv:
            ap.error(f"--set needs KEY=VALUE, got {kv!r}")
        k, v = kv.split("=", 1)
        try:
            overrides[k.strip()] = float(v)
        except ValueError:
            overrides[k.strip()] = v
    inh = {k: v for k, v in (("print", a.inherits_print), ("filament", a.inherits_filament),
                             ("printer", a.inherits_printer)) if v}
    opts = Options(target=a.target, source=a.source, name=a.name, outdir=a.out, cura_machine=a.cura_machine,
                   cura_material=a.cura_material, cura_resources=a.cura_resources,
                   orca_profiles=a.orca_profiles, inherits=inh, overrides=overrides)
    try:
        if a.install:
            from . import install
            inst = _pick_install(a.target, a.slicer_version, a.folder)
            rep, _res = install.send_converted(a.inputs, opts, inst, cura_printer=a.cura_printer,
                                               allow_running=a.force_running)
        else:
            rep = convert(a.inputs, opts)
    except SystemExit:
        raise
    except Exception as exc:  # show a clean message on the command line
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(rep.to_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
