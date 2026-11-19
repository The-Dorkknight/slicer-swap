# How SlicerSwap works

**WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN**

## What it reads, writes and never does

- **Reads** the settings folders of the slicers it finds (table below), the profile files you give it, and an installed Cura's `resources` folder if one is found.
- **Writes** only when you ask it to:
  - *Convert → save in a folder*: new files in the folder you choose.
  - *Convert → put straight into*, *Restore*, *Plug-ins*: files inside that slicer's settings folder (exactly which ones is listed below and shown in the window afterwards).
  - *Back up*: the one `.slicerpack` file you name.
  - Its own files: `~/.config/slicerswap/disclaimer_accepted_0.2`, and safety copies in `~/.local/share/slicerswap/safety-copies` (Windows `%LOCALAPPDATA%\slicerswap`, macOS `~/Library/Application Support/slicerswap`).
- **Never** changes the profile files you convert from, never deletes anything from a slicer's folder (a removed plug-in folder is moved aside), never overwrites a preset when installing (it picks a new name), never uses the network, and never runs code from a profile, backup or plug-in.
- **Start Cura** on the Plug-ins tab starts the Cura program it finds (newest AppImage in your home, Applications, Downloads or Desktop folder, a Flatpak, or `cura` on the path; Program Files on Windows; Applications on macOS). That is the only program SlicerSwap ever starts.

## Where each slicer keeps its settings

| Slicer | Linux | Windows | macOS |
|---|---|---|---|
| Cura (one folder set per version, e.g. `5.13`) | `~/.config/cura/<ver>` (preferences, scripts) and `~/.local/share/cura/<ver>` (printers, profiles, plug-ins, log) | `%APPDATA%\cura\<ver>` | `~/Library/Application Support/cura/<ver>` |
| PrusaSlicer | `~/.config/PrusaSlicer` | `%APPDATA%\PrusaSlicer` | `~/Library/Application Support/PrusaSlicer` |
| OrcaSlicer | `~/.config/OrcaSlicer` | `%APPDATA%\OrcaSlicer` | `~/Library/Application Support/OrcaSlicer` |

Flatpak installs are looked for under `~/.var/app/<app id>/`. PrusaSlicer `-alpha` / `-beta` folders are found too. The Linux layouts were checked against real installs; the Windows and macOS locations come from each program's source code and have not been checked on those systems.

What SlicerSwap recognises inside them:

- **Cura:** a printer is a *stack* file in `machine_instances/` that names its extruder stacks (`extruders/`), its user and machine-settings containers (`user/`, `definition_changes/`) and the quality, material and nozzle it uses. A custom profile is one container per stack in `quality_changes/` (one global, one per extruder), tied to a printer type and a quality type. Plug-ins live in `plugins/<id>/<name>/` and are listed in `packages.json`.
- **PrusaSlicer:** one `.ini` per preset in `print/`, `filament/`, `printer/`, `physical_printer/` (and the SLA folders); `PrusaSlicer.ini` holds preferences and the selected presets.
- **OrcaSlicer:** one `.json` plus a small `.info` file per preset in `user/<account or default>/process|filament|machine/`; `OrcaSlicer.conf` holds preferences.

## Backups (`.slicerpack`)

A backup is a zip:

```
slicerpack.json                 list of items; for every file: folder, path, size, SHA-256
files/<folder>/<path>           the files, byte for byte (except blanked secrets)
```

- **Making one:** files are read from the slicer folder, secrets are blanked if you left that option on, and the zip is written. Then the zip is opened again and every entry is compared with its checksum before the window says "Saved and checked".
- **Left out:** logs, caches, lock and temporary files, Cura's built-in profiles, OrcaSlicer's `system` presets and download folders, PrusaSlicer's cache and snapshots.
- **Secrets blanked by default:** Cura's `ultimaker_auth_data` and the network/cloud keys in printer stacks; `printhost_apikey`, `printhost_user`, `printhost_password` in PrusaSlicer and Orca presets; the account and access-code sections of `OrcaSlicer.conf`.

## Restore

