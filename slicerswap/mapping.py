# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""The neutral ("canonical") settings model and how each slicer maps onto it.

Every reader turns a slicer file into a flat dict of canonical keys with plain
Python values in fixed units (mm, mm/s, mm/s², °C, %, seconds, layers).
Every writer turns that dict back into native keys. Rows that are a straight
rename live in ROWS; anything needing logic lives in the per-slicer modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# kind: float | int | bool | pct | str | gcode
# (canon, section, kind, cura, prusa, orca, description)
ROWS: List[Tuple[str, str, str, Optional[str], Optional[str], Optional[str], str]] = [
    # ---- layers & widths --------------------------------------------------
    ("layer_height", "print", "float", "layer_height", "layer_height", "layer_height", "Layer height (mm)"),
    ("first_layer_height", "print", "float", "layer_height_0", "first_layer_height", "initial_layer_print_height", "First layer height (mm)"),
    ("line_width", "print", "float", "line_width", "extrusion_width", "line_width", "Default line width (mm)"),
    ("outer_wall_line_width", "print", "float", "wall_line_width_0", "external_perimeter_extrusion_width", "outer_wall_line_width", "Outer wall line width (mm)"),
    ("inner_wall_line_width", "print", "float", "wall_line_width_x", "perimeter_extrusion_width", "inner_wall_line_width", "Inner wall line width (mm)"),
    ("infill_line_width", "print", "float", "infill_line_width", "infill_extrusion_width", "sparse_infill_line_width", "Infill line width (mm)"),
    ("solid_infill_line_width", "print", "float", "skin_line_width", "solid_infill_extrusion_width", "internal_solid_infill_line_width", "Solid infill line width (mm)"),
    ("top_line_width", "print", "float", "skin_line_width", "top_infill_extrusion_width", "top_surface_line_width", "Top surface line width (mm)"),
    ("support_line_width", "print", "float", "support_line_width", "support_material_extrusion_width", "support_line_width", "Support line width (mm)"),
    # first_layer_line_width: special (Cura stores a % factor)
    # ---- shells ------------------------------------------------------------
    ("wall_loops", "print", "int", "wall_line_count", "perimeters", "wall_loops", "Wall line count"),
    ("top_layers", "print", "int", "top_layers", "top_solid_layers", "top_shell_layers", "Top solid layers"),
    ("bottom_layers", "print", "int", "bottom_layers", "bottom_solid_layers", "bottom_shell_layers", "Bottom solid layers"),
    ("top_thickness_min", "print", "float", None, "top_solid_min_thickness", "top_shell_thickness", "Minimum top shell thickness (mm)"),
    ("bottom_thickness_min", "print", "float", None, "bottom_solid_min_thickness", "bottom_shell_thickness", "Minimum bottom shell thickness (mm)"),
    # ---- infill ------------------------------------------------------------
    ("infill_density", "print", "pct", "infill_sparse_density", "fill_density", "sparse_infill_density", "Infill density (%)"),
    ("infill_overlap", "print", "pct", "infill_overlap", "infill_overlap", "infill_wall_overlap", "Infill/wall overlap (% of line width)"),
    ("infill_before_walls", "print", "bool", "infill_before_walls", "infill_first", "is_infill_first", "Print infill before walls"),
    # ---- speeds ------------------------------------------------------------
    ("speed_outer_wall", "print", "float", "speed_wall_0", "external_perimeter_speed", "outer_wall_speed", "Outer wall speed (mm/s)"),
    ("speed_inner_wall", "print", "float", "speed_wall_x", "perimeter_speed", "inner_wall_speed", "Inner wall speed (mm/s)"),
    ("speed_infill", "print", "float", "speed_infill", "infill_speed", "sparse_infill_speed", "Sparse infill speed (mm/s)"),
    ("speed_solid_infill", "print", "float", "speed_topbottom", "solid_infill_speed", "internal_solid_infill_speed", "Solid infill speed (mm/s)"),
    ("speed_top", "print", "float", "speed_roofing", "top_solid_infill_speed", "top_surface_speed", "Top surface speed (mm/s)"),
    ("speed_support", "print", "float", "speed_support_infill", "support_material_speed", "support_speed", "Support speed (mm/s)"),
    ("speed_support_interface", "print", "float", "speed_support_interface", "support_material_interface_speed", "support_interface_speed", "Support interface speed (mm/s)"),
    ("speed_bridge", "print", "float", "bridge_skin_speed", "bridge_speed", "bridge_speed", "Bridge speed (mm/s)"),
    ("speed_travel", "print", "float", "speed_travel", "travel_speed", "travel_speed", "Travel speed (mm/s)"),
    ("speed_first_layer", "print", "float", "speed_print_layer_0", "first_layer_speed", "initial_layer_speed", "First layer print speed (mm/s)"),
    ("speed_first_layer_infill", "print", "float", "speed_print_layer_0", "first_layer_infill_speed", "initial_layer_infill_speed", "First layer infill speed (mm/s)"),
    ("speed_first_layer_travel", "print", "float", "speed_travel_layer_0", None, "initial_layer_travel_speed", "First layer travel speed (mm/s)"),
    ("speed_ironing", "print", "float", "speed_ironing", "ironing_speed", "ironing_speed", "Ironing speed (mm/s)"),
    # ---- acceleration (0 = machine default in Prusa/Orca) ------------------
    ("accel_default", "print", "float", "acceleration_print", "default_acceleration", "default_acceleration", "Default print acceleration (mm/s²)"),
    ("accel_outer_wall", "print", "float", "acceleration_wall_0", "external_perimeter_acceleration", "outer_wall_acceleration", "Outer wall acceleration"),
    ("accel_inner_wall", "print", "float", "acceleration_wall_x", "perimeter_acceleration", "inner_wall_acceleration", "Inner wall acceleration"),
    ("accel_infill", "print", "float", "acceleration_infill", "infill_acceleration", "sparse_infill_acceleration", "Infill acceleration"),
    ("accel_solid_infill", "print", "float", "acceleration_topbottom", "solid_infill_acceleration", "internal_solid_infill_acceleration", "Solid infill acceleration"),
    ("accel_top", "print", "float", "acceleration_roofing", "top_solid_infill_acceleration", "top_surface_acceleration", "Top surface acceleration"),
    ("accel_travel", "print", "float", "acceleration_travel", "travel_acceleration", "travel_acceleration", "Travel acceleration"),
    ("accel_first_layer", "print", "float", "acceleration_layer_0", "first_layer_acceleration", "initial_layer_acceleration", "First layer acceleration"),
    ("accel_bridge", "print", "float", None, "bridge_acceleration", "bridge_acceleration", "Bridge acceleration"),
    # ---- jerk (Prusa has no per-feature jerk) -------------------------------
    ("jerk_default", "print", "float", "jerk_print", None, "default_jerk", "Default jerk (mm/s)"),
    ("jerk_outer_wall", "print", "float", "jerk_wall_0", None, "outer_wall_jerk", "Outer wall jerk"),
    ("jerk_inner_wall", "print", "float", "jerk_wall_x", None, "inner_wall_jerk", "Inner wall jerk"),
    ("jerk_infill", "print", "float", "jerk_infill", None, "infill_jerk", "Infill jerk"),
    ("jerk_top", "print", "float", "jerk_roofing", None, "top_surface_jerk", "Top surface jerk"),
    ("jerk_travel", "print", "float", "jerk_travel", None, "travel_jerk", "Travel jerk"),
    ("jerk_first_layer", "print", "float", "jerk_layer_0", None, "initial_layer_jerk", "First layer jerk"),
    # ---- support -----------------------------------------------------------
    ("support_top_z", "print", "float", "support_top_distance", "support_material_contact_distance", "support_top_z_distance", "Support top Z gap (mm)"),
    ("support_bottom_z", "print", "float", "support_bottom_distance", "support_material_bottom_contact_distance", "support_bottom_z_distance", "Support bottom Z gap (mm)"),
    ("support_xy", "print", "float", "support_xy_distance", "support_material_xy_spacing", "support_object_xy_distance", "Support XY gap (mm)"),
    # ---- adhesion ----------------------------------------------------------
    ("skirt_distance", "print", "float", "skirt_gap", "skirt_distance", "skirt_distance", "Skirt distance (mm)"),
    ("skirt_height", "print", "int", "skirt_height", "skirt_height", "skirt_height", "Skirt height (layers)"),
    ("brim_gap", "print", "float", "brim_gap", "brim_separation", "brim_object_gap", "Brim gap (mm)"),
    # ---- misc --------------------------------------------------------------
    ("spiral_vase", "print", "bool", "magic_spiralize", "spiral_vase", "spiral_mode", "Spiral vase mode"),
    ("xy_compensation", "print", "float", "xy_offset", "xy_size_compensation", "xy_contour_compensation", "Horizontal expansion (mm)"),
    ("fuzzy_thickness", "print", "float", "magic_fuzzy_skin_thickness", "fuzzy_skin_thickness", "fuzzy_skin_thickness", "Fuzzy skin thickness (mm)"),
    ("fuzzy_point_dist", "print", "float", "magic_fuzzy_skin_point_dist", "fuzzy_skin_point_dist", "fuzzy_skin_point_distance", "Fuzzy skin point distance (mm)"),
    ("ironing_spacing", "print", "float", "ironing_line_spacing", "ironing_spacing", "ironing_spacing", "Ironing line spacing (mm)"),
    ("ironing_flow", "print", "pct", "ironing_flow", "ironing_flowrate", "ironing_flow", "Ironing flow (%)"),
    ("bridge_angle", "print", "float", None, "bridge_angle", "bridge_angle", "Bridge infill angle (0 = auto)"),
    ("speed_gap_fill", "print", "float", None, "gap_fill_speed", "gap_infill_speed", "Gap fill speed (mm/s)"),
    ("speed_small_perimeter", "print", "float", None, "small_perimeter_speed", "small_perimeter_speed", "Small perimeter speed (mm/s)"),
    ("infill_angle", "print", "float", None, "fill_angle", "infill_direction", "Infill direction (deg)"),
    ("support_interface_spacing", "print", "float", None, "support_material_interface_spacing", "support_interface_spacing", "Support interface line spacing (mm)"),
    ("support_angle", "print", "float", None, "support_material_angle", "support_angle", "Support pattern angle (deg)"),
    ("raft_contact_distance", "print", "float", "raft_airgap", "raft_contact_distance", "raft_contact_distance", "Raft top Z gap (mm)"),
    ("interface_shells", "print", "bool", None, "interface_shells", "interface_shells", "Interface shells"),
    ("dont_support_bridges", "print", "bool", None, "dont_support_bridges", "bridge_no_support", "Don't support bridges"),
    ("detect_overhang_walls", "print", "bool", None, "overhangs", "detect_overhang_wall", "Detect overhang walls"),
    ("thick_bridges", "print", "bool", None, "thick_bridges", "thick_bridges", "Thick bridges"),
    # ---- filament ----------------------------------------------------------
    ("nozzle_temp", "filament", "float", "material_print_temperature", "temperature", "nozzle_temperature", "Nozzle temperature (°C)"),
    ("nozzle_temp_first_layer", "filament", "float", "material_print_temperature_layer_0", "first_layer_temperature", "nozzle_temperature_initial_layer", "First layer nozzle temperature (°C)"),
    ("filament_diameter", "filament", "float", "material_diameter", "filament_diameter", "filament_diameter", "Filament diameter (mm)"),
    ("fan_full_layer", "filament", "int", "cool_fan_full_layer", "full_fan_speed_layer", "full_fan_speed_layer", "Layer where fan reaches regular speed"),
    ("fan_below_layer_time", "filament", "float", "cool_min_layer_time_fan_speed_max", "fan_below_layer_time", "fan_cooling_layer_time", "Max fan when layer time below (s)"),
    ("slowdown_layer_time", "filament", "float", "cool_min_layer_time", "slowdown_below_layer_time", "slow_down_layer_time", "Minimum layer time (s)"),
    ("min_print_speed", "filament", "float", "cool_min_speed", "min_print_speed", "slow_down_min_speed", "Minimum print speed when slowing down (mm/s)"),
    ("bridge_fan", "filament", "pct", "bridge_fan_speed", "bridge_fan_speed", "overhang_fan_speed", "Bridge / overhang fan (%)"),
    # ---- printer -----------------------------------------------------------
    ("max_height", "printer", "float", "machine_height", "max_print_height", "printable_height", "Max print height (mm)"),
    ("nozzle_diameter", "printer", "float", "machine_nozzle_size", "nozzle_diameter", "nozzle_diameter", "Nozzle diameter (mm)"),
    ("retract_length", "printer", "float", "retraction_amount", "retract_length", "retraction_length", "Retraction length (mm)"),
    ("retract_speed", "printer", "float", "retraction_retract_speed", "retract_speed", "retraction_speed", "Retraction speed (mm/s)"),
    ("deretract_speed", "printer", "float", "retraction_prime_speed", "deretract_speed", "deretraction_speed", "Prime (deretract) speed (mm/s)"),
    ("retract_extra_prime", "printer", "float", "retraction_extra_prime_amount", "retract_restart_extra", "retract_restart_extra", "Extra prime after retraction (mm)"),
    ("retract_min_travel", "printer", "float", "retraction_min_travel", "retract_before_travel", "retraction_minimum_travel", "Minimum travel before retracting (mm)"),
    ("retract_layer_change", "printer", "bool", "retract_at_layer_change", "retract_layer_change", "retract_when_changing_layer", "Retract on layer change"),
    ("max_feed_x", "printer", "float", "machine_max_feedrate_x", "machine_max_feedrate_x", "machine_max_speed_x", "Max feedrate X (mm/s)"),
    ("max_feed_y", "printer", "float", "machine_max_feedrate_y", "machine_max_feedrate_y", "machine_max_speed_y", "Max feedrate Y (mm/s)"),
    ("max_feed_z", "printer", "float", "machine_max_feedrate_z", "machine_max_feedrate_z", "machine_max_speed_z", "Max feedrate Z (mm/s)"),
    ("max_feed_e", "printer", "float", "machine_max_feedrate_e", "machine_max_feedrate_e", "machine_max_speed_e", "Max feedrate E (mm/s)"),
    ("max_accel_x", "printer", "float", "machine_max_acceleration_x", "machine_max_acceleration_x", "machine_max_acceleration_x", "Max acceleration X"),
    ("max_accel_y", "printer", "float", "machine_max_acceleration_y", "machine_max_acceleration_y", "machine_max_acceleration_y", "Max acceleration Y"),
    ("max_accel_z", "printer", "float", "machine_max_acceleration_z", "machine_max_acceleration_z", "machine_max_acceleration_z", "Max acceleration Z"),
    ("max_accel_e", "printer", "float", "machine_max_acceleration_e", "machine_max_acceleration_e", "machine_max_acceleration_e", "Max acceleration E"),
    ("max_accel_print", "printer", "float", "machine_acceleration", "machine_max_acceleration_extruding", "machine_max_acceleration_extruding", "Max print acceleration"),
    ("max_accel_retract", "printer", "float", None, "machine_max_acceleration_retracting", "machine_max_acceleration_retracting", "Max retract acceleration"),
    ("max_accel_travel", "printer", "float", None, "machine_max_acceleration_travel", "machine_max_acceleration_travel", "Max travel acceleration"),
    ("min_extruding_rate", "printer", "float", "machine_minimum_feedrate", "machine_min_extruding_rate", "machine_min_extruding_rate", "Minimum feedrate (mm/s)"),
    ("min_travel_rate", "printer", "float", None, "machine_min_travel_rate", "machine_min_travel_rate", "Minimum travel feedrate (mm/s)"),
    ("min_layer_height", "printer", "float", None, "min_layer_height", "min_layer_height", "Min layer height for adaptive layers (mm)"),
    ("max_layer_height", "printer", "float", None, "max_layer_height", "max_layer_height", "Max layer height for adaptive layers (mm)"),
    ("zhop_above", "printer", "float", None, "retract_lift_above", "retract_lift_above", "Only Z hop above this height (mm)"),
    ("zhop_below", "printer", "float", None, "retract_lift_below", "retract_lift_below", "Only Z hop below this height (mm)"),
    ("relative_e", "printer", "bool", "relative_extrusion", "use_relative_e_distances", "use_relative_e_distances", "Relative extrusion (M83)"),
    ("firmware_retraction", "printer", "bool", "machine_firmware_retract", "use_firmware_retraction", "use_firmware_retraction", "Firmware retraction (G10/G11)"),
    ("z_offset", "printer", "float", None, "z_offset", "z_offset", "Z offset (mm)"),
    ("layer_gcode", "printer", "gcode", None, "layer_gcode", "layer_change_gcode", "After layer change G-code"),
    ("before_layer_gcode", "printer", "gcode", None, "before_layer_gcode", "before_layer_change_gcode", "Before layer change G-code"),
    ("max_volumetric_speed", "filament", "float", None, "filament_max_volumetric_speed", "filament_max_volumetric_speed", "Max volumetric speed (mm³/s)"),
    ("chamber_temp", "filament", "float", "build_volume_temperature", "chamber_temperature", "chamber_temperature", "Chamber temperature (°C)"),
    ("standby_temp", "filament", "float", "material_standby_temperature", None, "idle_temperature", "Standby / idle temperature (°C)"),
    ("max_jerk_z", "printer", "float", "machine_max_jerk_z", "machine_max_jerk_z", "machine_max_jerk_z", "Max jerk Z"),
    ("max_jerk_e", "printer", "float", "machine_max_jerk_e", "machine_max_jerk_e", "machine_max_jerk_e", "Max jerk E"),
]

