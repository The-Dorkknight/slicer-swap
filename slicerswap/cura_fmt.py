# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Cura <-> canonical."""
from __future__ import annotations

import math
import os
from typing import Any, Dict, List, Optional, Tuple

from . import cura_engine as ce
from . import gcode
from .mapping import (FLAVOR, CURA_FLAVOR_TO_CANON, INFILL, INFILL_ALIASES, ROWS, SEAM, SEAM_ALIASES,
                      SUPPORT_PATTERN, Report, enum_to_canon, enum_to_native)

# Parent settings whose effect we capture through their children.
CURA_COVERED = {
    "wall_thickness", "top_bottom_thickness", "top_thickness", "bottom_thickness", "speed_print", "speed_wall",
    "speed_layer_0", "speed_support", "speed_support_roof", "speed_support_bottom", "acceleration_wall",
    "acceleration_support", "jerk_wall", "jerk_support", "support_interface_height", "retraction_speed",
    "infill_line_distance", "support_infill_rate", "cool_fan_speed", "cool_fan_full_at_height", "wall_line_width",
    "skin_line_width", "roofing_line_width", "initial_layer_line_width_factor", "support_roof_enable",
    "support_bottom_enable", "support_roof_height", "support_bottom_height", "support_line_distance",
    "support_z_distance", "top_skin_preshrink", "raft_surface_layers", "raft_interface_layers",
    "material_bed_temperature", "material_print_temperature", "material_print_temperature_layer_0",
    "material_bed_temperature_layer_0", "retraction_enable", "machine_center_is_zero",
}


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def read(path: str, res: ce.Resources, machine: Optional[str] = None,
         material: Optional[str] = None) -> Tuple[Dict[str, Any], Report, ce.ResolvedCura]:
    prof = ce.read_cura_file(path)
    rc = ce.resolve_profile(prof, res, machine=machine, material=material)
    rep = Report(source="Cura")
    for n in rc.notes:
        rep.note(n)
    v = rc.values
    C: Dict[str, Any] = {"name": prof.name}
    used = set(CURA_COVERED)

    for canon, _sec, kind, ck, _p, _o, _d in ROWS:
        if ck and ck in v:
            val = v[ck]
            C[canon] = bool(val) if kind == "bool" else (int(val) if kind == "int" else (val if kind == "str" else _f(val)))
            used.add(ck)

    roof = int(_f(v.get("roofing_layer_count"), 0))
    used.add("roofing_layer_count")
    if roof == 0:  # no separate top-surface region in Cura: top == solid skin
        C["speed_top"] = _f(v["speed_topbottom"])
        C["accel_top"] = _f(v.get("acceleration_topbottom", C.get("accel_top", 0)))
        C["jerk_top"] = _f(v.get("jerk_topbottom", C.get("jerk_top", 0)))
        C["top_line_width"] = _f(v["skin_line_width"])
    else:
        C["top_line_width"] = _f(v.get("roofing_line_width", v["skin_line_width"]))

    C["first_layer_line_width"] = _f(v["line_width"]) * _f(v["initial_layer_line_width_factor"], 100) / 100.0
    C["infill_pattern"] = enum_to_canon(INFILL, v["infill_pattern"], "cura", INFILL_ALIASES)
    lh = _f(v["layer_height"], 0.2) or 0.2
    C["infill_every_layers"] = max(1, int(round(_f(v.get("infill_sparse_thickness"), lh) / lh)))
    mono = bool(v.get("skin_monotonic"))
    bottom = v.get("top_bottom_pattern", "lines")
    C["bottom_pattern"] = "monotonic" if (bottom == "lines" and mono) else bottom
    if roof > 0:
        tp, tm = v.get("roofing_pattern", bottom), bool(v.get("roofing_monotonic", mono))
    else:
        tp, tm = bottom, mono
    C["top_pattern"] = "monotonic" if (tp == "lines" and tm) else tp
    used.update({"infill_pattern", "infill_sparse_thickness", "skin_monotonic", "top_bottom_pattern",
                 "roofing_pattern", "roofing_monotonic"})

    C["wall_outer_first"] = v.get("inset_direction") == "outside_in"
    C["wall_generator"] = "arachne"
    C["seam"] = enum_to_canon(SEAM, v.get("z_seam_type"), "cura", SEAM_ALIASES)
    if v.get("z_seam_type") == "sharpest_corner":
        rep.approx("Seam 'sharpest corner' -> 'aligned' (both hide seams in corners, not identical)")
    used.update({"inset_direction", "z_seam_type", "z_seam_corner", "z_seam_position"})

    C["accel_enabled"] = bool(v.get("acceleration_enabled"))
    C["jerk_enabled"] = bool(v.get("jerk_enabled"))
    used.update({"acceleration_enabled", "jerk_enabled"})

    # support
    C["support_enabled"] = bool(v.get("support_enable"))
    C["support_style"] = "tree" if v.get("support_structure") == "tree" else "normal"
    C["support_buildplate_only"] = v.get("support_type") == "buildplate"
    C["support_overhang_angle"] = _f(v.get("support_angle"), 50)
    C["support_pattern"] = v.get("support_pattern", "zigzag")
    rate = _f(v.get("support_infill_rate"), 0)
    if rate > 0:
        C["support_gap"] = max(0.0, _f(v["support_line_distance"]) - _f(v["support_line_width"]))
    lhh = lh
    if v.get("support_interface_enable"):
        C["support_interface_top_layers"] = int(round(_f(v["support_roof_height"]) / lhh)) if v.get("support_roof_enable") else 0
        C["support_interface_bottom_layers"] = int(round(_f(v["support_bottom_height"]) / lhh)) if v.get("support_bottom_enable") else 0
    else:
        C["support_interface_top_layers"] = C["support_interface_bottom_layers"] = 0
    used.update({"support_enable", "support_structure", "support_type", "support_angle", "support_pattern",
                 "support_interface_enable"})

    # adhesion
    C["adhesion_type"] = v.get("adhesion_type", "skirt")
    C["skirt_loops"] = int(_f(v.get("skirt_line_count"), 1)) if C["adhesion_type"] == "skirt" else 0
    C["brim_width"] = _f(v.get("brim_width")) if C["adhesion_type"] == "brim" else 0.0
    C["brim_outer_only"] = v.get("brim_location", "outside") == "outside"
    C["raft_layers"] = (1 + int(_f(v.get("raft_interface_layers"), 1)) + int(_f(v.get("raft_surface_layers"), 2))
                        if C["adhesion_type"] == "raft" else 0)
    used.update({"adhesion_type", "skirt_line_count", "brim_width", "brim_location", "brim_line_count"})

    # bridges
    if v.get("bridge_settings_enabled"):
        C["bridge_flow"] = _f(v.get("bridge_skin_material_flow"), 100) / 100.0
    else:
        C["bridge_flow"] = 1.0
        C["speed_bridge"] = _f(v["speed_topbottom"])
        C["bridge_fan"] = _f(v.get("cool_fan_speed_min"), 100)
        rep.approx("Cura bridge settings are off: bridges use skin speed/flow and regular fan; written as such")
    used.update({"bridge_settings_enabled", "bridge_skin_material_flow"})

    C["ironing_enabled"] = bool(v.get("ironing_enabled"))
    C["ironing_topmost_only"] = bool(v.get("ironing_only_highest_layer"))
    C["elephant_foot"] = max(0.0, _f(v.get("xy_offset")) - _f(v.get("xy_offset_layer_0")))
    C["one_at_a_time"] = v.get("print_sequence") == "one_at_a_time"
    C["draft_shield"] = bool(v.get("draft_shield_enabled"))
    C["avoid_crossing"] = bool(v.get("travel_avoid_other_parts"))
    if v.get("magic_fuzzy_skin_enabled"):
        C["fuzzy_skin"] = "external" if v.get("magic_fuzzy_skin_outside_only") else "all"
    else:
        C["fuzzy_skin"] = "none"
    used.update({"ironing_enabled", "ironing_only_highest_layer", "xy_offset_layer_0", "print_sequence",
                 "draft_shield_enabled", "travel_avoid_other_parts", "magic_fuzzy_skin_enabled",
                 "magic_fuzzy_skin_outside_only"})
    if v.get("retraction_combing") not in (None, "off"):
        rep.approx(f"Cura combing '{v.get('retraction_combing')}' has no direct equivalent; "
                   "'avoid crossing walls' mapped from Cura 'Avoid Printed Parts When Traveling'")

    # filament
    C["bed_temp"] = _f(v["material_bed_temperature"])
    C["bed_temp_first_layer"] = _f(v["material_bed_temperature_layer_0"])
    C["flow_ratio"] = _f(v.get("material_flow"), 100) / 100.0
    C["fan_enabled"] = bool(v.get("cool_fan_enabled"))
    C["fan_min"] = _f(v.get("cool_fan_speed_min")) if C["fan_enabled"] else 0.0
    C["fan_max"] = _f(v.get("cool_fan_speed_max")) if C["fan_enabled"] else 0.0
    fs0 = _f(v.get("cool_fan_speed_0"))
    C["fan_off_first_layers"] = 1 if fs0 == 0 else 0
    if 0 < fs0 < C["fan_min"]:
        rep.approx(f"Cura initial fan speed {fs0:g}% ramps up; written as fan off for layer 1 then ramp to full at layer {C.get('fan_full_layer')}")
    mat = (rc.material or "")
    gm = ce._generic_material_for(mat, res.generic_materials, _f(v.get("material_diameter"), 1.75))
    C["filament_type"] = res.generic_materials.get(gm, {}).get("material", "PLA").split()[0].upper()
    used.update({"material_flow", "cool_fan_enabled", "cool_fan_speed_min", "cool_fan_speed_max", "cool_fan_speed_0"})

    # printer
    C["bed_x"], C["bed_y"] = _f(v["machine_width"]), _f(v["machine_depth"])
    C["bed_origin_center"] = bool(v.get("machine_center_is_zero"))
    C["gcode_flavor"] = CURA_FLAVOR_TO_CANON.get(v.get("machine_gcode_flavor"), "marlin2")
    C["start_gcode"] = v.get("machine_start_gcode", "")
    C["end_gcode"] = v.get("machine_end_gcode", "")
    C["zhop"] = _f(v.get("retraction_hop")) if v.get("retraction_hop_enabled") else 0.0
    C["max_jerk_x"] = C["max_jerk_y"] = _f(v.get("machine_max_jerk_xy"))
    if not v.get("retraction_enable", True):
        C["retract_length"] = 0.0
        rep.note("Retraction is disabled in this Cura profile; retraction length written as 0.")
    used.update({"machine_width", "machine_depth", "machine_gcode_flavor", "machine_start_gcode", "machine_end_gcode",
                 "retraction_hop", "retraction_hop_enabled", "machine_max_jerk_xy"})

    for k, val in rc.explicit.items():
        if k not in used:
            rep.not_converted[k] = val
    C["_src_values"] = dict(v)
    return C, rep, rc


