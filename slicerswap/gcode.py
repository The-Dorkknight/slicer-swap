# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Translate start/end G-code placeholders between Cura and Prusa/Orca macro syntax.

Cura:          {material_print_temperature}   {material_print_temperature, 0}
Prusa / Orca:  [first_layer_temperature]       {first_layer_temperature[initial_extruder]}
Only plain variable references are rewritten. Conditionals and arithmetic
({if ...}, {a+b}) are left alone and reported for manual review.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from . import mapping

# canon -> (cura key, prusa key, orca key)
VARS: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = {
    "nozzle_temp": ("material_print_temperature", "temperature", "nozzle_temperature"),
    "nozzle_temp_first_layer": ("material_print_temperature_layer_0", "first_layer_temperature", "nozzle_temperature_initial_layer"),
    "bed_temp": ("material_bed_temperature", "bed_temperature", "bed_temperature"),
    "bed_temp_first_layer": ("material_bed_temperature_layer_0", "first_layer_bed_temperature", "bed_temperature_initial_layer_single"),
    "standby_temp": ("material_standby_temperature", "idle_temperature", None),
    "initial_extruder": ("initial_extruder_nr", "initial_extruder", "initial_extruder"),
    "filament_type": ("material_type", "filament_type", "filament_type"),
    "max_height": ("machine_height", "max_print_height", "printable_height"),
    "layer_height": ("layer_height", "layer_height", "layer_height"),
    "first_layer_height": ("layer_height_0", "first_layer_height", "initial_layer_print_height"),
    "nozzle_diameter": ("machine_nozzle_size", "nozzle_diameter", "nozzle_diameter"),
    "filament_diameter": ("material_diameter", "filament_diameter", "filament_diameter"),
    "speed_travel": ("speed_travel", "travel_speed", "travel_speed"),
    "retract_length": ("retraction_amount", "retract_length", "retraction_length"),
    "print_time": ("print_time", None, None),
    "date": ("date", "timestamp*", "timestamp*"),
    "bed_x": ("machine_width", "{print_bed_size[0]}", "{print_bed_size[0]}"),
    "bed_y": ("machine_depth", "{print_bed_size[1]}", "{print_bed_size[1]}"),
}
# Prusa/Orca-only names worth recognising when going to Cura
EXTRA_NATIVE = {
    "prusa": {"first_layer_bed_temperature": "bed_temp_first_layer", "bed_temperature": "bed_temp",
              "temperature": "nozzle_temp", "first_layer_temperature": "nozzle_temp_first_layer",
              "current_extruder": "initial_extruder"},
    "orca": {"bed_temperature_initial_layer": "bed_temp_first_layer", "bed_temperature_initial_layer_single": "bed_temp_first_layer",
             "hot_plate_temp_initial_layer": "bed_temp_first_layer", "hot_plate_temp": "bed_temp",
             "textured_plate_temp_initial_layer": "bed_temp_first_layer", "textured_plate_temp": "bed_temp",
             "cool_plate_temp_initial_layer": "bed_temp_first_layer", "cool_plate_temp": "bed_temp",
             "eng_plate_temp_initial_layer": "bed_temp_first_layer", "eng_plate_temp": "bed_temp",
             "initial_tool": "initial_extruder", "current_extruder": "initial_extruder"},
}
IDX = {"cura": 0, "prusa": 1, "orca": 2}

_DATA = os.path.join(os.path.dirname(__file__), "data")
_TYPES: Dict[str, Dict[str, dict]] = {}


def native_types(slicer: str) -> Dict[str, dict]:
    if slicer not in _TYPES:
        with open(os.path.join(_DATA, f"{slicer}_keys.json"), encoding="utf-8") as fh:
            _TYPES[slicer] = json.load(fh)
    return _TYPES[slicer]


_VECTOR_TYPES = {"coFloats", "coInts", "coBools", "coStrings", "coPercents", "coFloatsOrPercents"}


def _is_vector(slicer: str, key: str) -> bool:
    return native_types(slicer).get(key, {}).get("type", "") in _VECTOR_TYPES


def _canon_from_native(slicer: str, key: str) -> Optional[str]:
    i = IDX[slicer]
    for canon, keys in VARS.items():
        if keys[i] == key:
            return canon
    if key in EXTRA_NATIVE.get(slicer, {}):
        return EXTRA_NATIVE[slicer][key]
    for row in mapping.ROWS:
        if row[3 + i] == key:
            return row[0]
    return None