ROW_BY_CANON = {r[0]: r for r in ROWS}

# Canonical keys produced/consumed by the special handlers (documented for the report).
SPECIAL_CANON = {
    "first_layer_line_width": ("print", "First layer line width (mm)"),
    "infill_pattern": ("print", "Infill pattern"),
    "infill_every_layers": ("print", "Combine infill every N layers"),
    "top_pattern": ("print", "Top surface pattern"),
    "bottom_pattern": ("print", "Bottom surface pattern"),
    "wall_outer_first": ("print", "Print outer wall first"),
    "wall_generator": ("print", "Wall generator (arachne/classic)"),
    "seam": ("print", "Seam placement"),
    "accel_enabled": ("print", "Per-feature acceleration control on"),
    "jerk_enabled": ("print", "Per-feature jerk control on"),
    "support_enabled": ("print", "Generate support"),
    "support_style": ("print", "Support style (normal/tree)"),
    "support_buildplate_only": ("print", "Support on build plate only"),
    "support_overhang_angle": ("print", "Overhang angle, measured from vertical like Cura (deg)"),
    "support_pattern": ("print", "Support pattern"),
    "support_gap": ("print", "Gap between support lines (mm)"),
    "support_interface_top_layers": ("print", "Support roof layers"),
    "support_interface_bottom_layers": ("print", "Support floor layers"),
    "adhesion_type": ("print", "none/skirt/brim/raft"),
    "skirt_loops": ("print", "Skirt loops"),
    "brim_width": ("print", "Brim width (mm)"),
    "brim_outer_only": ("print", "Brim outside only"),
    "raft_layers": ("print", "Raft layers"),
    "bridge_flow": ("print", "Bridge flow (fraction)"),
    "ironing_enabled": ("print", "Ironing on"),
    "ironing_topmost_only": ("print", "Iron only the topmost surface"),
    "elephant_foot": ("print", "Elephant foot compensation (mm)"),
    "one_at_a_time": ("print", "Print objects one at a time"),
    "draft_shield": ("print", "Draft shield"),
    "avoid_crossing": ("print", "Avoid crossing walls on travel"),
    "fuzzy_skin": ("print", "Fuzzy skin: none/external/all"),
    "bed_temp": ("filament", "Bed temperature (°C)"),
    "bed_temp_first_layer": ("filament", "First layer bed temperature (°C)"),
    "flow_ratio": ("filament", "Flow multiplier (1.0 = 100%)"),
    "fan_enabled": ("filament", "Part cooling on"),
    "fan_min": ("filament", "Regular fan speed (%)"),
    "fan_max": ("filament", "Maximum fan speed (%)"),
    "fan_off_first_layers": ("filament", "Fan off for the first N layers"),
    "filament_type": ("filament", "Material type (PLA, PETG...)"),
    "bed_x": ("printer", "Bed width (mm)"),
    "bed_y": ("printer", "Bed depth (mm)"),
    "bed_origin_center": ("printer", "Origin at bed centre"),
    "gcode_flavor": ("printer", "G-code flavour"),
    "start_gcode": ("printer", "Start G-code"),
    "end_gcode": ("printer", "End G-code"),
    "zhop": ("printer", "Z hop on retraction (mm, 0 = off)"),
    "max_jerk_x": ("printer", "Max jerk X"),
    "max_jerk_y": ("printer", "Max jerk Y"),
}

