# Third-party material

SlicerSwap's own code is covered by the PolyForm Noncommercial License 1.0.0 (see LICENSE.md). That licence covers only Matthew Armstrong's code. Everything below keeps its own licence.

| Material | Where | Licence |
|---|---|---|
| Cura setting definitions and extruder definitions, © Ultimaker B.V. and contributors ([Ultimaker/Cura](https://github.com/Ultimaker/Cura)) | `slicerswap/data/cura/definitions`, `extruders` | LGPL-3.0-or-later; full texts in `slicerswap/data/cura/LICENSE-LGPL-3.0.txt` and `LICENSE-GPL-3.0.txt`. Unmodified copies; replace them freely with files from any Cura version. |
| Cura quality, intent and nozzle (variant) profiles, same source | `slicerswap/data/cura/containers.json.gz` | LGPL-3.0-or-later. The values of those files, repacked into one JSON file by `tools/update_data.py` (the script is the corresponding source for the repacking; run it on a Cura checkout to rebuild or replace the file). |
| Generic material settings extracted from [Ultimaker/fdm_materials](https://github.com/Ultimaker/fdm_materials) | `slicerswap/data/cura/generic_materials.json` | CC0 1.0 |
| Option names, types and enum values of PrusaSlicer 2.9.6 ([prusa3d/PrusaSlicer](https://github.com/prusa3d/PrusaSlicer)) and OrcaSlicer ([SoftFever/OrcaSlicer](https://github.com/SoftFever/OrcaSlicer)) | `slicerswap/data/prusa_keys.json`, `orca_keys.json` | Lists of configuration key names for file-format interoperability; no source code is copied. Both programs are AGPL-3.0. |
| Short excerpts of two log files written by Cura 5.13.0 (a normal start and a crashed start) | `tests/data/cura_log_good_start.txt`, `cura_log_crashed_start.txt` | Program output recorded for a test; no Cura code. |
| A small Cura printer set-up (one Creality Ender-3) saved by Cura 5.13 | `tests/data/cura_ender3_printer.slicerpack` | Configuration values written by Cura for a test; no Cura code. |

Format knowledge (where each program keeps its settings, Cura's container and package layout, preset file rules) was taken from reading Cura's, Uranium's, PrusaSlicer's and OrcaSlicer's public source code and from running the programs.

The exact upstream commit of the Cura data is in `slicerswap/data/cura/UPSTREAM_COMMIT.txt`.

SlicerSwap is not affiliated with, endorsed by or supported by UltiMaker, Prusa Research, the OrcaSlicer project or Bambu Lab. Product names are used only to say which programs and file formats are supported.
