# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Run with:  python -m unittest discover -s tests"""
import configparser
import json
import os
import sys
import tempfile
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from slicerswap import cura_engine as ce  # noqa: E402
from slicerswap import gcode, mapping, slicer_fmt  # noqa: E402
from slicerswap.convert import Options, convert, detect, read_canonical  # noqa: E402

DATA = os.path.join(HERE, "data")
RES = ce.Resources()


def d(name):
    return os.path.join(DATA, name)


ORCA = [d("orca_process.json"), d("orca_filament.json"), d("orca_machine.json")]


class KeyValidity(unittest.TestCase):
    """Every native key in the mapping must exist in that slicer's own option list."""

    def test_rows_exist(self):
        cura = RES.setting_definitions("fdmprinter")
        prusa, orca = gcode.native_types("prusa"), gcode.native_types("orca")
        missing = []
        for row in mapping.ROWS:
            canon, _s, _k, ck, pk, ok, _d = row
            if ck and ck not in cura:
                missing.append(f"cura:{ck}")
            if pk and pk not in prusa:
                missing.append(f"prusa:{pk}")
            if ok and ok not in orca:
                missing.append(f"orca:{ok}")
        self.assertEqual(missing, [])

    def test_enum_values_exist(self):
        cura = RES.setting_definitions("fdmprinter")
        orca = gcode.native_types("orca")
        checks = [(mapping.INFILL, "infill_pattern", "sparse_infill_pattern"),
                  (mapping.SUPPORT_PATTERN, "support_pattern", "support_base_pattern"),
                  (mapping.SEAM, "z_seam_type", "seam_position")]
        bad = []
        for table, ck, ok in checks:
            copts = set(cura[ck]["options"])
            oopts = set(orca[ok]["enum"] or [])
            for canon, nats in table.items():
                c, o = nats[0].rstrip("*"), nats[2].rstrip("*")
                if "+" not in c and c not in copts:
                    bad.append(f"cura {ck}={c}")
                if oopts and o not in oopts:
                    bad.append(f"orca {ok}={o}")
        flav = set(cura["machine_gcode_flavor"]["options"])
        for canon, (c, _po) in mapping.FLAVOR.items():
            if c.rstrip("*") not in flav:
                bad.append(f"cura flavor {c}")
        self.assertEqual(bad, [])


class CuraEngine(unittest.TestCase):
    def test_formulas_all_evaluate(self):
        for machine in ("fdmprinter", "creality_ender3", "prusa_i3_mk3", "ultimaker_s5"):
            prof = ce.CuraProfile(machine=machine)
            rc = ce.resolve_profile(prof, RES)
            self.assertEqual(rc.resolver.errors, {}, machine)

    def test_formula_follows_override(self):
        prof = ce.CuraProfile(machine="creality_ender3", quality_type="standard",
                              global_changes={"layer_height": "0.1", "top_thickness": "0.8"})
        rc = ce.resolve_profile(prof, RES)
        self.assertEqual(rc.values["top_layers"], 8)  # ceil(0.8 / 0.1)

    def test_machine_overrides_and_quality(self):
        rc = ce.resolve_profile(ce.CuraProfile(machine="creality_ender3", quality_type="standard"), RES)
        self.assertAlmostEqual(rc.values["machine_width"], 235)
        self.assertAlmostEqual(rc.values["layer_height"], 0.2)
        self.assertAlmostEqual(rc.values["material_diameter"], 1.75)

    def test_unsafe_expression_rejected(self):
        with self.assertRaises(ce.CuraError):
            ce._check_expr("().__class__")

    def test_curaprofile_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            qt, _ = ce.choose_quality(RES, "creality_ender3", 0.2)
            data = ce.build_curaprofile("T", {"infill_sparse_density": 33, "support_enable": True}, RES,
                                        "creality_ender3", qt)
            p = os.path.join(tmp, "t.curaprofile")
            with open(p, "wb") as fh:
                fh.write(data)
            prof = ce.read_cura_file(p)
            self.assertEqual(prof.global_changes["infill_sparse_density"], "33")
            self.assertEqual(prof.machine, "creality_base")
            self.assertEqual(prof.quality_type, "standard")

    def test_3mf_project(self):
        """A Cura-style 3MF: stacks reference containers stored next to them."""
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "proj.3mf")
            gstack = ("[general]\nversion = 4\nname = Ender\nid = Ender\n\n[metadata]\ntype = machine\n\n"
                      "[containers]\n0 = Ender_user\n1 = my_qc\n2 = empty_intent\n3 = creality_base_global_standard\n"
                      "4 = empty_material\n5 = empty_variant\n6 = Ender_settings\n7 = creality_ender3\n")
            estack = ("[general]\nversion = 4\nname = Extruder 1\nid = e1\n\n[metadata]\ntype = extruder_train\nposition = 0\n\n"
                      "[containers]\n0 = e1_user\n1 = my_qc_e\n2 = empty_intent\n3 = q\n4 = generic_petg_175\n"
                      "5 = creality_base_0.4\n6 = e1_settings\n7 = creality_base_extruder_0\n")
            qc = ("[general]\nversion = 4\nname = Mine\ndefinition = creality_base\n\n[metadata]\ntype = quality_changes\n"
                  "quality_type = standard\n\n[values]\ninfill_sparse_density = 42\n")
            qce = ("[general]\nversion = 4\nname = Mine\ndefinition = creality_base\n\n[metadata]\ntype = quality_changes\n"
                   "quality_type = standard\nposition = 0\n\n[values]\nmaterial_print_temperature = 241\n")
            dc = ("[general]\nversion = 4\nname = s\ndefinition = creality_ender3\n\n[metadata]\ntype = definition_changes\n\n"
                  "[values]\nmachine_width = 250\n")
            with zipfile.ZipFile(p, "w") as zf:
                zf.writestr("Cura/Ender.global.cfg", gstack)
                zf.writestr("Cura/e1.extruder.cfg", estack)
                zf.writestr("Cura/my_qc.inst.cfg", qc)
                zf.writestr("Cura/my_qc_e.inst.cfg", qce)
                zf.writestr("Cura/Ender_settings.inst.cfg", dc)
                zf.writestr("3D/3dmodel.model", "<model/>")
            self.assertEqual(detect([p]), "cura")
            src, C, rep = read_canonical([p], Options(target="orca"))
            self.assertEqual(C["infill_density"], 42)
            self.assertEqual(C["nozzle_temp"], 241)
            self.assertEqual(C["bed_x"], 250)
            self.assertEqual(C["bed_temp"], 70)  # generic PETG 1.75 from Cura's material file
            self.assertEqual(C["filament_type"], "PETG")