# ---------------------------------------------------------------------------
# Enum tables. Canonical names follow Cura where possible.
# Each value: native name; a trailing '*' marks an approximation.
# ---------------------------------------------------------------------------
INFILL = {
    #  canon          cura            prusa              orca
    "lines":        ("lines",        "rectilinear",     "rectilinear"),
    "grid":         ("grid",         "grid",            "grid"),
    "triangles":    ("triangles",    "triangles",       "triangles"),
    "trihexagon":   ("trihexagon",   "stars",           "tri-hexagon"),
    "cubic":        ("cubic",        "cubic",           "cubic"),
    "cubicsubdiv":  ("cubicsubdiv",  "adaptivecubic",   "adaptivecubic"),
    "tetrahedral":  ("tetrahedral",  "cubic*",          "cubic*"),
    "quarter_cubic": ("quarter_cubic", "cubic*",        "quartercubic"),
    "concentric":   ("concentric",   "concentric",      "concentric"),
    "zigzag":       ("zigzag",       "zigzag",          "zigzag"),
    "cross":        ("cross",        "gyroid*",         "gyroid*"),
    "cross_3d":     ("cross_3d",     "gyroid*",         "gyroid*"),
    "gyroid":       ("gyroid",       "gyroid",          "gyroid"),
    "lightning":    ("lightning",    "lightning",       "lightning"),
    "honeycomb":    ("honeycomb",    "honeycomb",       "honeycomb"),
    "octagon":      ("octagon",      "grid*",           "grid*"),
    "3dhoneycomb":  ("gyroid*",      "3dhoneycomb",     "3dhoneycomb"),
    "hilbertcurve": ("lines*",       "hilbertcurve",    "hilbertcurve"),
    "archimedeanchords": ("concentric*", "archimedeanchords", "archimedeanchords"),
    "octagramspiral": ("concentric*", "octagramspiral", "octagramspiral"),
    "supportcubic": ("cubicsubdiv*", "supportcubic",    "supportcubic"),
    "alignedrectilinear": ("lines*", "alignedrectilinear", "alignedrectilinear"),
    "crosshatch":   ("grid*",        "grid*",           "crosshatch"),
    "tpms":         ("gyroid*",      "gyroid*",         "tpmsd"),
    "line":         ("lines*",       "line",            "line"),
    "stars":        ("trihexagon",   "stars",           "tri-hexagon*"),
}
# extra native names that read as an existing canonical value
INFILL_ALIASES = {
    "prusa": {"rectilinear": "lines", "monotonic": "lines", "monotoniclines": "lines", "stars": "trihexagon"},
    "orca": {"rectilinear": "lines", "monotonic": "lines", "monotonicline": "lines", "tri-hexagon": "trihexagon",
             "quartercubic": "quarter_cubic", "tpmsfk": "tpms", "tpmsd": "tpms", "lateral-honeycomb": "honeycomb",
             "lateral-lattice": "grid", "lockedzag": "zigzag", "crosszag": "zigzag"},
    "cura": {},
}