# ---------------------------------------------------------------------------
# canonical -> Cura
# ---------------------------------------------------------------------------

MACHINE_ONLY = {"bed_x", "bed_y", "bed_origin_center", "gcode_flavor", "start_gcode", "end_gcode", "max_height",
                "nozzle_diameter", "filament_diameter", "max_feed_x", "max_feed_y", "max_feed_z", "max_feed_e",
                "max_accel_x", "max_accel_y", "max_accel_z", "max_accel_e", "max_accel_print", "max_jerk_x",
                "max_jerk_y", "max_jerk_z", "max_jerk_e"}


def build_values(C: Dict[str, Any], res: ce.Resources, machine: str, rep: Report, src_slicer: str,
                 material: Optional[str] = None, variant: Optional[str] = None,
                 machine_extra: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], str]:
    """Canonical settings -> (Cura values for a custom profile, quality type to base it on)."""
    if machine_extra is None:
        machine_extra = {}
    vals: Dict[str, Any] = {}
    present = lambda k: C.get(k) is not None

    defs = res.setting_definitions(machine)
    for canon, _sec, kind, ck, _p, _o, desc in ROWS:
        if canon in MACHINE_ONLY or not ck or not present(canon):
            continue
        if defs.get(ck, {}).get("category") == "machine_settings":
            machine_extra[desc] = C[canon]
            rep.converted[canon] = C[canon]
            continue
        if ck in vals:  # first mapping wins (e.g. skin_line_width shared by two canon keys)
            continue
        if canon in ("top_line_width", "speed_top", "accel_top", "jerk_top", "speed_first_layer_infill"):
            continue
        vals[ck] = C[canon]
        rep.converted[canon] = C[canon]

    lh = float(C.get("layer_height") or 0.2)
    # top surface region ("roofing")
    top_differs = any(present(a) and present(b) and abs(float(C[a]) - float(C[b])) > 1e-6
                      for a, b in (("speed_top", "speed_solid_infill"), ("top_line_width", "solid_infill_line_width")))
    if C.get("top_pattern") and C.get("bottom_pattern") and C["top_pattern"] != C["bottom_pattern"]:
        top_differs = True
    if top_differs:
        vals["roofing_layer_count"] = 1
        for canon, ck in (("speed_top", "speed_roofing"), ("top_line_width", "roofing_line_width"),
                          ("accel_top", "acceleration_roofing"), ("jerk_top", "jerk_roofing")):
            if present(canon):
                vals[ck] = C[canon]
                rep.converted[canon] = C[canon]
        rep.approx("Separate top-surface settings written as Cura 'Top Surface Skin Layers' = 1")
    if present("speed_first_layer_infill") and present("speed_first_layer") and \
            abs(C["speed_first_layer_infill"] - C["speed_first_layer"]) > 1e-6:
        rep.approx("Cura has one first-layer print speed; first-layer infill speed dropped")
    if present("first_layer_line_width") and present("line_width") and C["line_width"]:
        vals["initial_layer_line_width_factor"] = round(C["first_layer_line_width"] / C["line_width"] * 100, 2)
        rep.converted["first_layer_line_width"] = C["first_layer_line_width"]

    # infill
    nat, ap = enum_to_native(INFILL, C.get("infill_pattern"), "cura")
    if nat:
        vals["infill_pattern"] = nat
        rep.converted["infill_pattern"] = C["infill_pattern"]
        if ap:
            rep.approx(f"Infill pattern '{C['infill_pattern']}' -> Cura '{nat}'")
    if present("infill_every_layers") and int(C["infill_every_layers"]) > 1:
        vals["infill_sparse_thickness"] = round(int(C["infill_every_layers"]) * lh, 4)
        rep.converted["infill_every_layers"] = C["infill_every_layers"]

    def surf(p):
        if p in ("monotonic", "monotoniclines"):
            return "lines", True, p != "monotonic"
        if p in ("lines", "concentric", "zigzag"):
            return p, False, False
        return ("concentric", False, True) if p in ("archimedeanchords", "octagramspiral", "spiralinset") else ("lines", False, True)
    if C.get("bottom_pattern"):
        p, m, a = surf(C["bottom_pattern"])
        vals["top_bottom_pattern"], vals["skin_monotonic"] = p, m
        rep.converted["bottom_pattern"] = C["bottom_pattern"]
        if a:
            rep.approx(f"Bottom pattern '{C['bottom_pattern']}' -> Cura '{p}'")
    if C.get("top_pattern"):
        p, m, a = surf(C["top_pattern"])
        if top_differs:
            vals["roofing_pattern"], vals["roofing_monotonic"] = p, m
        rep.converted["top_pattern"] = C["top_pattern"]
        if a:
            rep.approx(f"Top pattern '{C['top_pattern']}' -> Cura '{p}'")

    if present("wall_outer_first"):
        vals["inset_direction"] = "outside_in" if C["wall_outer_first"] else "inside_out"
        rep.converted["wall_outer_first"] = C["wall_outer_first"]
    if C.get("wall_generator") == "classic":
        rep.approx("Cura always uses variable-width (Arachne-style) walls; 'classic' perimeters not available")
    nat, ap = enum_to_native(SEAM, C.get("seam"), "cura")
    if nat:
        vals["z_seam_type"] = nat
        rep.converted["seam"] = C["seam"]
        if C["seam"] == "aligned":
            rep.approx("Seam 'aligned' -> Cura 'sharpest corner'")

    # acceleration / jerk
    for flag, prefix, keys in (("accel_enabled", "accel_", "acceleration_enabled"), ("jerk_enabled", "jerk_", "jerk_enabled")):
        if present(flag):
            vals[keys] = bool(C[flag])
            rep.converted[flag] = C[flag]
            if not C[flag]:
                for canon, *_ in ROWS:
                    if canon.startswith(prefix):
                        ck = mapping_cura(canon)
                        vals.pop(ck, None)
                        rep.converted.pop(canon, None)

    # support
    if present("support_enabled"):
        vals["support_enable"] = bool(C["support_enabled"])
        vals["support_structure"] = "tree" if C.get("support_style") == "tree" else "normal"
        vals["support_type"] = "buildplate" if C.get("support_buildplate_only") else "everywhere"
        for k in ("support_enabled", "support_style", "support_buildplate_only"):
            if present(k):
                rep.converted[k] = C[k]
    if present("support_overhang_angle"):
        vals["support_angle"] = round(float(C["support_overhang_angle"]), 2)
        rep.converted["support_overhang_angle"] = C["support_overhang_angle"]
    nat, ap = enum_to_native(SUPPORT_PATTERN, C.get("support_pattern"), "cura")
    if nat:
        vals["support_pattern"] = nat
        rep.converted["support_pattern"] = C["support_pattern"]
        if ap:
            rep.approx(f"Support pattern '{C['support_pattern']}' -> Cura '{nat}'")
    if present("support_gap"):
        w = float(C.get("support_line_width") or C.get("line_width") or 0.4)
        dist = float(C["support_gap"]) + w
        mult = {"grid": 2, "triangles": 3, "cross": 1}.get(vals.get("support_pattern", "zigzag"), 1)
        vals["support_line_distance"] = round(dist, 4)
        vals["support_infill_rate"] = round(min(100.0, w * 100 * mult / dist), 2)
        rep.converted["support_gap"] = C["support_gap"]
    t, b = C.get("support_interface_top_layers"), C.get("support_interface_bottom_layers")
    if t is not None or b is not None:
        t, b = int(t or 0), int(b or 0)
        vals["support_interface_enable"] = (t > 0 or b > 0)
        vals["support_roof_enable"] = t > 0
        vals["support_bottom_enable"] = b > 0
        if t > 0:
            vals["support_roof_height"] = round(t * lh, 4)
        if b > 0:
            vals["support_bottom_height"] = round(b * lh, 4)
        rep.converted["support_interface_top_layers"] = t
        rep.converted["support_interface_bottom_layers"] = b

    # adhesion
    at = C.get("adhesion_type")
    if at:
        vals["adhesion_type"] = at
        rep.converted["adhesion_type"] = at
        if at == "skirt" and present("skirt_loops"):
            vals["skirt_line_count"] = int(C["skirt_loops"])
            rep.converted["skirt_loops"] = C["skirt_loops"]
        if at == "brim" and present("brim_width"):
            vals["brim_width"] = C["brim_width"]
            vals["brim_location"] = "outside" if C.get("brim_outer_only", True) else "everywhere"
            rep.converted["brim_width"] = C["brim_width"]
        if at == "raft" and present("raft_layers"):
            n = int(C["raft_layers"])
            vals["raft_interface_layers"] = 1
            vals["raft_surface_layers"] = max(1, n - 2)
            rep.converted["raft_layers"] = n
            rep.approx(f"Raft of {n} layers -> Cura base 1 + interface 1 + surface {max(1, n - 2)}")

    if present("bridge_flow"):
        special = (abs(float(C["bridge_flow"]) - 1.0) > 1e-3 or
                   (present("speed_bridge") and present("speed_solid_infill") and abs(C["speed_bridge"] - C["speed_solid_infill"]) > 1e-3) or
                   (present("bridge_fan") and abs(float(C["bridge_fan"]) - float(C.get("fan_min") or 0)) > 1e-3))
        vals["bridge_settings_enabled"] = bool(special)
        if special:
            vals["bridge_skin_material_flow"] = round(float(C["bridge_flow"]) * 100, 2)
        else:
            vals.pop("bridge_skin_speed", None)
            vals.pop("bridge_fan_speed", None)
        rep.converted["bridge_flow"] = C["bridge_flow"]
    for flag, ck in (("ironing_enabled", "ironing_enabled"), ("ironing_topmost_only", "ironing_only_highest_layer"),
                     ("draft_shield", "draft_shield_enabled"), ("avoid_crossing", "travel_avoid_other_parts")):
        if present(flag):
            vals[ck] = bool(C[flag])
            rep.converted[flag] = C[flag]
    if present("one_at_a_time"):
        vals["print_sequence"] = "one_at_a_time" if C["one_at_a_time"] else "all_at_once"
        rep.converted["one_at_a_time"] = C["one_at_a_time"]
    if present("elephant_foot"):
        vals["xy_offset_layer_0"] = round(float(C.get("xy_compensation") or 0) - float(C["elephant_foot"]), 4)
        rep.converted["elephant_foot"] = C["elephant_foot"]
    if present("fuzzy_skin"):
        vals["magic_fuzzy_skin_enabled"] = C["fuzzy_skin"] != "none"
        if C["fuzzy_skin"] != "none":
            vals["magic_fuzzy_skin_outside_only"] = C["fuzzy_skin"] == "external"
        rep.converted["fuzzy_skin"] = C["fuzzy_skin"]

    # filament
    for canon, ck in (("bed_temp", "material_bed_temperature"), ("bed_temp_first_layer", "material_bed_temperature_layer_0")):
        if present(canon):
            vals[ck] = C[canon]
            rep.converted[canon] = C[canon]
    if present("flow_ratio"):
        vals["material_flow"] = round(float(C["flow_ratio"]) * 100, 2)
        rep.converted["flow_ratio"] = C["flow_ratio"]
    if present("fan_max") or present("fan_min"):
        fmin, fmax = float(C.get("fan_min") or 0), float(C.get("fan_max") or 0)
        on = bool(C.get("fan_enabled", fmax > 0))
        vals["cool_fan_enabled"] = on
        vals["cool_fan_speed"] = fmin
        vals["cool_fan_speed_min"] = fmin
        vals["cool_fan_speed_max"] = max(fmin, fmax)
        for k in ("fan_enabled", "fan_min", "fan_max"):
            if present(k):
                rep.converted[k] = C[k]
        if fmin == 0 and fmax > 0:
            rep.approx("Fan only runs on short layers in the source; Cura regular fan speed set to 0%")
    if present("fan_full_layer"):
        ffl = max(int(C["fan_full_layer"] or 0), int(C.get("fan_off_first_layers") or 0) + 1, 1)
        vals["cool_fan_full_layer"] = ffl
        C = dict(C, fan_full_layer=ffl)
    if present("fan_off_first_layers"):
        n = int(C["fan_off_first_layers"])
        vals["cool_fan_speed_0"] = 0 if n > 0 else float(C.get("fan_min") or 0)
        rep.converted["fan_off_first_layers"] = n
        if n > 1:
            rep.approx(f"Fan off for {n} layers: Cura only has 'initial fan speed' + ramp to full at layer "
                       f"{C.get('fan_full_layer')}; first layer off, then ramp")
    if present("zhop"):
        vals["retraction_hop_enabled"] = float(C["zhop"]) > 0
        if float(C["zhop"]) > 0:
            vals["retraction_hop"] = C["zhop"]
        rep.converted["zhop"] = C["zhop"]

    # anything with no Cura equivalent
    for canon, _sec, _k, ck, _p, _o, desc in ROWS:
        if ck is None and present(canon) and C[canon] not in (0, 0.0, False, ""):
            rep.target_missing.append(f"{canon} ({desc}) = {C[canon]}")

    # sanity: only keep keys Cura knows
    unknown = [k for k in vals if k not in defs]
    for k in unknown:
        vals.pop(k)
    if unknown:
        rep.note("Dropped keys unknown to the bundled Cura definitions: " + ", ".join(unknown))

    qt, notes = ce.choose_quality(res, machine, lh, material=material, variant=variant)
    for n in notes:
        rep.note(n)
    before = len(vals)
    vals = ce.minimal_changes(res, machine, qt, vals, material=material)
    if before - len(vals):
        rep.note(f"{len(vals)} values written to the Cura profile; {before - len(vals)} more follow from them "
                 f"through Cura's own formulas and were left for Cura to calculate.")
    return vals, qt