1. The backup's list is read and every file checked against its checksum.
2. A backup only goes into the slicer it came from. A backup from a newer Cura than the target is refused unless you allow it (Cura refuses the same thing in its own backup feature).
3. Each file is compared with what is in the slicer now: new, identical, or different.
4. Before anything is written, every file that will be replaced is copied into a **safety copy** (itself a `.slicerpack`), together with a list of the files the restore is about to add.
5. Each file is written under a temporary name, moved into place, read back and compared with the backup. Paths in a backup are checked so nothing can be written outside the slicer's folders.
6. Cura plug-ins that were installed as packages are also re-entered in Cura's `packages.json`, so Cura lists them again. If that file cannot be read, the plug-in folders are restored and the list is left alone, with a note.

Before step 4, every file the restore will write is read from the backup and checked against its checksum. A damaged or incomplete backup therefore changes nothing. If writing stops part-way (a full disk, no permission), the message says how many files were written, and Undo puts them back.

**Undo** uses the latest safety copy: replaced files are put back, and files the restore added are removed, but only if they still have exactly the content the restore wrote. A safety copy is marked as used after an undo and cannot be applied a second time, because that would overwrite changes made since.

A restore never deletes files that are in the slicer but not in the backup.

## Putting converted profiles straight into a slicer

- **PrusaSlicer:** three files, `print/<name>.ini`, `filament/<name>.ini`, `printer/<name>.ini`.
- **OrcaSlicer:** `process/`, `filament/` and `machine/` `<name>.json` in the active user folder, each with the `.info` file Orca expects and the `version` field without which Orca skips a user preset.
- **Cura:** two containers in `quality_changes/`, one for the printer and one for its extruder, named and tagged the way Cura's own "Create profile" does, for a printer that already exists in that Cura. The quality type is chosen from the ones that exist for that printer's material and nozzle, nearest to the layer height.

If a preset with that name exists, the new one becomes `name (2)`. Every file is read back after writing.

## Cura plug-ins

SlicerSwap does not copy a plug-in into Cura's plug-in folder. It does what Cura's Marketplace does:

1. The plug-in (a `.curapackage`, a zip, or a folder with `plugin.json` and `__init__.py`) is **checked for the icon fault** described below. With the fault it is refused and nothing is written.
2. It is wrapped as a `.curapackage` if it isn't one.
3. The package is placed in Cura's package cache and entered under `to_install` in Cura's `packages.json` (the version before is kept as `packages.json.bak`).
   If `packages.json` exists but cannot be read (cut short, binary, not JSON, or the wrong shape), nothing is written at all. Rewriting it would wipe Cura's record of every other plug-in, which is what Cura itself does when it next saves the list. SlicerSwap says so and points to `packages.json.bak` when that copy is readable. An empty file is treated as an empty list. **Remove selected** still works in this state: it moves the plug-in folder aside and leaves the list alone.
4. On its next start **Cura itself** unpacks it into `plugins/`, records it as installed and loads it. It then appears under *Marketplace → Manage packages* like any other. A newer version installed over an older one replaces it: Cura removes the old folder first.

Post-processing scripts are single `.py` files copied to Cura's `scripts/` folder.

### The icon fault

Cura recolours tool-bar icons like this (`UM/ColorImage.py`): it reads the icon file and replaces every `<svg ` with `<svg fill="#rrggbb" `. If the `<svg>` tag already has a `fill` attribute, the result has the attribute twice, which is not valid XML, and Cura's SVG loader takes Cura down with a segmentation fault while the window is being built. Cura logs "Loaded plugin …" before that point.

SlicerSwap repeats that replacement on the plug-in's icon files and tries to parse the result. A file that parses before and not after has the fault. It counts as "stops Cura from starting" only when the plug-in names it as its tool-bar icon (`"icon": "…svg"` in its `getMetaData()`); such a file used as an ordinary picture is harmless. One handed to Cura's recolouring item in a plug-in's own panel only gets a warning, because that case was not reproduced.

Where the check is applied: before installing; on every plug-in already in Cura whenever the list is shown; on the plug-ins inside a backup when it is made (a warning is stored in the backup) and when it is restored (the plug-in is left out).

### What "loaded" means