SURFACE = {  # top/bottom pattern
    "lines":      ("lines",       "rectilinear",  "rectilinear"),
    "monotonic":  ("lines+mono",  "monotonic",    "monotonic"),
    "monotoniclines": ("lines+mono*", "monotoniclines", "monotonicline"),
    "concentric": ("concentric",  "concentric",   "concentric"),
    "zigzag":     ("zigzag",      "rectilinear*", "rectilinear*"),
    "alignedrectilinear": ("lines*", "alignedrectilinear", "alignedrectilinear"),
    "hilbertcurve": ("lines*",    "hilbertcurve", "hilbertcurve"),
    "archimedeanchords": ("concentric*", "archimedeanchords", "archimedeanchords"),
    "octagramspiral": ("concentric*", "octagramspiral", "octagramspiral"),
    "spiralinset": ("concentric*", "concentric*", "spiralinset"),
}

SUPPORT_PATTERN = {
    "lines":      ("lines",      "rectilinear",      "rectilinear"),
    "grid":       ("grid",       "rectilinear-grid", "rectilinear-grid"),
    "zigzag":     ("zigzag",     "rectilinear*",     "rectilinear*"),
    "triangles":  ("triangles",  "rectilinear-grid*", "rectilinear-grid*"),
    "concentric": ("concentric", "rectilinear*",     "rectilinear*"),
    "cross":      ("cross",      "rectilinear-grid*", "rectilinear-grid*"),
    "gyroid":     ("gyroid",     "honeycomb*",       "honeycomb*"),
    "honeycomb":  ("honeycomb",  "honeycomb",        "honeycomb"),
    "lightning":  ("lightning",  "rectilinear*",     "lightning"),
    "octagon":    ("octagon",    "rectilinear-grid*", "rectilinear-grid*"),
    "hollow":     ("lines*",     "rectilinear*",     "hollow"),
    "default":    ("zigzag*",    "rectilinear*",     "default"),
}