class Readers(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(detect([d("cura_fast_petg.inst.cfg")]), "cura")
        self.assertEqual(detect([d("prusa_simple.ini")]), "prusa")
        self.assertEqual(detect(ORCA), "orca")

    def test_prusa_percentages_and_auto(self):
        _, C, rep = read_canonical([d("prusa_simple.ini")], Options(target="orca"))
        self.assertAlmostEqual(C["speed_outer_wall"], 22.5)        # 50% of 45
        self.assertAlmostEqual(C["speed_solid_infill"], 60)        # 75% of 80
        self.assertAlmostEqual(C["inner_wall_line_width"], 0.45)   # 0 = default extrusion_width
        self.assertAlmostEqual(C["accel_inner_wall"], 1000)        # 0 = default acceleration
        self.assertAlmostEqual(C["support_xy"], 0.252)             # 60% of 0.42
        self.assertEqual(C["top_layers"], 5)
        self.assertEqual(C["support_overhang_angle"], 50)
        self.assertEqual(C["support_style"], "tree")
        self.assertEqual(C["support_interface_bottom_layers"], 2)  # -1 = same as top
        self.assertEqual(C["seam"], "back")
        self.assertEqual(C["adhesion_type"], "skirt")
        self.assertEqual(C["retract_length"], 0.8)                 # filament override 'nil' ignored

    def test_orca_reader(self):
        _, C, rep = read_canonical(ORCA, Options(target="prusa"))
        self.assertEqual(C["bed_x"], 220)
        self.assertTrue(C["bed_origin_center"])
        self.assertAlmostEqual(C["first_layer_line_width"], 0.48)  # 120% of 0.4 nozzle
        self.assertAlmostEqual(C["speed_first_layer_travel"], 150)  # 50% of travel
        self.assertAlmostEqual(C["accel_infill"], 5000)            # 100% of default
        self.assertAlmostEqual(C["accel_solid_infill"], 5000)      # 0 -> default
        self.assertEqual(C["infill_pattern"], "crosshatch")
        self.assertEqual(C["retract_length"], 1.2)                 # filament override wins
        self.assertEqual(C["bed_temp"], 75)                        # textured plate chosen
        self.assertEqual(C["adhesion_type"], "brim")


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def canon_of(path_list, target="orca"):
    return read_canonical(path_list, Options(target=target))[1]


class RoundTrips(unittest.TestCase):
    KEYS = ["layer_height", "first_layer_height", "wall_loops", "top_layers", "bottom_layers", "infill_density",
            "infill_pattern", "speed_outer_wall", "speed_inner_wall", "speed_infill", "speed_travel",
            "nozzle_temp", "nozzle_temp_first_layer", "bed_temp", "retract_length", "retract_speed", "zhop",
            "support_enabled", "support_style", "adhesion_type", "seam", "flow_ratio", "fan_max",
            "accel_default", "accel_outer_wall", "line_width", "outer_wall_line_width", "bed_x", "bed_y",
            "max_height", "elephant_foot", "skirt_loops", "brim_width", "support_overhang_angle"]

    def _trip(self, inputs, mid, src_fmt):
        with tempfile.TemporaryDirectory() as tmp:
            a = canon_of(inputs)
            rep = convert(inputs, Options(target=mid, outdir=os.path.join(tmp, "a"), name="trip",
                                          cura_machine="creality_ender3"))
            files = [f for f in rep.files if not f.endswith((".report.txt", ".txt"))]
            if mid == "prusa":
                files = [f for f in files if f.endswith("prusa_config.ini")]
            back = convert(files, Options(target=src_fmt, outdir=os.path.join(tmp, "b"), name="back",
                                          cura_machine="creality_ender3"))
            b = canon_of([f for f in back.files if not f.endswith((".report.txt", ".txt")) and
                          not f.endswith("prusa_bundle.ini")])
        diffs = {}
        for k in self.KEYS:
            if k in a and k in b:
                va, vb = a[k], b[k]
                if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and not isinstance(va, bool):
                    if abs(float(va) - float(vb)) > 1e-3:
                        diffs[k] = (va, vb)
                elif va != vb:
                    diffs[k] = (va, vb)
        return diffs

    def test_prusa_orca_prusa(self):
        self.assertEqual(self._trip([d("prusa_simple.ini")], "orca", "prusa"), {})

    def test_orca_prusa_orca(self):
        self.assertEqual(self._trip(ORCA, "prusa", "orca"), {"infill_pattern": ("crosshatch", "grid")})

    def test_cura_orca_cura(self):
        self.assertEqual(self._trip([d("cura_fast_petg.inst.cfg")], "orca", "cura"), {})

    def test_prusa_cura_prusa(self):
        diffs = self._trip([d("prusa_simple.ini")], "cura", "prusa")
        # Cura has no per-printer limits/bed data in profiles: those come from the Cura machine instead
        for k in ("bed_x", "bed_y", "max_height"):
            diffs.pop(k, None)
        self.assertEqual(diffs, {})


class Writers(unittest.TestCase):
    def test_orca_json_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = convert([d("prusa_simple.ini")], Options(target="orca", outdir=tmp, name="X"))
            proc, fil, mach = (_load([f for f in rep.files if f.endswith(f"orca_{t}.json")][0])
                               for t in ("process", "filament", "machine"))
            self.assertEqual(proc["type"], "process")
            self.assertEqual(proc["sparse_infill_density"], "20%")
            self.assertEqual(proc["outer_wall_speed"], ["22.5"])
            self.assertEqual(fil["nozzle_temperature"], ["215"])
            self.assertEqual(fil["filament_settings_id"], ["X"])
            self.assertEqual(mach["printable_area"], ["0x0", "220x0", "220x220", "0x220"])
            self.assertIn("{first_layer_temperature[0]}".replace("first_layer_temperature", "nozzle_temperature_initial_layer"),
                          mach["machine_start_gcode"])
            self.assertIn("printable_height", mach["machine_end_gcode"])
            self.assertEqual(mach["layer_change_gcode"], ";LAYER:[layer_num]")

    def test_prusa_bundle_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = convert(ORCA, Options(target="prusa", outdir=tmp, name="Y"))
            bundle = [f for f in rep.files if f.endswith("prusa_bundle.ini")][0]
            cp = configparser.ConfigParser(interpolation=None)
            cp.read(bundle)
            self.assertIn("print:Y", cp.sections())
            self.assertEqual(cp["presets"]["printer"], "Y")
            self.assertEqual(cp["printer:Y"]["bed_shape"], "-110x-110,110x-110,110x110,-110x110")
            self.assertIn("\\n", cp["printer:Y"]["start_gcode"] + "\\n")

    def test_cura_output_minimal_and_importable(self):
        with tempfile.TemporaryDirectory() as tmp:
            rep = convert(ORCA, Options(target="cura", outdir=tmp, name="Z", cura_machine="creality_ender3"))
            prof = [f for f in rep.files if f.endswith(".curaprofile")][0]
            with zipfile.ZipFile(prof) as zf:
                names = zf.namelist()
                self.assertEqual(len(names), 1)
                ic = ce.read_inst_cfg_text(zf.read(names[0]).decode())
            self.assertEqual(ic.metadata["type"], "quality_changes")
            self.assertIn(ic.metadata["quality_type"], RES.quality_types("creality_ender3"))
            self.assertEqual(ic.general["definition"], "creality_base")
            defs = RES.setting_definitions("creality_ender3")
            for k in ic.values:
                self.assertIn(k, defs)
                self.assertNotEqual(defs[k].get("category"), "machine_settings", k)
            self.assertEqual(ic.values["infill_pattern"], "grid")  # crosshatch approximated
            self.assertTrue(any("crosshatch" in a for a in rep.approximations))


class GcodeTranslation(unittest.TestCase):
    def test_prusa_to_orca_expressions(self):
        out, notes = gcode.translate("{if layer_z < max_print_height}G1{endif} [first_layer_bed_temperature]", "prusa", "orca")
        self.assertIn("printable_height", out)
        self.assertIn("[bed_temperature_initial_layer_single]", out)

    def test_cura_to_prusa(self):
        out, _ = gcode.translate("M104 S{material_print_temperature_layer_0}", "cura", "prusa")
        self.assertEqual(out, "M104 S{first_layer_temperature[initial_extruder]}")

    def test_logic_left_for_cura(self):
        out, notes = gcode.translate("{if x}G1{endif}", "prusa", "cura")
        self.assertEqual(out, "{if x}G1{endif}")
        self.assertTrue(notes)


if __name__ == "__main__":
    unittest.main()