**Check** (and the automatic check after **Start Cura**) reads four things, in this order:

1. **The plug-in's own files**, for the icon fault. Red if found, whatever the log says.
2. **Cura's `plugins.json`**, for plug-ins switched off inside Cura.
3. **Cura's log**, for its most recent start only: "Loaded plugin …", "has been disabled", "is incompatible with the current sdk version", "failed to register", import errors with the last line of Cura's traceback. The version Cura loaded is compared with the version installed.
4. **Whether that start finished**: Cura's "Booting Cura took …" line, a normal close, or the log carrying on for a minute after the plug-in loaded. If none of these is there and Cura is not running, the plug-in is *NOT CONFIRMED*; when Cura's crash record (`stderr.log`, which Cura rewrites on every start) holds a "Fatal Python error", that line is quoted.

Green needs steps 1 to 4 all to pass.

### Removing

A plug-in on Cura's package list is entered under `to_remove`; Cura deletes it at its next start, before it loads plug-ins, so this works even when the plug-in stops Cura from starting. A hand-copied folder is moved to `plugins-removed-by-slicerswap/` next to the plug-in folder (kept out of backups).

## Conversion pipeline

```
 source file(s) ──read──▶ native values ──resolve──▶ canonical settings ──write──▶ target file(s) + report
```

1. **Detect** the source format from the file (zip contents, `[general]`/`[values]` sections, JSON).
2. **Read native values.**
   - *Cura:* the profile's containers are layered over the quality, material and nozzle containers for the chosen printer and the printer's definition chain (`fdmprinter` → vendor base → printer → extruder). Every Cura setting is then evaluated lazily: its value is the top-most layer that sets it, otherwise its definition's `value` formula, otherwise its `default_value`. Formulas are evaluated with Cura's helper functions (`resolveOrValue`, `extruderValue`, …) mapped onto the single extruder. Expressions are parsed first and anything other than plain expressions is refused.
   - *PrusaSlicer:* `key = value` INI. `inherits` chains are followed. Percentages are turned into absolute values from what they are relative to.
   - *OrcaSlicer:* one JSON per preset; `inherits` is followed through the files given and Orca's own folders.
3. **Canonical model:** 160 neutral settings in fixed units (mm, mm/s, mm/s², °C, %, s, layers). 112 are straight renames (table `ROWS` in `slicerswap/mapping.py`); the rest need logic.
4. **Write the target.** Orca: JSON with the right value shapes. Prusa: a config bundle plus a flat config. Cura: a `quality_changes` profile. A value is only left out of a Cura profile when Cura would compute exactly that value from *other values in the same profile*; everything else is written, because the material or printer in your Cura may say something different.
5. **G-code:** placeholders are translated through the same table. Prusa↔Orca rewrites names inside `{if}` expressions too; a placeholder the target does not have is replaced by its value from the source profile, and the report says so. Cura has no macro language, so logic is left untouched and reported.
6. **Report:** converted values, approximations, things the target can't express, source settings that were not converted, and settings the target *version* is too old to have.

## Bundled reference data (`slicerswap/data/`)

| File | From | Used for |
|---|---|---|
| `cura/definitions`, `cura/extruders` | Cura (LGPLv3) | setting list, formulas, printer overrides |
| `cura/containers.json.gz` | Cura's quality, intent and nozzle (variant) profiles (LGPLv3), packed into one file | layer height, speeds, temperatures per quality / material / nozzle |
| `cura/generic_materials.json` | Ultimaker fdm_materials (CC0) | material temperatures, diameters, per-printer overrides |
| `prusa_keys.json`, `orca_keys.json` | option names, types and enum values from each slicer's `PrintConfig.cpp` (PrusaSlicer 2.9.6; OrcaSlicer main branch of October 2026, 2.5.0-dev) | output value formatting and key validation |

`tools/update_data.py` regenerates all of these from upstream checkouts.

## How it is checked against the real programs

`tools/host_tests/` holds two scripts that run real Cura, PrusaSlicer and OrcaSlicer on SlicerSwap's output in a throwaway folder and read back what each program made of it. See [tools/host_tests/README.md](tools/host_tests/README.md) for what they cover and the last results.