SEAM = {  # canon: cura, prusa, orca
    "back":    ("back",            "rear",    "back"),
    "nearest": ("shortest",        "nearest", "nearest"),
    "aligned": ("sharpest_corner", "aligned", "aligned"),
    "random":  ("random",          "random",  "random"),
}
SEAM_ALIASES = {"orca": {"aligned_back": "back"}, "prusa": {}, "cura": {}}

FLAVOR = {  # canon: cura, prusa/orca
    "marlin2":        ("RepRap (Marlin/Sprinter)", "marlin2"),
    "marlin":         ("RepRap (Marlin/Sprinter)", "marlin"),
    "klipper":        ("RepRap (Marlin/Sprinter)*", "klipper"),
    "reprapfirmware": ("RepRap (RepRap)", "reprapfirmware"),
    "reprap":         ("RepRap (Marlin/Sprinter)", "reprap"),
    "repetier":       ("Repetier", "repetier"),
    "smoothie":       ("RepRap (Marlin/Sprinter)*", "smoothie"),
    "mach3":          ("MACH3", "mach3"),
    "makerware":      ("Makerbot", "makerware"),
    "volumetric":     ("RepRap (Volumetric)", "marlin2*"),
    "ultigcode":      ("UltiGCode", "marlin2*"),
    "griffin":        ("Griffin", "marlin2*"),
    "bfb":            ("BFB", "marlin2*"),
    "bambu":          ("BambuLab", "marlin2*"),
    "teacup":         ("RepRap (Marlin/Sprinter)*", "teacup"),
    "sailfish":       ("Makerbot*", "sailfish"),
    "machinekit":     ("RepRap (Marlin/Sprinter)*", "machinekit"),
    "no-extrusion":   ("RepRap (Marlin/Sprinter)*", "no-extrusion"),
    "cheetah":        ("Cheetah", "marlin2*"),
}
CURA_FLAVOR_TO_CANON = {
    "RepRap (Marlin/Sprinter)": "marlin2", "RepRap (Volumetric)": "volumetric",
    "RepRap (RepRap)": "reprapfirmware", "UltiGCode": "ultigcode", "Griffin": "griffin",
    "Makerbot": "makerware", "BFB": "bfb", "MACH3": "mach3", "Repetier": "repetier",
    "BambuLab": "bambu", "Cheetah": "cheetah",
}