def _native_from_canon(slicer: str, canon: str) -> Optional[str]:
    if canon in VARS:
        k = VARS[canon][IDX[slicer]]
        if k:
            return k
    row = mapping.ROW_BY_CANON.get(canon)
    if row:
        return row[3 + IDX[slicer]]
    return None


_PRINT_KEYS = {r[5] for r in mapping.ROWS if r[1] == "print" and r[5]}


def _render(slicer: str, key: str) -> str:
    key = key.rstrip("*")
    if slicer == "cura":
        return "{" + key + "}"
    if key.startswith("{"):
        return key  # already an expression
    if _is_vector(slicer, key):
        # Orca stores some process values as per-nozzle-variant arrays: index 0
        idx = "0" if (slicer == "orca" and key in _PRINT_KEYS) else "initial_extruder"
        return "{" + key + "[" + idx + "]}"
    return "[" + key + "]"


_CURA_RE = re.compile(r"\{\s*([A-Za-z_][A-Za-z_0-9]*)\s*(?:,\s*(-?\d+|initial_extruder_nr))?\s*\}")
_MACRO_SQ = re.compile(r"\[([A-Za-z_][A-Za-z_0-9]*?)(?:_(\d+))?\]")
_MACRO_CURLY = re.compile(r"\{\s*([A-Za-z_][A-Za-z_0-9]*)\s*(?:\[\s*([A-Za-z_0-9]+)\s*\])?\s*\}")
_MACRO_COMPLEX = re.compile(r"\{[^{}]*(?:\bif\b|\belsif\b|\belse\b|\bendif\b|\blocal\b|\bglobal\b|[+\-*/<>=!&|?(])[^{}]*\}")


_IDENT = re.compile(r"(?<![\w.\"'])([A-Za-z_][A-Za-z_0-9]*)(\s*\[[^\[\]]*\])?")
_KEYWORDS = {"if", "elsif", "else", "endif", "and", "or", "not", "true", "false", "local", "global", "is_nil",
             "min", "max", "int", "round", "digits", "zdigits", "regex_replace", "one_of", "interpolate_table",
             "random", "filament_preset", "print_preset", "printer_preset", "position", "empty", "size", "repeat"}


def _macro_to_macro(text: str, src: str, dst: str, unknown: List[str]) -> str:
    """Prusa <-> Orca: rename identifiers everywhere inside {...} and [...] macros."""
    st, dt = native_types(src), native_types(dst)

    def rename(name: str, index: Optional[str]) -> str:
        if name in _KEYWORDS:
            return name + (index or "")
        canon = _canon_from_native(src, name)
        nat = _native_from_canon(dst, canon) if canon else None
        if nat == "bed_temperature_initial_layer_single" and dst == "orca":
            nat = "bed_temperature_initial_layer"  # keep vector shape inside expressions
        if not nat:
            if name in st and name not in dt:
                unknown.append(name)
            return name + (index or "")
        nat = nat.rstrip("*")
        if _is_vector(src, name) and not _is_vector(dst, nat):
            return nat  # drop the index
        if not _is_vector(src, name) and _is_vector(dst, nat) and index is None:
            return nat + "[initial_extruder]"
        return nat + (index or "")

    def curly(m: re.Match) -> str:
        body = m.group(1)
        parts = re.split(r'("(?:[^"\\]|\\.)*")', body)  # leave string literals alone
        for i in range(0, len(parts), 2):
            parts[i] = _IDENT.sub(lambda mm: rename(mm.group(1), mm.group(2)), parts[i])
        return "{" + "".join(parts) + "}"

    def square(m: re.Match) -> str:
        name = m.group(1)
        if _canon_from_native(src, name) is None and re.match(r".*_\d+$", name):
            base = re.sub(r"_\d+$", "", name)
            if _canon_from_native(src, base):
                name = base
        if name in _KEYWORDS:
            return m.group(0)
        canon = _canon_from_native(src, name)
        nat = _native_from_canon(dst, canon) if canon else None
        if not nat:
            if name in st and name not in dt:
                unknown.append(name)
            return m.group(0)
        return _render(dst, nat)

    out = re.sub(r"\{([^{}]*)\}", curly, text)
    out = re.sub(r"\[([A-Za-z_][A-Za-z_0-9]*)\]", square, out)
    return out