def write(C: Dict[str, Any], name: str, outdir: str, res: ce.Resources, machine: str,
          rep: Report, src_slicer: str) -> List[str]:
    machine_extra: Dict[str, Any] = {}
    vals, qt = build_values(C, res, machine, rep, src_slicer, machine_extra=machine_extra)
    os.makedirs(outdir, exist_ok=True)
    data = ce.build_curaprofile(name, vals, res, machine, qt)
    prof_path = os.path.join(outdir, _safe(name) + ".curaprofile")
    with open(prof_path, "wb") as fh:
        fh.write(data)
    rep.note(f"Cura profile uses quality type '{qt}' for machine '{machine}'. In Cura: Preferences > Configure Cura > "
             f"Profiles > Import, with a matching printer selected.")

    # machine settings go to a text file (Cura keeps them in Machine Settings, not in profiles)
    msg = machine_text(C, src_slicer, rep, machine_extra)
    ms_path = os.path.join(outdir, _safe(name) + ".cura_machine_settings.txt")
    with open(ms_path, "w", encoding="utf-8") as fh:
        fh.write(msg)
    return [prof_path, ms_path]


def mapping_cura(canon: str) -> Optional[str]:
    from .mapping import ROW_BY_CANON
    r = ROW_BY_CANON.get(canon)
    return r[3] if r else None