SLICERS = ("cura", "prusa", "orca")


def enum_to_native(table: Dict[str, tuple], canon: Optional[str], slicer: str) -> Tuple[Optional[str], bool]:
    """(native value, is_approximation)."""
    if canon is None or canon not in table:
        return None, False
    idx = {"cura": 0, "prusa": 1, "orca": 2}[slicer]
    if len(table[canon]) == 2:  # FLAVOR has (cura, prusa/orca)
        idx = 0 if slicer == "cura" else 1
    nat = table[canon][idx]
    return nat.rstrip("*"), nat.endswith("*")


def enum_to_canon(table: Dict[str, tuple], native: Optional[str], slicer: str,
                  aliases: Optional[Dict[str, Dict[str, str]]] = None) -> Optional[str]:
    if native is None:
        return None
    if aliases and native in aliases.get(slicer, {}):
        return aliases[slicer][native]
    idx = {"cura": 0, "prusa": 1, "orca": 2}[slicer]
    for canon, nats in table.items():
        i = idx if len(nats) == 3 else (0 if slicer == "cura" else 1)
        if nats[i] == native:  # exact (non-approximate) matches only
            return canon
    return native if native in table else None


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class Report:
    source: str = ""
    target: str = ""
    converted: Dict[str, Any] = field(default_factory=dict)          # canon -> value
    approximations: List[str] = field(default_factory=list)
    not_converted: Dict[str, Any] = field(default_factory=dict)      # native source key -> value
    target_missing: List[str] = field(default_factory=list)          # canon keys target can't express
    notes: List[str] = field(default_factory=list)
    gcode_notes: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)

    def approx(self, msg: str):
        if msg not in self.approximations:
            self.approximations.append(msg)

    def note(self, msg: str):
        if msg not in self.notes:
            self.notes.append(msg)

    def to_text(self) -> str:
        lines = [f"SlicerSwap conversion report: {self.source} -> {self.target}", ""]
        if self.files:
            lines += ["Files written:"] + [f"  {f}" for f in self.files] + [""]
        if self.notes:
            lines += ["Read this first:"] + [f"  - {n}" for n in self.notes] + [""]
        lines += [f"Converted settings ({len(self.converted)}):"]
        for k in sorted(self.converted):
            lines.append(f"  {k:32s} = {fmt_value(self.converted[k])}")
        lines.append("")
        if self.approximations:
            lines += [f"Approximated ({len(self.approximations)}) - check these:"] + [f"  ~ {a}" for a in self.approximations] + [""]
        if self.target_missing:
            lines += [f"No equivalent in {self.target} ({len(self.target_missing)}):"] + [f"  - {m}" for m in self.target_missing] + [""]
        if self.gcode_notes:
            lines += ["Start/end G-code:"] + [f"  - {g}" for g in self.gcode_notes] + [""]
        if self.not_converted:
            lines += [f"Source settings not converted ({len(self.not_converted)}):"]
            for k in sorted(self.not_converted):
                lines.append(f"  {k:40s} = {fmt_value(self.not_converted[k])[:60]}")
            lines.append("")
        return "\n".join(lines)


def fmt_value(v: Any) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        s = f"{v:.4f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    if isinstance(v, str) and "\n" in v:
        return v.splitlines()[0] + f" ... ({len(v.splitlines())} lines)"
    return str(v)
