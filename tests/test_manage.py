# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Tests for finding slicers, listing their contents, backup/restore and installing.

The fake settings folders below copy the layout of real Cura 5.13, PrusaSlicer 2.7.2 and
OrcaSlicer 2.4.2 folders. Run with:  python -m unittest discover -s tests
"""
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from slicerswap import cura_engine as ce  # noqa: E402
from slicerswap import gcode, install, inventory, mapping, pack, plugcheck, slicers  # noqa: E402
from slicerswap.convert import Options, read_canonical  # noqa: E402

DATA = os.path.join(HERE, "data")
ORCA = [os.path.join(DATA, n) for n in ("orca_process.json", "orca_filament.json", "orca_machine.json")]


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


# the lines real Cura 5.13 writes at the start of a run, and when its start-up is complete
LOG_START = ("2026-10-06 {t},000 - DEBUG - [MainThread] UM.Application.initialize [171]: Initializing UltiMaker Cura\n"
             "2026-10-06 {t},100 - INFO - [MainThread] UM.PluginRegistry.loadPlugin [540]: Loaded plugin FileLogger 1.0.1\n"
             "2026-10-06 {t},200 - INFO - [MainThread] UM.PluginRegistry.loadPlugin [540]: Loaded plugin ConsoleLogger 1.0.1\n")
LOG_BOOTED = "2026-10-06 {t},000 - DEBUG - [MainThread] cura.CuraApplication.run [947]: Booting Cura took 9.1 seconds\n"


def make_cura(home, version="5.13"):
    cfg = os.path.join(home, ".config", "cura", version)
    data = os.path.join(home, ".local", "share", "cura", version)
    w(os.path.join(cfg, "cura.cfg"), "[general]\nversion = 7\nultimaker_auth_data = {\"access_token\": \"SECRET-TOKEN\"}\n\n"
                                    "[cura]\nactive_machine = My Ender\n\n[metadata]\nsetting_version = 27\n")
    w(os.path.join(cfg, "plugins.json"), '{"disabled": [], "to_install": {}, "to_remove": []}')
    w(os.path.join(cfg, "scripts", "MyScript.py"), "from ..Script import Script\nclass MyScript(Script):\n    pass\n")
    w(os.path.join(data, "machine_instances", "My+Ender.global.cfg"),
      "[general]\nversion = 6\nname = My Ender\nid = My Ender\n\n[metadata]\nsetting_version = 27\ntype = machine\n"
      "octoprint_api_key = SECRET-KEY\n\n[containers]\n0 = My Ender_user\n1 = creality_ender3_my_profile\n2 = empty_intent\n"
      "3 = base_global_standard\n4 = empty_material\n5 = empty_variant\n6 = My Ender_settings\n7 = creality_ender3\n")
    w(os.path.join(data, "extruders", "creality_base_extruder_0+%232.extruder.cfg"),
      "[general]\nversion = 6\nname = Extruder 1\nid = creality_base_extruder_0 #2\n\n[metadata]\nsetting_version = 27\n"
      "type = extruder_train\nposition = 0\nmachine = My Ender\n\n[containers]\n0 = creality_base_extruder_0 #2_user\n"
      "1 = creality_base_extruder_0_my_profile\n2 = empty_intent\n3 = base_0.4_PLA_standard\n4 = generic_pla_175_creality_ender3\n"
      "5 = creality_ender3_0.4\n6 = creality_base_extruder_0 #2_settings\n7 = creality_base_extruder_0\n")
    for name, d in (("My+Ender_user", "user"), ("creality_base_extruder_0+%232_user", "user"),
                    ("My+Ender_settings", "definition_changes"), ("creality_base_extruder_0+%232_settings", "definition_changes")):
        w(os.path.join(data, d, name + ".inst.cfg"), f"[general]\nversion = 4\nname = {name}\ndefinition = creality_ender3\n\n"
                                                      f"[metadata]\ntype = {d.rstrip('s') if d == 'user' else d}\nsetting_version = 27\n\n[values]\n")
    w(os.path.join(data, "quality_changes", "creality_ender3_my_profile.inst.cfg"),
      "[general]\nversion = 4\nname = My Profile\ndefinition = creality_base\n\n[metadata]\ntype = quality_changes\n"
      "quality_type = standard\nsetting_version = 27\n\n[values]\nsupport_enable = True\n")
    w(os.path.join(data, "quality_changes", "creality_base_extruder_0_my_profile.inst.cfg"),
      "[general]\nversion = 4\nname = My Profile\ndefinition = creality_base\n\n[metadata]\ntype = quality_changes\n"
      "quality_type = standard\nsetting_version = 27\nposition = 0\n\n[values]\ninfill_sparse_density = 33\nwall_line_count = 3\n")
    w(os.path.join(data, "plugins", "LoosePlugin", "plugin.json"), '{"name": "Loose Plugin", "version": "1.2.0", "author": "A", "api": 8}')
    w(os.path.join(data, "plugins", "LoosePlugin", "__init__.py"), "def getMetaData():\n    return {}\n")
    w(os.path.join(data, "plugins", "LoosePlugin", "__pycache__", "x.pyc"), "junk")
    w(os.path.join(data, "plugins", "PkgPlugin", "PkgPlugin", "plugin.json"), '{"name": "Packaged Plugin", "version": "2.0.0", "author": "B", "api": 8}')
    w(os.path.join(data, "plugins", "PkgPlugin", "PkgPlugin", "__init__.py"), "def getMetaData():\n    return {}\n")
    w(os.path.join(data, "packages.json"), json.dumps({"installed": {"PkgPlugin": {"package_info": {"package_id": "PkgPlugin", "package_version": "2.0.0"}}},
                                                       "to_remove": [], "to_install": {}, "dismissed": []}))
    w(os.path.join(data, "cura.log"), LOG_START.format(t="10:00:00") +
      "2026-10-06 10:00:01,000 - INFO - [MainThread] UM.PluginRegistry.loadPlugin [540]: Loaded plugin LoosePlugin 1.2.0\n"
      "2026-10-06 10:00:02,000 - WARNING - [MainThread] UM.PluginRegistry.loadPlugin [543]: Plugin [PkgPlugin] failed to register: boom\n"
      + LOG_BOOTED.format(t="10:00:09"))
    return slicers.Install("cura", version, {"config": cfg, "data": data, "cache": os.path.join(home, ".cache", "cura", version)})


def make_prusa(home):
    d = os.path.join(home, ".config", "PrusaSlicer")
    w(os.path.join(d, "PrusaSlicer.ini"), "# generated by PrusaSlicer 2.7.2\nversion = 2.7.2\n\n[presets]\nprint = A\n")
    w(os.path.join(d, "print", "A.ini"), "# generated by PrusaSlicer\ninherits = 0.20mm QUALITY @MK3S\nlayer_height = 0.2\n")
    w(os.path.join(d, "filament", "B.ini"), "temperature = 215\n")
    w(os.path.join(d, "printer", "C.ini"), "nozzle_diameter = 0.4\n")
    w(os.path.join(d, "physical_printer", "D.ini"), "print_host = 192.168.1.20\nprinthost_apikey = SECRET-KEY\nprinter_technology = FFF\n")
    w(os.path.join(d, "vendor", "PrusaResearch.ini"), "[vendor]\nname = Prusa Research\n")
    w(os.path.join(d, "cache", "x.idx"), "cache")
    w(os.path.join(d, "snapshots", "s1", "snapshot.ini"), "snap")
    return slicers.Install("prusa", "2.7.2", {"data": d})


def make_orca(home):
    d = os.path.join(home, ".config", "OrcaSlicer")
    w(os.path.join(d, "OrcaSlicer.conf"), json.dumps({"header": "OrcaSlicer 2.4.2", "app": {"language": "en_GB"},
                                                      "access_code": {"00M00A": "12345678"}}))
    for sub, extra in (("process", {"layer_height": "0.2"}), ("filament", {"nozzle_temperature": ["230"]}),
                       ("machine", {"printhost_apikey": "SECRET-KEY", "print_host": "192.168.1.30"})):
        w(os.path.join(d, "user", "default", sub, "Mine.json"),
          json.dumps(dict({"type": sub, "name": "Mine", "from": "User", "inherits": "", "version": "2.4.2.0"}, **extra)))
        w(os.path.join(d, "user", "default", sub, "Mine.info"), "sync_info = \nuser_id = \nsetting_id = \nbase_id = \nupdated_time = 1\n")
    w(os.path.join(d, "system", "Custom", "machine", "x.json"), "{}")
    w(os.path.join(d, "log", "debug.log.0"), "log")
    w(os.path.join(d, ".orcaslicer_machine_id"), "abc")
    return slicers.Install("orca", "2.4.2", {"data": d})


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ssw-test-")
        self.home = os.path.join(self.tmp, "home")
        self._snap, self._run = pack.snapshot_dir, (slicers.is_running, pack.is_running, install.is_running)
        snap = os.path.join(self.tmp, "safety")
        pack.snapshot_dir = lambda: snap
        slicers.is_running = pack.is_running = install.is_running = lambda s: False

    def tearDown(self):
        pack.snapshot_dir = self._snap
        slicers.is_running, pack.is_running, install.is_running = self._run
        shutil.rmtree(self.tmp, ignore_errors=True)

    def zipnames(self, path):
        with zipfile.ZipFile(path) as zf:
            return zf.namelist()

    def zipread(self, path, name):
        with zipfile.ZipFile(path) as zf:
            return zf.read(name).decode("utf-8")


class Detection(Base):
    def test_linux_all_three(self):
        make_cura(self.home)
        make_cura(self.home, "5.8")
        make_prusa(self.home)
        make_orca(self.home)
        found = slicers.detect(env={}, home=self.home, system="Linux")
        self.assertEqual([(i.slicer, i.version) for i in found],
                         [("cura", "5.13"), ("cura", "5.8"), ("prusa", "2.7.2"), ("orca", "2.4.2")])
        cura = found[0]
        self.assertTrue(cura.roots["config"].endswith(os.path.join(".config", "cura", "5.13")))
        self.assertTrue(cura.roots["data"].endswith(os.path.join(".local", "share", "cura", "5.13")))
        self.assertEqual(found[0].label, "Cura 5.13")

    def test_xdg_and_flatpak(self):
        fp = os.path.join(self.home, ".var", "app", "com.orcaslicer.OrcaSlicer", "config", "OrcaSlicer")
        w(os.path.join(fp, "OrcaSlicer.conf"), '{"header": "OrcaSlicer 2.3.0"}')
        w(os.path.join(self.tmp, "xdgc", "PrusaSlicer", "PrusaSlicer.ini"), "version = 2.9.2\n")
        found = slicers.detect(env={"XDG_CONFIG_HOME": os.path.join(self.tmp, "xdgc")}, home=self.home, system="Linux")
        self.assertEqual([(i.slicer, i.version, i.flavour) for i in found],
                         [("prusa", "2.9.2", "standard"), ("orca", "2.3.0", "flatpak")])

    def test_mac_and_windows_locations(self):
        mac = os.path.join(self.home, "Library", "Application Support")
        w(os.path.join(mac, "cura", "5.8", "cura.cfg"), "[general]\n")
        w(os.path.join(mac, "OrcaSlicer", "OrcaSlicer.conf"), '{"header": "OrcaSlicer 2.4.2"}')
        found = slicers.detect(env={}, home=self.home, system="Darwin")
        self.assertEqual([i.slicer for i in found], ["cura", "orca"])
        self.assertEqual(found[0].roots["config"], found[0].roots["data"])
        app = os.path.join(self.tmp, "AppData", "Roaming")
        w(os.path.join(app, "PrusaSlicer", "PrusaSlicer.ini"), "version = 2.9.3\n")
        w(os.path.join(app, "cura", "5.9", "cura.cfg"), "[general]\n")
        found = slicers.detect(env={"APPDATA": app, "LOCALAPPDATA": os.path.join(self.tmp, "AppData", "Local")},
                               home=self.home, system="Windows")
        self.assertEqual([(i.slicer, i.version) for i in found], [("cura", "5.9"), ("prusa", "2.9.3")])
        self.assertTrue(found[0].roots["cache"].endswith(os.path.join("cura", "5.9", "cache")))

    def test_from_folder(self):
        c, p, o = make_cura(self.home), make_prusa(self.home), make_orca(self.home)
        self.assertEqual(slicers.from_folder(p.roots["data"]).slicer, "prusa")
        self.assertEqual(slicers.from_folder(o.roots["data"]).version, "2.4.2")
        got = slicers.from_folder(c.roots["data"])
        self.assertEqual((got.slicer, got.version), ("cura", "5.13"))
        self.assertEqual(os.path.normpath(got.roots["config"]), os.path.normpath(c.roots["config"]))
        self.assertIsNone(slicers.from_folder(self.tmp))


class Inventory(Base):
    def test_cura(self):
        inst = make_cura(self.home)
        items = {i.id: i for i in inventory.inventory(inst)}
        self.assertEqual(sorted(items), ["plugin:Loose Plugin", "plugin:Packaged Plugin", "printer:My Ender",
                                         "profile:My Profile", "script:MyScript", "settings:Cura preferences"])
        printer = {f[1] for f in items["printer:My Ender"].files}
        # the stack, its extruder, their own containers AND the custom profile the stack points at
        for need in ("machine_instances/My+Ender.global.cfg", "extruders/creality_base_extruder_0+%232.extruder.cfg",
                     "user/My+Ender_user.inst.cfg", "definition_changes/My+Ender_settings.inst.cfg",
                     "quality_changes/creality_ender3_my_profile.inst.cfg",
                     "quality_changes/creality_base_extruder_0_my_profile.inst.cfg"):
            self.assertIn(need, printer)
        self.assertEqual(len(items["profile:My Profile"].files), 2)
        loose = [f[1] for f in items["plugin:Loose Plugin"].files]
        self.assertEqual(sorted(loose), ["plugins/LoosePlugin/__init__.py", "plugins/LoosePlugin/plugin.json"])  # no __pycache__
        self.assertIsNotNone(items["plugin:Packaged Plugin"].meta["package"])
        self.assertEqual(items["script:MyScript"].files, [("config", "scripts/MyScript.py")])
        self.assertEqual([m["definition"] for m in inventory.cura_machines(inst)], ["creality_ender3"])

    def test_prusa_and_orca(self):
        p = {i.id: i for i in inventory.inventory(make_prusa(self.home))}
        self.assertEqual(sorted(k for k in p if not k.startswith("other")),
                         ["material:B", "printer:C", "printer:D", "profile:A", "settings:PrusaSlicer preferences"])
        other = [f[1] for f in p["other:Other PrusaSlicer files"].files]
        self.assertEqual(other, ["vendor/PrusaResearch.ini"])                      # cache and snapshots skipped
        self.assertIn("based on 0.20mm QUALITY @MK3S", p["profile:A"].detail)
        o = {i.id: i for i in inventory.inventory(make_orca(self.home))}
        self.assertEqual(sorted(o), ["material:Mine", "printer:Mine", "profile:Mine", "settings:OrcaSlicer preferences"])
        self.assertEqual(sorted(f[1] for f in o["profile:Mine"].files),
                         ["user/default/process/Mine.info", "user/default/process/Mine.json"])


class BackupRestore(Base):
    def test_backup_leaves_out_secrets(self):
        for make in (make_cura, make_prusa, make_orca):
            inst = make(self.home)
            out = os.path.join(self.tmp, inst.slicer + ".slicerpack")
            m = pack.create(inst, inventory.inventory(inst), out, full=True)
            self.assertEqual(pack.verify(out), [])
            self.assertGreaterEqual(m["redacted_values"], 1)
            with zipfile.ZipFile(out) as zf:
                blob = b"".join(zf.read(n) for n in zf.namelist())
            self.assertNotIn(b"SECRET", blob, inst.slicer)
            self.assertNotIn(b"12345678", blob)
            keep = os.path.join(self.tmp, inst.slicer + "-keep.slicerpack")
            pack.create(inst, inventory.inventory(inst), keep, redact_secrets=False)
            with zipfile.ZipFile(keep) as zf:
                blob = b"".join(zf.read(n) for n in zf.namelist())
            self.assertIn(b"SECRET", blob)

    def test_restore_into_empty_then_identical(self):
        src = make_cura(self.home)
        out = os.path.join(self.tmp, "c.slicerpack")
        pack.create(src, inventory.inventory(src), out, redact_secrets=False)
        h2 = os.path.join(self.tmp, "home2")
        dst = slicers.Install("cura", "5.13", {"config": os.path.join(h2, "cfg"), "data": os.path.join(h2, "data"),
                                               "cache": os.path.join(h2, "cache")})
        res = pack.restore(out, dst)
        self.assertTrue(res.verified)
        self.assertEqual(res.replaced, 0)
        self.assertEqual(sorted(i.id for i in inventory.inventory(dst)), sorted(i.id for i in inventory.inventory(src)))
        # Cura's own package list was rebuilt for the packaged plug-in
        _p, pk = inventory.cura_packages(dst)
        self.assertIn("PkgPlugin", pk["installed"])
        _m, actions = pack.plan(out, dst)
        self.assertEqual({a.status for a in actions}, {"same"})

    def test_replace_snapshot_and_undo(self):
        inst = make_prusa(self.home)
        out = os.path.join(self.tmp, "p.slicerpack")
        pack.create(inst, inventory.inventory(inst), out)
        a = os.path.join(inst.roots["data"], "print", "A.ini")
        original = open(a).read()
        w(a, "layer_height = 0.3\n")
        os.remove(os.path.join(inst.roots["data"], "filament", "B.ini"))
        res = pack.restore(out, inst, ["profile:A", "material:B"])
        self.assertEqual((res.replaced, res.created), (1, 1))
        self.assertEqual(open(a).read(), original)
        self.assertTrue(os.path.isfile(res.snapshot))
        un = pack.undo(res.snapshot, inst)
        self.assertEqual((un.replaced, un.created), (1, 1))
        self.assertEqual(open(a).read(), "layer_height = 0.3\n")
        self.assertFalse(os.path.exists(os.path.join(inst.roots["data"], "filament", "B.ini")))

    def test_undo_keeps_files_changed_since(self):
        inst = make_prusa(self.home)
        out = os.path.join(self.tmp, "p.slicerpack")
        pack.create(inst, inventory.inventory(inst), out)
        b = os.path.join(inst.roots["data"], "filament", "B.ini")
        os.remove(b)
        res = pack.restore(out, inst, ["material:B"])
        w(b, "temperature = 240\n")                      # the user edited it afterwards
        un = pack.undo(res.snapshot, inst)
        self.assertTrue(os.path.exists(b))
        self.assertTrue(un.notes)

    def test_refusals(self):
        cura, prusa = make_cura(self.home), make_prusa(self.home)
        out = os.path.join(self.tmp, "c.slicerpack")
        pack.create(cura, inventory.inventory(cura), out)
        with self.assertRaises(pack.PackError):                       # wrong slicer
            pack.restore(out, prusa)
        older = slicers.Install("cura", "5.2", dict(cura.roots))
        with self.assertRaises(pack.PackError):                       # backup newer than target Cura
            pack.restore(out, older)
        pack.is_running = lambda s: True
        with self.assertRaises(pack.PackError):                       # slicer open
            pack.restore(out, cura)
        with self.assertRaises(pack.PackError):
            pack.read_manifest(os.path.join(DATA, "prusa_simple.ini"))

    def test_hostile_pack_cannot_escape(self):
        inst = make_prusa(self.home)
        evil = os.path.join(self.tmp, "evil.slicerpack")
        for bad in ("../../outside.ini", "/etc/passwd", "print/../../x.ini", "C:/x.ini"):
            m = {"format": 1, "slicer": "prusa", "slicer_version": "2.7.2", "created": "x",
                 "items": [{"kind": "profile", "name": "x", "detail": "", "meta": {},
                            "files": [{"root": "data", "path": bad, "sha256": "0", "size": 1}]}]}
            with zipfile.ZipFile(evil, "w") as zf:
                zf.writestr("slicerpack.json", json.dumps(m))
                zf.writestr("files/data/" + bad, "x")
            with self.assertRaises(pack.PackError, msg=bad):
                pack.restore(evil, inst)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "outside.ini")))


class Installing(Base):
    def test_prusa_presets_never_overwrite(self):
        inst = make_prusa(self.home)
        r1 = install.send_converted(ORCA, Options(target="prusa", name="A"), inst)[1]
        self.assertEqual(r1.name, "A (2)")                                 # print/A.ini already existed
        for sub in ("print", "filament", "printer"):
            self.assertTrue(os.path.isfile(os.path.join(inst.roots["data"], sub, "A (2).ini")))
        self.assertIn("layer_height = 0.2", open(os.path.join(inst.roots["data"], "print", "A.ini")).read())
        txt = open(os.path.join(inst.roots["data"], "print", "A (2).ini")).read()
        self.assertIn("layer_height = 0.16", txt)
        self.assertNotIn("nozzle_diameter", txt)                           # printer keys stay in the printer preset

    def test_orca_presets_have_what_orca_needs(self):
        inst = make_orca(self.home)
        rep, res = install.send_converted([os.path.join(DATA, "prusa_simple.ini")], Options(target="orca", name="From Prusa"), inst)
        base = os.path.join(inst.roots["data"], "user", "default")
        for sub in ("process", "filament", "machine"):
            j = json.load(open(os.path.join(base, sub, "From Prusa.json")))
            self.assertEqual(j["version"], "2.4.2.0")                      # Orca ignores user presets without a version
            self.assertEqual((j["from"], j["type"], j["name"]), ("User", sub, "From Prusa"))
            self.assertIn("updated_time", open(os.path.join(base, sub, "From Prusa.info")).read())
        mach = json.load(open(os.path.join(base, "machine", "From Prusa.json")))
        self.assertIn("machine_max_speed_x", mach)                         # Orca's name, not Prusa's feedrate
        self.assertNotIn("machine_max_feedrate_x", mach)

    def test_cura_profile_split_like_curas_importer(self):
        inst = make_cura(self.home)
        rep, res = install.send_converted([os.path.join(DATA, "prusa_simple.ini")], Options(target="cura", name="Sent"), inst)
        q = os.path.join(inst.roots["data"], "quality_changes")
        g = ce.read_inst_cfg_text(open(os.path.join(q, "creality_ender3_sent.inst.cfg")).read())
        e = ce.read_inst_cfg_text(open(os.path.join(q, "creality_base_extruder_0_sent.inst.cfg")).read())
        self.assertEqual((g.general["name"], g.general["definition"], g.metadata["type"]), ("Sent", "creality_base", "quality_changes"))
        self.assertEqual(e.metadata["position"], "0")
        self.assertNotIn("position", g.metadata)
        self.assertIn("support_enable", g.values)                          # not settable per extruder -> global container
        self.assertIn("wall_line_count", e.values)
        self.assertNotIn("wall_line_count", g.values)
        self.assertEqual(g.values["material_bed_temperature"], "60")       # must be explicit: the material sets it otherwise
        self.assertIn(g.metadata["quality_type"], ce.Resources().quality_types("creality_ender3"))
        with self.assertRaises(install.InstallError):
            install.send_converted(ORCA, Options(target="cura"), inst, cura_printer="No such printer")

    def test_same_slicer_files_are_copied_not_converted(self):
        inst = make_orca(self.home)
        rep, res = install.send_converted(ORCA, Options(target="orca"), inst)
        j = json.load(open(os.path.join(inst.roots["data"], "user", "default", "process", "Test 0.16mm.json")))
        self.assertEqual(j["sparse_infill_pattern"], "crosshatch")
        self.assertEqual(j["version"], "2.4.2.0")
        self.assertTrue(any("nothing was converted" in n for n in rep.notes))

    def test_refuses_while_slicer_is_open(self):
        inst = make_prusa(self.home)
        install.is_running = lambda s: True
        with self.assertRaises(install.InstallError):
            install.send_converted(ORCA, Options(target="prusa"), inst)


class CuraPlugins(Base):
    DEMO = os.path.join(DATA, "DemoCuraPlugin")

    def test_sources(self):
        info = install.read_plugin_source(self.DEMO)
        self.assertEqual((info["kind"], info["plugin_id"]), ("folder", "DemoCuraPlugin"))
        z = os.path.join(self.tmp, "DemoCuraPlugin-main.zip")              # what GitHub's "Download ZIP" looks like
        with zipfile.ZipFile(z, "w") as zf:
            for fn in ("plugin.json", "__init__.py"):
                zf.write(os.path.join(self.DEMO, fn), "DemoCuraPlugin-main/" + fn)
            zf.writestr("DemoCuraPlugin-main/README.md", "x")
        info = install.read_plugin_source(z)
        self.assertEqual((info["kind"], info["plugin_id"]), ("zip", "DemoCuraPlugin"))
        with self.assertRaises(install.InstallError):
            install.read_plugin_source(DATA)
        pkg = os.path.join(self.tmp, "x.curapackage")
        pi = install.build_curapackage(info, pkg)
        self.assertEqual(pi["package_id"], "DemoCuraPlugin")
        names = self.zipnames(pkg)
        self.assertIn("files/plugins/DemoCuraPlugin/plugin.json", names)
        self.assertIn("package.json", names)
        self.assertEqual(install.read_plugin_source(pkg)["kind"], "curapackage")

    def test_install_goes_through_curas_package_manager(self):
        inst = make_cura(self.home)
        res = install.install_cura_plugin(inst, self.DEMO)
        queued = os.path.join(inst.roots["cache"], "cura_packages", "DemoCuraPlugin.curapackage")
        self.assertTrue(os.path.isfile(queued))
        _p, pk = inventory.cura_packages(inst)
        entry = pk["to_install"]["DemoCuraPlugin"]
        self.assertEqual(entry["filename"], queued)
        self.assertEqual(entry["package_info"]["display_name"], "SlicerSwap Demo Plugin")
        self.assertIn("PkgPlugin", pk["installed"])                        # existing entries kept
        self.assertEqual(install.check_cura_plugin(inst, "DemoCuraPlugin")[0], "waiting")
        self.assertFalse(os.path.exists(os.path.join(inst.roots["data"], "plugins", "DemoCuraPlugin")))  # Cura does that

    def test_check_reads_curas_log(self):
        inst = make_cura(self.home)
        self.assertEqual(install.check_cura_plugin(inst, "LoosePlugin")[0], "loaded")
        st, why = install.check_cura_plugin(inst, "PkgPlugin")
        self.assertEqual(st, "failed")
        self.assertIn("boom", why)
        self.assertEqual(install.check_cura_plugin(inst, "Nope")[0], "missing")
        # a later Cura start that no longer loads it is a failure, not "still loaded"
        with open(inventory.cura_log_path(inst), "a") as fh:
            fh.write(LOG_START.format(t="11:00:00") + LOG_BOOTED.format(t="11:00:09"))
        os.utime(os.path.join(inst.roots["data"], "plugins", "LoosePlugin", "plugin.json"), (0, 1_700_000_000))
        self.assertEqual(install.check_cura_plugin(inst, "LoosePlugin")[0], "failed")

    def test_remove(self):
        inst = make_cura(self.home)
        install.remove_cura_plugin(inst, "PkgPlugin")
        self.assertIn("PkgPlugin", inventory.cura_packages(inst)[1]["to_remove"])    # Cura uninstalls it itself
        res = install.remove_cura_plugin(inst, "LoosePlugin")
        self.assertFalse(os.path.exists(os.path.join(inst.roots["data"], "plugins", "LoosePlugin")))
        self.assertTrue(os.path.isfile(os.path.join(res.files[0], "plugin.json")))   # moved aside, not deleted
        backed_up = [r for it in inventory.inventory(inst) for _root, r in it.files]
        self.assertFalse([r for r in backed_up if "removed-by-slicerswap" in r])     # ...and kept out of backups

    def test_script(self):
        inst = make_cura(self.home)
        src = os.path.join(self.tmp, "Other.py")
        w(src, "class Other(Script):\n    pass\n")
        install.install_cura_script(inst, src)
        self.assertTrue(os.path.isfile(os.path.join(inst.roots["config"], "scripts", "Other.py")))
        with self.assertRaises(install.InstallError):
            install.install_cura_script(make_prusa(self.home), src)


class DamagedPackageList(Base):
    """Cura's packages.json holds the record of every installed plug-in. When it cannot be read, writing a fresh
    one would wipe that record (the bug Forge-X and the Bambu plug-in had). SlicerSwap must leave it alone."""
    DEMO = os.path.join(DATA, "DemoCuraPlugin")
    BROKEN = {
        "truncated": b'{"installed": {"PkgPlugin": {"package_info": {"package_id": "PkgP',
        "not json": b"this is not json",
        "binary": b"\x00\xff\xfe\x00garbage",
        "a list": b'[1, 2, 3]',
        "wrong shape": b'{"installed": [], "to_install": {}}',
        "deep nesting": b"[" * 200000 + b"]" * 200000,
    }

    def _break(self, inst, data):
        pk_path = os.path.join(inst.roots["data"], "packages.json")
        with open(pk_path, "wb") as fh:
            fh.write(data)
        return pk_path

    def _bytes(self, path):
        with open(path, "rb") as fh:
            return fh.read()

    def test_install_refuses_and_changes_nothing(self):
        for label, data in self.BROKEN.items():
            with self.subTest(label):
                inst = make_cura(os.path.join(self.tmp, label.replace(" ", "_")))
                pk_path = self._break(inst, data)
                with self.assertRaises(install.InstallError) as cm:
                    install.install_cura_plugin(inst, self.DEMO)
                self.assertIn("Nothing was changed", str(cm.exception))
                self.assertIn("wipe", str(cm.exception))
                self.assertEqual(self._bytes(pk_path), data)
                self.assertFalse(os.path.exists(pk_path + ".bak"))
                self.assertFalse(os.path.exists(os.path.join(inst.roots["cache"], "cura_packages")))

    def test_good_list_keeps_a_readable_backup_and_the_hint_uses_it(self):
        inst = make_cura(self.home)
        pk_path = os.path.join(inst.roots["data"], "packages.json")
        good = self._bytes(pk_path)
        install.install_cura_plugin(inst, self.DEMO)
        self.assertEqual(self._bytes(pk_path + ".bak"), good)
        _p, pk = inventory.cura_packages(inst)
        self.assertIn("PkgPlugin", pk["installed"])           # other plug-ins kept
        self._break(inst, b"{oops")
        with self.assertRaises(install.InstallError) as cm:
            install.install_cura_plugin(inst, self.DEMO)
        self.assertIn("packages.json.bak", str(cm.exception))   # points at the good copy
        self.assertEqual(self._bytes(pk_path + ".bak"), good)    # the good copy is not overwritten with junk
        self.assertIn("WARNING", "WARNING: " + inventory.packages_problem(inst))

    def test_empty_file_and_byte_order_mark_are_fine(self):
        inst = make_cura(self.home)
        self._break(inst, b"")
        install.install_cura_plugin(inst, self.DEMO)
        self.assertIn("DemoCuraPlugin", inventory.cura_packages(inst)[1]["to_install"])
        inst2 = make_cura(os.path.join(self.tmp, "bom"))
        pk_path = os.path.join(inst2.roots["data"], "packages.json")
        self._break(inst2, b"\xef\xbb\xbf" + self._bytes(pk_path))
        install.install_cura_plugin(inst2, self.DEMO)
        self.assertIn("PkgPlugin", inventory.cura_packages(inst2)[1]["installed"])
        self.assertIsNone(inventory.packages_problem(inst2))

    def test_remove_still_works_but_leaves_the_list_alone(self):
        inst = make_cura(self.home)
        pk_path = self._break(inst, b"{broken")
        res = install.remove_cura_plugin(inst, "PkgPlugin")      # rescue: a plug-in that stops Cura must still go
        self.assertFalse(os.path.exists(os.path.join(inst.roots["data"], "plugins", "PkgPlugin")))
        self.assertEqual(self._bytes(pk_path), b"{broken")
        self.assertTrue(any("left as it is" in n for n in res.notes))

    def test_restore_puts_the_folders_back_but_leaves_the_list_alone(self):
        src = make_cura(self.home)
        out = os.path.join(self.tmp, "c.slicerpack")
        pack.create(src, inventory.inventory(src), out, redact_secrets=False)
        dst = make_cura(os.path.join(self.tmp, "home2"))
        shutil.rmtree(os.path.join(dst.roots["data"], "plugins", "PkgPlugin"))
        pk_path = self._break(dst, b'{"installed": {"Other')
        res = pack.restore(out, dst)
        self.assertTrue(res.verified)
        self.assertTrue(os.path.isfile(os.path.join(dst.roots["data"], "plugins", "PkgPlugin", "PkgPlugin", "plugin.json")))
        self.assertEqual(self._bytes(pk_path), b'{"installed": {"Other')
        self.assertTrue(any("folders only" in n for n in res.notes))

    def test_unreadable_list_is_reported_not_crashed_on(self):
        inst = make_cura(self.home)
        self._break(inst, b"\xff\xfe\x00")
        self.assertIn("not readable text", inventory.packages_problem(inst))
        names = {p["plugin_id"] for p, _st, _w in install.cura_plugin_report(inst)}
        self.assertEqual(names, {"LoosePlugin", "PkgPlugin"})


class EdgeCases(Base):
    """Found by the 0.2.2 edge-case sweep (tools/edge_sweep.py runs the full set)."""
    DEMO = os.path.join(DATA, "DemoCuraPlugin")

    def _pack(self):
        src = make_cura(self.home)
        out = os.path.join(self.tmp, "c.slicerpack")
        pack.create(src, inventory.inventory(src), out, redact_secrets=False)
        return out

    def test_a_second_undo_is_refused(self):
        out = self._pack()
        dst = make_cura(os.path.join(self.tmp, "d"))
        p = os.path.join(dst.roots["data"], "quality_changes", "creality_ender3_my_profile.inst.cfg")
        with open(p, "a") as fh:
            fh.write("# mine\n")
        pack.restore(out, dst)
        snap = pack.list_snapshots("cura")[0]
        pack.undo(snap, dst)
        with open(p, "a") as fh:
            fh.write("# edited after the undo\n")
        with self.assertRaises(pack.PackError):
            pack.undo(snap, dst)
        with open(p) as fh:
            self.assertIn("edited after the undo", fh.read())
        self.assertNotIn(snap, pack.list_snapshots("cura"))

    def test_newest_safety_copy_first_within_one_second(self):
        d = pack.snapshot_dir()
        os.makedirs(d)
        for n in ("cura-before-restore-20261117-120344.slicerpack", "cura-before-restore-20261117-120344-2.slicerpack",
                  "cura-before-restore-20261117-120344-10.slicerpack", "cura-before-restore-20261117-120343-9.slicerpack"):
            w(os.path.join(d, n), "")
        self.assertEqual([os.path.basename(x)[-14:] for x in pack.list_snapshots("cura")],
                         ["0344-10.slicerpack"[-14:], "20344-2.slicerpack"[-14:], "120344.slicerpack"[-14:], "20343-9.slicerpack"[-14:]])

    def test_damaged_backup_changes_nothing(self):
        out = self._pack()
        bad = os.path.join(self.tmp, "bad.slicerpack")
        with zipfile.ZipFile(out) as a, zipfile.ZipFile(bad, "w") as b:
            names = [n for n in a.namelist() if n.startswith("files/")]
            for n in a.namelist():
                b.writestr(n, b"tampered" if n == names[-1] else a.read(n))
        dst = slicers.Install("cura", "5.13", {k: os.path.join(self.tmp, "empty", k) for k in ("config", "data", "cache")})
        with self.assertRaises(pack.PackError) as cm:
            pack.restore(bad, dst)
        self.assertIn("Nothing was changed", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "empty")))

    def test_hostile_or_damaged_plugin_ids_are_refused(self):
        z = os.path.join(self.tmp, "e.curapackage")
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("package.json", json.dumps({"package_id": "../../evil", "package_type": "plugin"}))
            zf.writestr("files/plugins/evil/plugin.json", "{}")
        with self.assertRaises(install.InstallError):
            install.install_cura_plugin(make_cura(self.home), z)
        self.assertEqual([f for r, _d, fs in os.walk(self.tmp) for f in fs if f == "evil.curapackage"], [])
        z2 = os.path.join(self.tmp, "P.zip")
        with zipfile.ZipFile(z2, "w") as zf:
            zf.writestr("P/plugin.json", "{nope")
            zf.writestr("P/__init__.py", "")
        with self.assertRaises(install.InstallError):
            install.read_plugin_source(z2)
        with self.assertRaises(install.InstallError):
            install.remove_cura_plugin(make_cura(self.home), "../..")

    def test_folder_and_github_zip_give_the_same_id(self):
        d = os.path.join(self.tmp, "DemoCuraPlugin-main")
        shutil.copytree(self.DEMO, d)
        self.assertEqual(install.read_plugin_source(d)["plugin_id"], "DemoCuraPlugin")

    def test_empty_or_junk_profile_is_refused_not_converted_to_defaults(self):
        for name, data in (("e.ini", b""), ("j.ini", os.urandom(3000)), ("e.json", b""), ("l.json", b"[1]"),
                           ("e.curaprofile", b""), ("j.inst.cfg", b"\xff\xfe\x00junk")):
            with self.subTest(name):
                p = os.path.join(self.tmp, name)
                with open(p, "wb") as fh:
                    fh.write(data)
                out = os.path.join(self.tmp, "out-" + name)
                with self.assertRaises(ValueError) as cm:
                    from slicerswap.convert import convert
                    convert([p], Options(target="orca" if not name.endswith(".json") else "prusa", outdir=out))
                self.assertIn(name, str(cm.exception))
                self.assertFalse(os.path.exists(out))


class CuraPluginFaults(Base):
    """A tool-bar icon with fill on its <svg> tag takes Cura down while it starts (found with Hybrid Supports
    0.1.0-wip, reproduced in Cura 5.13.0). Cura has already logged "Loaded plugin" by then."""
    TOOL = os.path.join(DATA, "DemoToolPlugin")
    # the two icons of Hybrid Supports: 0.1.0-wip (crashed Cura) and the fixed one
    BAD_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" '
               b'stroke="#000" stroke-width="1.6" stroke-linejoin="round">\n  <path d="M3 4h18"/>\n</svg>\n')
    GOOD_SVG = (b'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">\n'
                b'  <rect x="3" y="3" width="18" height="2"/>\n</svg>\n')

    def faulty_copy(self, name="DemoToolPlugin"):
        """The demo tool plug-in with the fault put into its icon."""
        dst = os.path.join(self.tmp, "faulty", name)
        shutil.copytree(self.TOOL, dst)
        icon = os.path.join(dst, "demo_tool.svg")
        with open(icon, "rb") as fh:
            data = fh.read()
        with open(icon, "wb") as fh:
            fh.write(data.replace(b"<svg ", b'<svg fill="none" stroke="#000" ', 1))
        return dst

    def put_in_cura(self, inst, src, packaged=True):
        """As if it had been installed before anyone checked: files in place, on Cura's package list."""
        pid = os.path.basename(src)
        dst = os.path.join(inst.roots["data"], "plugins", pid, pid) if packaged else os.path.join(inst.roots["data"], "plugins", pid)
        shutil.copytree(src, dst)
        if packaged:
            path, pk = inventory.cura_packages(inst)
            pk["installed"][pid] = {"package_info": {"package_id": pid, "package_version": "1.0.0"}, "filename": ""}
            w(path, json.dumps(pk))
        return dst

    def test_the_fault_itself(self):
        self.assertTrue(plugcheck.svg_breaks_recolouring(self.BAD_SVG))
        self.assertFalse(plugcheck.svg_breaks_recolouring(self.GOOD_SVG))
        with open(os.path.join(self.TOOL, "demo_tool.svg"), "rb") as fh:
            self.assertFalse(plugcheck.svg_breaks_recolouring(fh.read()))
        # Cura only touches "<svg " followed by a space; a line break there means no recolouring and no crash
        self.assertFalse(plugcheck.svg_breaks_recolouring(b'<svg\nfill="none" xmlns="http://www.w3.org/2000/svg"/>'))
        self.assertFalse(plugcheck.svg_breaks_recolouring(b"not an svg at all <svg "))
        self.assertTrue(plugcheck.svg_breaks_recolouring(b'<?xml version="1.0"?>\n<svg  fill="#000" xmlns="http://www.w3.org/2000/svg"/>'))

    def test_only_recoloured_icons_count(self):
        init = b'def getMetaData():\n    return {"tool": {"name": "T", "icon": "tool_icon.svg"}}\n'
        self.assertEqual([f.where for f in plugcheck.icon_faults({"__init__.py": init, "tool_icon.svg": self.BAD_SVG})], ["toolbar"])
        self.assertEqual(plugcheck.icon_faults({"__init__.py": init, "tool_icon.svg": self.GOOD_SVG}), [])
        # the same kind of file used as an ordinary picture is harmless: plenty of working plug-ins have one
        self.assertEqual(plugcheck.icon_faults({"__init__.py": init, "tool_icon.svg": self.GOOD_SVG, "images/logo.svg": self.BAD_SVG}), [])
        # ...unless a panel hands it to Cura's recolouring item
        qml = b'import UM 1.5 as UM\nUM.ColorImage { source: "images/logo.svg" }\n'
        faults = plugcheck.icon_faults({"__init__.py": init, "Panel.qml": qml, "images/logo.svg": self.BAD_SVG})
        self.assertEqual([(f.where, f.path) for f in faults], [("panel", "images/logo.svg")])
        self.assertEqual(plugcheck.stops_cura(faults), [])
        self.assertIn("remove fill", plugcheck.explain("T", plugcheck.icon_faults({"__init__.py": init, "tool_icon.svg": self.BAD_SVG})))

    def test_install_refuses_a_plugin_that_stops_cura(self):
        inst = make_cura(self.home)
        before = open(inventory.cura_packages(inst)[0]).read()
        bad = self.faulty_copy()
        z = os.path.join(self.tmp, "DemoToolPlugin-main.zip")
        with zipfile.ZipFile(z, "w") as zf:
            for fn in os.listdir(bad):
                zf.write(os.path.join(bad, fn), "DemoToolPlugin-main/" + fn)
        pkg = os.path.join(self.tmp, "bad.curapackage")
        install.build_curapackage(install.read_plugin_source(bad), pkg)
        for source in (bad, z, pkg):
            with self.assertRaises(install.InstallError) as ctx:
                install.install_cura_plugin(inst, source)
            self.assertIn("stop Cura from starting", str(ctx.exception))
            self.assertIn("demo_tool.svg", str(ctx.exception))
        self.assertEqual(open(inventory.cura_packages(inst)[0]).read(), before)          # nothing was queued
        self.assertFalse(os.path.exists(os.path.join(inst.roots["cache"], "cura_packages", "DemoToolPlugin.curapackage")))
        # the sound plug-in goes through, and the fixed Hybrid Supports icon would too
        res = install.install_cura_plugin(inst, self.TOOL)
        self.assertTrue(res.verified)
        self.assertEqual(install.check_cura_plugin(inst, "DemoToolPlugin")[0], "waiting")

    def test_package_list_is_copied_before_it_is_changed(self):
        inst = make_cura(self.home)
        path = inventory.cura_packages(inst)[0]
        before = open(path).read()
        install.install_cura_plugin(inst, self.TOOL)
        self.assertEqual(open(path + ".bak").read(), before)
        middle = open(path).read()
        install.remove_cura_plugin(inst, "PkgPlugin")
        self.assertEqual(open(path + ".bak").read(), middle)
        self.assertNotIn("packages.json.bak", [r for it in inventory.inventory(inst) for _root, r in it.files])   # not backed up

    def test_installed_faulty_plugin_is_red_even_though_curas_log_says_loaded(self):
        inst = make_cura(self.home)
        self.put_in_cura(inst, self.faulty_copy())
        shutil.copy(os.path.join(DATA, "cura_log_crashed_start.txt"), inventory.cura_log_path(inst))
        with open(inventory.cura_log_path(inst), "a") as fh:
            fh.write("2026-10-07 09:17:06,340 - INFO - [MainThread] UM.PluginRegistry.loadPlugin [540]: Loaded plugin DemoToolPlugin 1.0.0\n")
        st, why = install.check_cura_plugin(inst, "DemoToolPlugin", running=False)
        self.assertEqual(st, "failed")
        self.assertIn("STOPS CURA FROM STARTING", why)
        self.assertIn("Remove selected", why)
        # and it can be taken out while Cura cannot start: Cura removes packages before it loads plug-ins
        install.remove_cura_plugin(inst, "DemoToolPlugin")
        self.assertIn("DemoToolPlugin", inventory.cura_packages(inst)[1]["to_remove"])

    def test_loaded_is_only_green_when_cura_finished_starting(self):
        inst = make_cura(self.home)
        hs = os.path.join(inst.roots["data"], "plugins", "HybridSupports", "HybridSupports")
        w(os.path.join(hs, "plugin.json"), '{"name": "Hybrid Supports", "version": "0.1.2", "api": 8}')
        w(os.path.join(hs, "__init__.py"), 'def getMetaData():\n    return {"tool": {"icon": "tool_icon.svg"}}\n')
        with open(os.path.join(hs, "tool_icon.svg"), "wb") as fh:
            fh.write(self.GOOD_SVG)
        log = inventory.cura_log_path(inst)
        # 1. the log of a real Cura 5.13 start that went through
        shutil.copy(os.path.join(DATA, "cura_log_good_start.txt"), log)
        st, why = install.check_cura_plugin(inst, "HybridSupports", running=False)
        self.assertEqual(st, "loaded", why)
        # 2. the log of a real Cura 5.13 start that died 4 seconds after "Loaded plugin HybridSupports"
        shutil.copy(os.path.join(DATA, "cura_log_crashed_start.txt"), log)
        st, why = install.check_cura_plugin(inst, "HybridSupports", running=False)
        self.assertEqual(st, "unsure", why)
        self.assertIn("NOT CONFIRMED", why)
        self.assertEqual(install.check_cura_plugin(inst, "HybridSupports", running=True)[0], "waiting")   # still starting
        # 3. ...and Cura's own crash record names the reason
        w(os.path.join(os.path.dirname(inst.roots["data"]), "stderr.log"), "x\nFatal Python error: Segmentation fault\n\nThread 0x1:\n")
        st, why = install.check_cura_plugin(inst, "HybridSupports", running=False)
        self.assertEqual(st, "unsure")
        self.assertIn("Segmentation fault", why)
        # 4. a different version loaded than the one installed: restart needed, not "loaded"
        shutil.copy(os.path.join(DATA, "cura_log_good_start.txt"), log)
        w(os.path.join(hs, "plugin.json"), '{"name": "Hybrid Supports", "version": "0.1.3", "api": 8}')
        st, why = install.check_cura_plugin(inst, "HybridSupports", running=False)
        self.assertEqual(st, "waiting")
        self.assertIn("0.1.2", why)

    def test_curas_reasons_for_not_loading_are_passed_on(self):
        inst = make_cura(self.home)
        log = inventory.cura_log_path(inst)
        pre = "2026-10-06 12:00:01,000 - {lvl} - [MainThread] UM.PluginRegistry.{fn}: "
        cases = [
            ("INFO", "loadPlugin [494]", "Plugin [LoosePlugin] has been disabled. Skip loading it.", "Switched off"),
            ("WARNING", "loadPlugin [506]", "Plugin [LoosePlugin] with supported sdk versions [['7.0.0']] is incompatible "
             "with the current sdk version [8.12.0].", "different Cura version"),
            ("WARNING", "loadPlugin [514]", "Plugin LoosePlugin did not return any objects to register", "did not return any objects"),
        ]
        for lvl, fn, msg, expect in cases:
            w(log, LOG_START.format(t="12:00:00") + pre.format(lvl=lvl, fn=fn) + msg + "\n" + LOG_BOOTED.format(t="12:00:09"))
            st, why = install.check_cura_plugin(inst, "LoosePlugin", running=False)
            self.assertEqual(st, "failed", msg)
            self.assertIn(expect, why)
        # an exception, as real Cura 5.13 logs it: the traceback line by line with the same stamp (the last line is
        # the useful one), then a second, vaguer error for the same plug-in that must not hide the first
        a = "2026-10-06 12:00:01,000 - ERROR - [MainThread] UM.PluginRegistry._findPlugin [795]: "
        b = "2026-10-06 12:00:01,000 - ERROR - [MainThread] UM.PluginRegistry.removeCorruptedPluginMessage [577]: "
        w(log, LOG_START.format(t="12:00:00") + a + "Exception: Import error loading module LoosePlugin\n" +
          a + "Traceback (most recent call last):\n" + a + '  File "/x/plugins/LoosePlugin/__init__.py", line 18, in <module>\n' +
          a + "    import numpy_stl\n" + a + "ModuleNotFoundError: No module named 'numpy_stl'\n" +
          "2026-10-06 12:00:01,000 - WARNING - [MainThread] UM.PluginRegistry._populateMetaData [892]: Could not find plugin LoosePlugin\n" +
          b + "Exception: Error loading plugin LoosePlugin:\n" + b + "NoneType: None\n" + LOG_BOOTED.format(t="12:00:09"))
        st, why = install.check_cura_plugin(inst, "LoosePlugin", running=False)
        self.assertEqual(st, "failed")
        self.assertIn("Import error loading module LoosePlugin ... ModuleNotFoundError: No module named 'numpy_stl'", why)
        # switched off in Cura's own settings file, whatever the log says
        w(os.path.join(inst.roots["config"], "plugins.json"), '{"disabled": ["PkgPlugin"], "to_install": {}, "to_remove": []}')
        self.assertIn("Switched off", install.check_cura_plugin(inst, "PkgPlugin", running=False)[1])

    def test_backup_warns_and_restore_leaves_it_out(self):
        inst = make_cura(self.home)
        self.put_in_cura(inst, self.faulty_copy())
        self.put_in_cura(inst, os.path.join(DATA, "DemoCuraPlugin"))
        out = os.path.join(self.tmp, "with-faulty.slicerpack")
        m = pack.create(inst, inventory.inventory(inst), out)
        self.assertEqual(len(m["warnings"]), 1)
        self.assertIn("SlicerSwap Demo Tool", m["warnings"][0])
        self.assertEqual(list(pack.faulty_plugins(out)), ["plugin:SlicerSwap Demo Tool"])
        # restore into an empty Cura
        new = slicers.Install("cura", "5.13", {k: os.path.join(self.tmp, "new", k) for k in ("config", "data", "cache")})
        _m, actions = pack.plan(out, new)
        self.assertEqual({a.item for a in actions if a.status == "unsafe"}, {"plugin:SlicerSwap Demo Tool"})
        res = pack.restore(out, new, None, allow_running=True, make_snapshot=False)
        self.assertTrue(res.verified)
        self.assertEqual(res.skipped, 1)
        self.assertTrue(any("NOT restored" in n and "demo_tool.svg" in n for n in res.notes))
        self.assertFalse(os.path.exists(os.path.join(new.roots["data"], "plugins", "DemoToolPlugin")))
        self.assertTrue(os.path.isfile(os.path.join(new.roots["data"], "plugins", "DemoCuraPlugin", "DemoCuraPlugin", "plugin.json")))
        listed = inventory.cura_packages(new)[1]["installed"]
        self.assertIn("DemoCuraPlugin", listed)
        self.assertNotIn("DemoToolPlugin", listed)                # not on Cura's list either

    def test_finding_and_starting_cura(self):
        home = os.path.join(self.tmp, "h")
        for rel in ("Downloads/UltiMaker-Cura-5.11.0-linux-X64.AppImage", "Applications/UltiMaker-Cura-5.13.0-linux-X64.AppImage",
                    "UltiMaker-Cura-5.8.1-linux-X64.AppImage"):
            w(os.path.join(home, rel), "x")
        if sys.platform.startswith("linux"):
            names = [label for label, _cmd in slicers.find_cura_programs(home=home)]
            self.assertEqual([n.split("-")[2] for n in names[:3]], ["5.13.0", "5.11.0", "5.8.1"])          # newest first
            self.assertIn("5.11.0", slicers.find_cura_programs("5.11", home=home)[0][0])                # the settings folder's own
            with self.assertRaises(OSError) as ctx:
                slicers.launch([os.path.join(home, "UltiMaker-Cura-5.8.1-linux-X64.AppImage")])
            self.assertIn("Allow executing file as program", str(ctx.exception))