def _literal(v: Any) -> Optional[str]:
    """A value as it can be pasted into G-code, or None if it is not a plain scalar."""
    if isinstance(v, (list, tuple)):
        v = v[0] if len(v) == 1 else None
    if v is None or isinstance(v, (dict, list, tuple)):
        return None
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        s = f"{v:.4f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-0") else "0"
    s = str(v).strip()
    if not s or "\n" in s or len(s) > 40 or s.endswith("%") or "," in s:
        return None
    return s


def translate(text: str, src: str, dst: str, values: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """Return (translated text, notes).

    values: the source slicer's settings. A plain placeholder with no equivalent in the
    target is replaced by its current value, because a placeholder the target slicer does
    not know makes it refuse to slice (Orca/Prusa) or ends up verbatim in the G-code (Cura).
    """
    notes: List[str] = []
    if not text or src == dst:
        return text or "", notes
    unknown: List[str] = []
    inlined: Dict[str, str] = {}
    values = values or {}

    def map_key(key: str) -> Optional[str]:
        canon = _canon_from_native(src, key)
        if canon is None:
            return None
        return _native_from_canon(dst, canon)

    def inline(key: str) -> Optional[str]:
        lit = _literal(values.get(key)) if key in values else None
        if lit is not None:
            inlined[key] = lit
        return lit

    if src == "cura":
        def rep(m: re.Match) -> str:
            nat = map_key(m.group(1))
            if not nat:
                lit = inline(m.group(1))
                if lit is not None:
                    return lit
                unknown.append(m.group(1))
                return m.group(0)
            return _render(dst, nat)
        out = _CURA_RE.sub(rep, text)
    elif dst != "cura":
        out = _macro_to_macro(text, src, dst, unknown)
        # plain placeholders the target lacks: inline the value
        dt = native_types(dst)
        for key in sorted(set(unknown)):
            if key in dt:
                continue
            lit = _literal(values.get(key)) if key in values else None
            if lit is None:
                continue
            new, n = re.subn(r"\[" + re.escape(key) + r"\]|\{\s*" + re.escape(key) + r"\s*(?:\[\s*\w+\s*\])?\s*\}", lit, out)
            if n:
                out = new
                inlined[key] = lit
                if not re.search(r"\b" + re.escape(key) + r"\b", out):
                    unknown[:] = [u for u in unknown if u != key]
    else:
        complex_hits = _MACRO_COMPLEX.findall(text)
        if complex_hits:
            notes.append(f"{len(complex_hits)} macro expression(s) with logic/maths can't be expressed in Cura; "
                         f"left unchanged, e.g. {complex_hits[0][:60]}")
        masks: List[str] = []

        def mask(m: re.Match) -> str:
            masks.append(m.group(0))
            return f"\x00{len(masks) - 1}\x00"

        def simple(m: re.Match) -> str:
            key = m.group(1)
            nat = map_key(key)
            if not nat and re.match(r".*_\d+$", key):
                nat = map_key(re.sub(r"_\d+$", "", key))
            if not nat:
                if key in native_types(src) or m.group(0).startswith("{"):
                    lit = inline(key)
                    if lit is not None:
                        return lit
                    unknown.append(key)
                return m.group(0)
            return _render(dst, nat)
        tmp = _MACRO_COMPLEX.sub(mask, text)
        tmp = _MACRO_CURLY.sub(simple, tmp)
        tmp = re.sub(r"\[([A-Za-z_][A-Za-z_0-9]*)\]", simple, tmp)
        out = re.sub("\x00(\\d+)\x00", lambda m: masks[int(m.group(1))], tmp)
    if inlined:
        notes.append("Placeholders the target slicer does not have were replaced by their current value: " +
                     ", ".join(f"{k} = {v}" for k, v in sorted(inlined.items())[:12]) +
                     (" ..." if len(inlined) > 12 else ""))
    if unknown:
        uniq = sorted(set(unknown))
        notes.append("Placeholders with no equivalent (left as-is; edit by hand, the target may refuse to slice): " +
                     ", ".join(uniq[:15]) + (" ..." if len(uniq) > 15 else ""))
    return out, notes
