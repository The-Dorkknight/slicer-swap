# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Maintainer tool: refresh the bundled reference data from upstream checkouts.

Usage (needs git checkouts of the upstream projects):
    python3 tools/update_data.py --cura ~/src/Cura --materials ~/src/fdm_materials \
        --prusa ~/src/PrusaSlicer --orca ~/src/OrcaSlicer

--prusa / --orca take either a checkout or a folder that directly holds
PrintConfig.cpp and Preset.cpp (handy for a release tag).

What it regenerates in slicerswap/data/:
  cura/definitions, cura/extruders   copied from Cura resources (LGPLv3)
  cura/containers.json.gz            every quality, intent and variant profile (LGPLv3), compacted
  cura/generic_materials.json        generic material values incl. per-printer overrides (fdm_materials, CC0)
  prusa_keys.json, orca_keys.json    option names, types, enum values and which preset each belongs to
Then run the tests: python3 -m unittest discover -s tests
"""
import argparse
import configparser
import glob
import gzip
import json
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(os.path.dirname(HERE), "slicerswap", "data")
# per-axis options are created in a loop in PrintConfig.cpp ("machine_max_speed_" + axis.name), so list them here
AXIS_PREFIXES = {"prusa": ("machine_max_feedrate_", "machine_max_acceleration_", "machine_max_jerk_"),
                 "orca": ("machine_max_speed_", "machine_max_acceleration_", "machine_max_jerk_")}
EXTRA = {
    "prusa": {k: "coFloats" for k in ("filament_retract_length", "filament_retract_lift", "filament_retract_speed",
                                     "filament_deretract_speed", "filament_retract_restart_extra",
                                     "filament_retract_before_travel", "filament_retract_lift_above",
                                     "filament_retract_lift_below")},
    "orca": {k: "coFloats" for k in ("filament_retraction_length", "filament_z_hop", "filament_retraction_speed",
                                    "filament_deretraction_speed", "filament_retract_restart_extra",
                                    "filament_retraction_minimum_travel", "filament_retract_lift_above",
                                    "filament_retract_lift_below")},
}
EXTRA["prusa"]["filament_retract_layer_change"] = "coBools"
EXTRA["orca"]["filament_retract_when_changing_layer"] = "coBools"

# fdm_material <setting key="..."> -> Cura setting (from Cura's XmlMaterialProfile plugin)
MATERIAL_KEYS = {
    "print temperature": "default_material_print_temperature",
    "heated bed temperature": "default_material_bed_temperature",
    "standby temperature": "material_standby_temperature",
    "print cooling": "cool_fan_speed",
    "retraction amount": "retraction_amount",
    "retraction speed": "retraction_speed",
    "adhesion tendency": "material_adhesion_tendency",
    "surface energy": "material_surface_energy",
    "build volume temperature": "build_volume_temperature",
}


def _read(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _option_lists(preset_cpp):
    """{key: 'print'|'filament'|'printer'} from the s_Preset_*_options lists."""
    src = _read(preset_cpp)
    out = {}
    for var, sec in (("s_Preset_print_options", "print"), ("s_Preset_filament_options", "filament"),
                     ("s_Preset_machine_limits_options", "printer"), ("s_Preset_printer_options", "printer")):
        m = re.search(var + r"\s*\{(.*?)\};", src, re.S)
        if not m:
            continue
        body = re.sub(r"//[^\n]*", "", m.group(1))
        for k in re.findall(r'"([a-z_0-9]+)"', body):
            out.setdefault(k, sec)
    return out


def dump_keys(cpp_path, preset_cpp, slicer):
    src = _read(cpp_path)
    secs = _option_lists(preset_cpp) if preset_cpp else {}
    out = {}
    for m in re.finditer(r'add\("([a-z_0-9]+)",\s*(co[A-Za-z]+)\)', src):
        end = src.find('add("', m.end())
        blk = src[m.end(): end if end > 0 else None]
        ev = re.findall(r'\{\s*"([a-zA-Z0-9_\-() /]+)"\s*,\s*(?:L|_L|_u8L)?\(?"', blk)
        ev2 = re.findall(r'enum_values\.(?:push_back|emplace_back)\("([^"]+)"\)', blk)
        out[m.group(1)] = {"type": m.group(2), "enum": ev or ev2 or None}
    for prefix in AXIS_PREFIXES[slicer]:
        if ('add("' + prefix + '" +') not in src:
            raise SystemExit(f"{slicer}: expected per-axis option {prefix}* not found in PrintConfig.cpp")
        for axis in "xyze":
            out.setdefault(prefix + axis, {"type": "coFloats", "enum": None})
    for k, t in EXTRA[slicer].items():
        out.setdefault(k, {"type": t, "enum": None})
    for k, v in out.items():
        sec = secs.get(k)
        if sec is None:
            if k.startswith(("machine_", "retract", "deretract", "nozzle_", "extruder_", "wipe", "z_hop", "printable_")):
                sec = "printer"
            elif k.startswith("filament_"):
                sec = "filament"
        v["sec"] = sec
    return out


def find_source(root, name):
    direct = os.path.join(root, name)
    if os.path.isfile(direct):
        return direct
    hits = glob.glob(os.path.join(root, "src", "**", name), recursive=True)
    return max(hits, key=os.path.getsize) if hits else None


def commit(root):
    try:
        return subprocess.check_output(["git", "-C", root, "log", "-1", "--format=%H %cd"], text=True,
                                       stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def read_container(path):
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str
    cp.read(path, encoding="utf-8")
    g = dict(cp.items("general")) if cp.has_section("general") else {}
    m = dict(cp.items("metadata")) if cp.has_section("metadata") else {}
    v = dict(cp.items("values")) if cp.has_section("values") else {}
    return g, m, v


def cura_containers(res):
    """Every quality / intent / variant container, compacted to one list."""
    out = []
    for sub in ("quality", "intent", "variants"):
        for f in sorted(glob.glob(os.path.join(res, sub, "**", "*.inst.cfg"), recursive=True)):
            try:
                g, m, v = read_container(f)
            except Exception:
                continue
            rec = {"t": m.get("type", sub), "d": g.get("definition"), "n": g.get("name"),
                   "id": os.path.basename(f)[:-9], "v": v}
            for src, dst in (("quality_type", "q"), ("material", "m"), ("variant", "var"),
                             ("intent_category", "i"), ("hardware_type", "hw")):
                if src in m:
                    rec[dst] = m[src]
            if m.get("global_quality", "").lower() == "true":
                rec["g"] = 1
            out.append(rec)
    return out


def materials(root):
    ns = {"m": "http://www.ultimaker.com/material", "cura": "http://www.ultimaker.com/cura"}

    def settings(node):
        out = {}
        for st in node.findall("m:setting", ns):
            key = MATERIAL_KEYS.get(st.get("key"))
            if key and st.text and st.text.strip():
                try:
                    out[key] = float(st.text)
                except ValueError:
                    pass
        for st in node.findall("cura:setting", ns):
            if st.get("key") and st.text:
                out[st.get("key")] = st.text.strip()
        return out
    out = {}
    for f in sorted(glob.glob(os.path.join(root, "generic_*.xml.fdm_material"))):
        r = ET.parse(f).getroot()
        base = settings(r.find("m:settings", ns))
        machines = {}
        for mach in r.findall("m:settings/m:machine", ns):
            s = settings(mach)
            if not s:
                continue
            for ident in mach.findall("m:machine_identifier", ns):
                pid = (ident.get("product") or "").lower().replace(" ", "_")
                if pid:
                    machines.setdefault(pid, {}).update(s)
        out[os.path.basename(f).split(".xml")[0]] = {
            "material": r.find("m:metadata/m:name/m:material", ns).text,
            "diameter": float(r.find("m:properties/m:diameter", ns).text),
            "print_temp": base.get("default_material_print_temperature", 0.0),
            "bed_temp": base.get("default_material_bed_temperature", 0.0),
            "settings": base, "machines": machines}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cura")
    ap.add_argument("--materials")
    ap.add_argument("--prusa")
    ap.add_argument("--orca")
    a = ap.parse_args()
    if a.cura:
        res = os.path.join(a.cura, "resources")
        for sub in ("definitions", "extruders"):
            dst = os.path.join(DATA, "cura", sub)
            shutil.rmtree(dst, ignore_errors=True)
            os.makedirs(dst)
            for f in glob.glob(os.path.join(res, sub, "*.def.json")):
                shutil.copy2(f, dst)
        recs = cura_containers(res)
        raw = json.dumps(recs, separators=(",", ":"), sort_keys=True).encode("utf-8")
        with open(os.path.join(DATA, "cura", "containers.json.gz"), "wb") as fh:
            with gzip.GzipFile(fileobj=fh, mode="wb", mtime=0) as gz:
                gz.write(raw)
        with open(os.path.join(DATA, "cura", "UPSTREAM_COMMIT.txt"), "w") as fh:
            fh.write(commit(a.cura) + "\n")
        print(f"cura: {len(recs)} quality/intent/variant containers")
    if a.materials:
        with open(os.path.join(DATA, "cura", "generic_materials.json"), "w") as fh:
            json.dump(materials(a.materials), fh, indent=1, sort_keys=True)
    for slicer, root in (("prusa", a.prusa), ("orca", a.orca)):
        if root:
            pc = find_source(root, "PrintConfig.cpp")
            if not pc:
                raise SystemExit(f"PrintConfig.cpp not found under {root}")
            keys = dump_keys(pc, find_source(root, "Preset.cpp"), slicer)
            with open(os.path.join(DATA, f"{slicer}_keys.json"), "w") as fh:
                json.dump(keys, fh, indent=0, sort_keys=True)
            n = sum(1 for v in keys.values() if v.get("sec"))
            print(f"{slicer}: {len(keys)} options ({n} with a preset type) from {commit(root)}")


if __name__ == "__main__":
    main()