def machine_text(C: Dict[str, Any], src: str, rep: Report, extra: Optional[Dict[str, Any]] = None) -> str:
    def g(k, unit=""):
        v = C.get(k)
        if v is None:
            return "(not in source)"
        if isinstance(v, float):
            v = f"{v:g}"
        return f"{v}{unit}"
    start, n1 = gcode.translate(C.get("start_gcode", ""), src, "cura", C.get("_src_values"))
    end, n2 = gcode.translate(C.get("end_gcode", ""), src, "cura", C.get("_src_values"))
    for n in n1 + n2:
        rep.gcode_notes.append(n)
    flav, ap = enum_to_native(FLAVOR, C.get("gcode_flavor"), "cura")
    if ap:
        rep.approx(f"G-code flavour '{C.get('gcode_flavor')}' -> Cura '{flav}'")
    for k in ("bed_x", "bed_y", "max_height", "nozzle_diameter", "filament_diameter", "gcode_flavor", "start_gcode", "end_gcode"):
        if C.get(k) is not None:
            rep.converted[k] = C[k]
    lines = [
        "Cura printer settings (Preferences > Printers > Machine Settings)",
        "Cura stores these per printer, not in profiles, so enter them by hand.",
        "",
        "Printer tab",
        f"  X (Width) ............. {g('bed_x', ' mm')}",
        f"  Y (Depth) ............. {g('bed_y', ' mm')}",
        f"  Z (Height) ............ {g('max_height', ' mm')}",
        f"  Origin at center ...... {'yes' if C.get('bed_origin_center') else 'no'}",
        f"  G-code flavor ......... {flav or '(not in source)'}",
        "",
        "Extruder 1 tab",
        f"  Nozzle size ........... {g('nozzle_diameter', ' mm')}",
        f"  Compatible material diameter ... {g('filament_diameter', ' mm')}",
        "",
        "Machine limits (Cura uses these for time estimates only;",
        "the 'Printer Settings' plugin from the Marketplace exposes them):",
    ]
    for k in ("max_feed_x", "max_feed_y", "max_feed_z", "max_feed_e", "max_accel_x", "max_accel_y", "max_accel_z",
              "max_accel_e", "max_accel_print", "max_jerk_x", "max_jerk_z", "max_jerk_e"):
        if C.get(k) is not None:
            rep.converted[k] = C[k]
            lines.append(f"  {k:16s} {g(k)}")
    if extra:
        lines += ["", "Other printer settings"]
        for desc, val in extra.items():
            lines.append(f"  {desc} ... {val if not isinstance(val, float) else f'{val:g}'}")
    lines += ["", "Start G-code", "-" * 40, start, "", "End G-code", "-" * 40, end, ""]
    return "\n".join(lines)


def _safe(name: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9._ ()+-]+", "_", name).strip() or "profile"
