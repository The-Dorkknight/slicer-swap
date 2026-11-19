# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
"""Top-level conversion: detect the input format, read, convert, write, report."""
from __future__ import annotations

import json
import configparser
import os
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import cura_engine as ce
from . import cura_fmt, slicer_fmt
from .mapping import ROWS, Report

FORMATS = ("cura", "prusa", "orca")
LABEL = {"cura": "Cura", "prusa": "PrusaSlicer", "orca": "OrcaSlicer"}


@dataclass
class Options:
    target: str = "orca"
    source: Optional[str] = None            # auto-detect when None
    name: Optional[str] = None
    outdir: str = "."
    cura_machine: Optional[str] = None      # target Cura machine (and source machine for Cura input)
    cura_material: Optional[str] = None     # e.g. generic_pla_175 (Cura input only)
    cura_resources: Optional[str] = None    # an installed Cura's resources folder (optional)
    orca_profiles: List[str] = field(default_factory=list)  # extra folders to resolve Orca 'inherits'
    inherits: Dict[str, str] = field(default_factory=dict)  # print/filament/printer -> system preset name
    overrides: Dict[str, Any] = field(default_factory=dict)  # canonical key -> value forced by the user


def detect(paths: List[str]) -> str:
    """Guess the slicer of the input file(s)."""
    p = paths[0]
    low = p.lower()
    if low.endswith((".curaprofile", ".inst.cfg")):
        return "cura"
    if low.endswith((".orca_printer", ".orca_filament")):
        return "orca"
    if zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as zf:
            names = zf.namelist()
        if any(n.startswith("Cura/") for n in names):
            return "cura"
        if any(n.lower().endswith("slic3r_pe.config") for n in names):
            return "prusa"
        if any(n.endswith("project_settings.config") for n in names) or any(n.endswith(".json") for n in names):
            return "orca"
        # .curaprofile without the extension: zip of inst.cfg
        return "cura"
    if low.endswith(".json"):
        return "orca"
    with open(p, encoding="utf-8", errors="replace") as fh:
        head = fh.read(4000)
    if "[general]" in head and "[values]" in head:
        return "cura"
    if head.lstrip().startswith("{"):
        return "orca"
    return "prusa"


def _no_settings(paths: List[str], what: str) -> ValueError:
    names = ", ".join(os.path.basename(p) for p in paths)
    return ValueError(f"No {what} settings found in {names}. Is it empty, or a different kind of file? "
                      f"Nothing was written.")


def read_canonical(paths: List[str], opts: Options, res: Optional[ce.Resources] = None):
    """Read the input file(s). A damaged or empty file gives ValueError with the file name, never a bare
    parser error or a profile made of defaults alone."""
    try:
        return _read_canonical(paths, opts, res)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        names = ", ".join(os.path.basename(p) for p in paths)
        raise ValueError(f"Could not read {names}: it is damaged or not a slicer profile ({str(exc)[:120]}). "
                         f"Nothing was written.") from None
    except (ValueError, FileNotFoundError):
        raise
    except (UnicodeDecodeError, KeyError, TypeError, AttributeError, IndexError, zipfile.BadZipFile,
            configparser.Error, RecursionError, OSError) as exc:
        names = ", ".join(os.path.basename(p) for p in paths)
        raise ValueError(f"Could not read {names}: it is damaged or not a slicer profile "
                         f"({exc.__class__.__name__}: {str(exc)[:120]}). Nothing was written.") from None


def _read_canonical(paths: List[str], opts: Options, res: Optional[ce.Resources] = None):
    src = opts.source or detect(paths)
    rep = Report(source=LABEL[src])
    if src == "cura":
        res = res or ce.Resources(opts.cura_resources)
        if len(paths) > 1:
            rep.note("Cura input: only the first file is read.")
        try:
            prof = ce.read_cura_file(paths[0])
        except UnicodeDecodeError:
            raise ValueError(f"Could not read {os.path.basename(paths[0])}: it is not a Cura profile "
                             f"(not text). Nothing was written.") from None
        if not (prof.global_changes or prof.extruder_changes or prof.machine_changes or prof.quality_type):
            raise _no_settings(paths[:1], "Cura")
        C, rep2, _rc = cura_fmt.read(paths[0], res, machine=opts.cura_machine, material=opts.cura_material)
        rep2.notes = rep.notes + rep2.notes
        rep = rep2
    elif src == "prusa":
        cfg = slicer_fmt.read_prusa(paths, rep)
        if not any(r[4] and r[4] in cfg for r in ROWS):
            raise _no_settings(paths, "PrusaSlicer")
        C = slicer_fmt.to_canon("prusa", cfg, rep, name=_default_name(paths))
    else:
        cfg = slicer_fmt.read_orca(paths, rep, opts.orca_profiles)
        if not isinstance(cfg, dict) or not any(r[5] and r[5] in cfg for r in ROWS):
            raise _no_settings(paths, "OrcaSlicer")
        C = slicer_fmt.to_canon("orca", cfg, rep, name=cfg.get("name") or _default_name(paths))
    for k, v in opts.overrides.items():
        if v is not None and v != "":
            C[k] = v
            rep.note(f"{k} set by you to {v}")
    return src, C, rep


def convert(paths: List[str], opts: Options) -> Report:
    if not paths:
        raise ValueError("No input files")
    for p in paths:
        if not os.path.isfile(p):
            raise FileNotFoundError(p)
    res = None
    if opts.source == "cura" or opts.target == "cura" or detect(paths) == "cura":
        res = ce.Resources(opts.cura_resources)
    src, C, rep = read_canonical(paths, opts, res)
    tgt = opts.target
    rep.target = LABEL[tgt]
    if src == tgt:
        rep.note(f"Source and target are both {LABEL[src]}; writing a normalised copy.")
    name = opts.name or f"{C.get('name', 'Imported')} ({LABEL[src]})"
    if tgt == "cura":
        machine = opts.cura_machine or "fdmprinter"
        if not opts.cura_machine:
            rep.note("No Cura printer chosen; the profile targets the generic 'Custom FFF printer'. "
                     "Pick your printer for a profile Cura will accept on it.")
        files = cura_fmt.write(C, name, opts.outdir, res, machine, rep, src)
    else:
        native = slicer_fmt.from_canon(tgt, C, rep, src)
        if tgt == "prusa":
            files = slicer_fmt.write_prusa(native, name, opts.outdir, opts.inherits)
            rep.note("PrusaSlicer: File > Import > Import Config Bundle (adds three presets), "
                     "or Import Config for the flat .ini.")
        else:
            files = slicer_fmt.write_orca(native, name, opts.outdir, opts.inherits)
            rep.note("OrcaSlicer: File > Import > Import Configs, select the three .json files "
                     "(machine first). Settings not written fall back to Orca defaults"
                     + (" or the inherited preset." if opts.inherits else "."))
    rep.files = files
    report_path = os.path.join(opts.outdir, slicer_fmt._safe(name) + ".report.txt")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(rep.to_text())
    rep.files.append(report_path)
    return rep


def _default_name(paths: List[str]) -> str:
    base = os.path.basename(paths[0])
    for ext in (".inst.cfg", ".curaprofile", ".ini", ".json", ".3mf", ".orca_printer", ".orca_filament", ".zip"):
        if base.lower().endswith(ext):
            return base[: -len(ext)]
    return os.path.splitext(base)[0]