class FoundByRealSlicers(unittest.TestCase):
    """Regressions for bugs that only showed up when the output was loaded in the real programs."""

    def test_prusa_overlap_percent_and_prime_speed(self):
        _s, C, _r = read_canonical([os.path.join(DATA, "prusa_simple.ini")], Options(target="cura"))
        self.assertAlmostEqual(C["infill_overlap"], 10.0)        # was written to Cura as 0.045
        self.assertAlmostEqual(C["deretract_speed"], 35.0)       # 0 means "same as retract speed"

    def test_settings_newer_than_the_installed_prusaslicer_are_reported(self):
        from slicerswap import slicer_fmt
        native = {"print": {"first_layer_infill_speed": 20, "layer_height": 0.2}, "filament": {"chamber_temperature": 40}}
        self.assertEqual([k for k, _v in slicer_fmt.too_new_for("prusa", native, "2.7.2")],
                         ["chamber_temperature", "first_layer_infill_speed"])       # real 2.7.2 ignored both
        self.assertEqual([k for k, _v in slicer_fmt.too_new_for("prusa", native, "2.8.1+linux")], ["first_layer_infill_speed"])
        self.assertEqual(slicer_fmt.too_new_for("prusa", native, "2.9.6"), [])
        self.assertEqual(len(slicer_fmt.too_new_for("prusa", native)), 2)             # version unknown: say so anyway
        self.assertEqual(slicer_fmt.too_new_for("orca", native, "2.0"), [])
        _s, C, _r = read_canonical([os.path.join(DATA, "orca_process.json"), os.path.join(DATA, "orca_filament.json"),
                                    os.path.join(DATA, "orca_machine.json")], Options(target="prusa"))
        rep = mapping.Report()
        slicer_fmt.from_canon("prusa", C, rep, "orca", target_version="2.7.2")
        self.assertTrue(any("2.7.2 is older" in n and "first_layer_infill_speed" in n for n in rep.notes))

    def test_the_real_cura_fixture_backup_is_intact(self):
        # tools/host_tests/check_cura.py restores this pack (made by real Cura 5.13) into a throwaway Cura
        fixture = os.path.join(DATA, "cura_ender3_printer.slicerpack")
        self.assertEqual(pack.verify(fixture), [])
        m = pack.read_manifest(fixture)
        self.assertEqual(sorted(i["kind"] for i in m["items"]), ["printer", "settings"])
        self.assertTrue(m["redacted"])

    def test_cura_profile_only_drops_values_derived_from_itself(self):
        res = ce.Resources()
        vals = {"line_width": 0.4, "wall_line_width": 0.4, "wall_line_width_0": 0.4, "material_bed_temperature": 60.0,
                "speed_print": 50.0, "infill_sparse_density": 20.0}
        kept = ce.minimal_changes(res, "creality_ender3", "standard", vals)
        self.assertIn("material_bed_temperature", kept)          # the material profile says 50 for this printer
        self.assertIn("speed_print", kept)
        self.assertIn("infill_sparse_density", kept)
        self.assertNotIn("wall_line_width", kept)                # = line_width, which is written
        self.assertIn("line_width", kept)
        full = ce.resolve_profile(ce.CuraProfile(machine="creality_ender3", quality_type="standard",
                                                 global_changes={k: str(v) for k, v in kept.items()}), res)
        for k, v in vals.items():                                # nothing changed by leaving values out
            self.assertAlmostEqual(float(full.values[k]), float(v), msg=k)

    def test_material_values_follow_the_printer(self):
        res = ce.Resources()
        rc = ce.resolve_profile(ce.CuraProfile(machine="creality_ender3", quality_type="standard"), res)
        self.assertAlmostEqual(rc.values["material_bed_temperature"], 50)      # Creality override in generic PLA
        rc = ce.resolve_profile(ce.CuraProfile(machine="prusa_i3_mk3", quality_type="normal"), res)
        self.assertAlmostEqual(rc.values["material_bed_temperature"], 60)

    def test_unknown_placeholders_are_replaced_by_values(self):
        out, notes = gcode.translate("G1 Y{machine_depth} ;{nonsense}", "cura", "orca", {"machine_depth": 235.0})
        self.assertEqual(out, "G1 Y{print_bed_size[1]} ;{nonsense}")
        out, notes = gcode.translate("M117 {material_brand}", "cura", "prusa", {"material_brand": "Generic"})
        self.assertEqual(out, "M117 Generic")
        self.assertTrue(notes)

    def test_keys_sit_in_the_preset_the_slicer_expects(self):
        p, o = gcode.native_types("prusa"), gcode.native_types("orca")
        wrong = []
        for canon, sec, _k, _c, pk, ok, _d in mapping.ROWS:
            for name, table, key in (("prusa", p, pk), ("orca", o, ok)):
                if key and table.get(key, {}).get("sec") not in (None, sec):
                    wrong.append((name, key, sec, table[key]["sec"]))
        self.assertEqual(wrong, [])


class Launchers(unittest.TestCase):
    def test_present_and_executable(self):
        for fn in ("SlicerSwap-Linux.sh", "SlicerSwap-Mac.command", "SlicerSwap-Windows.bat"):
            p = os.path.join(ROOT, fn)
            self.assertTrue(os.path.isfile(p), fn)
            if not fn.endswith(".bat") and os.name != "nt":
                self.assertTrue(os.stat(p).st_mode & stat.S_IXUSR, fn + " must be executable")
        with open(os.path.join(ROOT, "SlicerSwap-Windows.bat"), "rb") as fh:
            self.assertIn(b"\r\n", fh.read())


if __name__ == "__main__":
    unittest.main()
