# Changelog

All notable changes are listed here. Versions follow semantic versioning; `-wip` means work in progress.

## [0.2.2-wip] - 2026-11-19

The known Cura bugs from the other plug-ins were checked one by one, and then a full edge-case sweep was run. One known bug was present: a damaged `packages.json` could be overwritten. The sweep found the other problems listed below.

### Fixed
- **A damaged Cura package list could wipe Cura's record of your other plug-ins.** If `packages.json` was cut short, binary or not JSON, SlicerSwap read it as empty. Installing, removing or restoring a plug-in then wrote a new list holding only that plug-in. Forge-X and the Bambu plug-in had the same bug. Now:
  - installing refuses and changes nothing: no copy is queued, and no `.bak` of the damaged file is made;
  - **Remove selected** still works as a rescue: it moves the folder aside and leaves the list alone;
  - a restore puts the plug-in folders back but leaves the list alone, and says so;
  - the Plug-ins tab and `slicerswap plugin list` show a warning. If a good `packages.json.bak` exists, they point to it.
  - An empty file, or one starting with a byte-order mark, still works.
  - Real Cura (Uranium's package manager) silently ignores such a file and later saves a list holding only new entries. SlicerSwap does not copy that.
- **A second Undo could overwrite changes made after the first one.** From the command line, a safety copy could be applied again days later. A used safety copy is now marked as used and refused.
- **Undo could pick the wrong safety copy** when several restores happened in the same second (`-2` … `-10` copies sorted wrongly). They now sort by time and number.
- **A damaged or incomplete backup could leave a half-done restore.** Every file is now checked against its checksum before anything is written. A damaged backup changes nothing.
- **A restore stopped by a full disk or missing permission** now says how many files were written and how to undo them. Before, it showed a bare error.
- **Backups with a damaged list of items** (no items, an item without files, wrong types) gave a Python error. They now give "Backup list is damaged".
- **An empty or junk profile was "converted" into a profile made only of defaults.** An empty `.ini`, `.curaprofile` or `.inst.cfg`, or random bytes, is now refused with "No … settings found in <file>".
- **Damaged JSON or non-text profiles** gave bare parser messages or Python errors. They now name the file.
- **Plug-in files:** a damaged `plugin.json` or `package.json`, one that is not a JSON object, or one not in UTF-8 gave a Python error. It is now refused with a plain message.
- **A `.curapackage` whose package id contained `../` was written outside Cura's cache folder.** Package ids must now be letters, digits, `_`, `.` or `-`, with no `..`. Remove checks the name the same way.
- **The same plug-in could get two different ids.** A plug-in installed from its folder (for example `MyPlugin-main`) and the same one from a zip were treated as different plug-ins. Both routes now use the same id.
- A truncated `.zip` or `.curapackage` now reads "damaged or incomplete, download it again", not "pick a .curapackage file".
- A file inside a project `.3mf` or profile zip that unpacks to more than 50 MB is refused, not read into memory. This matters on a low-end PC.
- Writing to a read-only folder or a full disk now shows a plain message in the window, not a Python traceback.
- Files are flushed to disk before they replace the old ones, so a power cut cannot leave an empty settings file.

### Added
- `tools/edge_sweep.py`: 71 edge cases (damaged, empty, huge and oddly named inputs; hostile and damaged backups; an interrupted restore, then undo twice; read-only and missing folders; damaged plug-ins; missing, binary and 100 MB Cura logs; two Cura versions). It needs no slicer and takes about 10 s.
- Step 8 of `tools/host_tests/check_cura_plugins.py`: a damaged `packages.json` in real Cura.
- 12 more automated tests (72 in total).

### Checked and already fine
- Cura's tool-bar icon fault, "Loaded plugin" not being proof, listing under *Manage packages*, and the hint that tool-bar buttons only show once a model is loaded. All were fixed in 0.2.1-wip.
- HTML in Cura messages does not apply: SlicerSwap is not a Cura plug-in and shows nothing inside Cura.
- Missing, empty, binary, cut-off, non-UTF-8 and 100 MB Cura logs are read without errors. A 100 MB log is read in under 0.2 s.

### Checked in the real programs (Linux)
- Cura 5.13.0: `check_cura_plugins.py` (32 checks, including the new damaged-list step) and `check_cura.py` (restore, two profile installs, plug-in install; 96 of 96 and 95 of 95 values) passed.
- PrusaSlicer 2.7.2 and OrcaSlicer 2.4.2: `check_prusa_orca.py` passed. Every converted value was kept in all six directions.

### Not tested
- Windows and macOS (including their launchers), Flatpak installs, other slicer versions, the GitHub workflows, and printing the converted profiles on a real printer.

## [0.2.1-wip] - 2026-10-07

Checked against the installer of Hybrid Supports 0.1.2-wip, which fixed two installation faults. One of them was missing here.

### Fixed
- **SlicerSwap installed a plug-in that stops Cura from starting, then showed it green.** A tool-bar icon with `fill` on its `<svg>` tag makes Cura crash (segmentation fault) while its window is being built, on every start; Cura logs "Loaded plugin" just before, and 0.2.0-wip trusted that line. Reproduced in Cura 5.13.0. Now:
  - such a plug-in is refused at install, with the file named;
  - one that is already installed is shown red ("STOPS CURA FROM STARTING") before Cura is started, and can be removed while Cura cannot start;
  - green requires that Cura loaded the plug-in **and** finished starting; after a crash the other plug-ins read "NOT CONFIRMED", with Cura's own crash record;
  - a restore leaves such a plug-in out and says so; a backup containing one carries a warning.
- A plug-in switched off inside Cura was reported as "did not load, no reason". It now says it is switched off and where to switch it on.
- For a plug-in Cura could not load, only the first line of Cura's error was shown ("Error loading plugin X:"). The cause is now included (for example `ModuleNotFoundError: No module named …`).
- A plug-in folder moved aside by **Remove selected** ended up in full backups.
- `slicerswap restore --dry-run` listed files of a left-out plug-in as "replace".

### Changed
- **Start Cura** finds Cura AppImages in more places (home, Applications, Downloads, Desktop, AppImages, bin, /opt; Program Files; macOS Applications), prefers the one matching the selected Cura version, explains an AppImage that is not marked executable, and asks for the program when none is found.
- After **Start Cura** the plug-in list updates by itself for two minutes; no need to press Check.
- Cura's package list is copied to `packages.json.bak` before SlicerSwap changes it.
- A plug-in whose loaded version differs from the installed one reads "restart Cura" instead of "loaded".
- A hint where to find a loaded plug-in (Cura hides tool-bar buttons until a model is loaded).

### Already the same as Hybrid Supports 0.1.2-wip
- Its other fix, installing the way Cura's own package installer does so the plug-in is listed under *Marketplace → Manage packages*, is how SlicerSwap has installed plug-ins since 0.2.0-wip. Confirmed with Hybrid Supports 0.1.2-wip itself in Cura 5.13.0.

### Added
- `tools/host_tests/check_cura_plugins.py`: proves all of the above in a real Cura, including that the faulty plug-in really does take Cura down.
- `tests/data/DemoToolPlugin` (a harmless tool-bar plug-in) and excerpts of two real Cura 5.13 logs (a good start, a crashed start); 9 more automated tests (60 in total).

### Not tested
- Windows and macOS, as before. Whether Cura versions other than 5.13.0 crash on the icon fault in the same way. The same fault in an icon used inside a plug-in's own panel.

## [0.2.0-wip] - 2026-10-06
### Added
- **One tabbed window** for five jobs: Slicers, Convert, Back up, Restore, Plug-ins.
- **Slicer detection:** finds every Cura version, PrusaSlicer and OrcaSlicer settings folder (Linux, Windows, macOS, Flatpak), shows what each holds and whether it is open; other folders can be added by hand.
- **Back up** profiles, materials, printers, plug-ins, scripts and app settings to one `.slicerpack` file, read back and checked after writing. Passwords, API keys and account logins are left out by default.
- **Restore** all or only ticked items, with a per-item comparison against the slicer as it is now, a safety copy of everything replaced, read-back verification, and **Undo last restore**.
- **Install converted profiles straight into a slicer** (never overwriting an existing preset).
- **Cura plug-ins:** install a `.curapackage`, zip or folder through Cura's own package manager; **Check** confirms from Cura's log that Cura loaded it; remove; install post-processing scripts.
- Command line: `list`, `backup`, `restore` (with `--dry-run`), `undo`, `plugin install|check|list|remove`, and `--install` for conversions.
- Double-click launchers: `SlicerSwap-Linux.sh`, `SlicerSwap-Windows.bat`, `SlicerSwap-Mac.command` (replace `slicerswap.sh`).
- Cura conversions now use Cura's material- and nozzle-specific quality profiles (bundled, 8,391 containers in one 150 KB file) without needing an installed Cura.
- Report note when PrusaSlicer output uses settings the target PrusaSlicer version is too old to have.
- `tools/host_tests/`: scripts that check SlicerSwap's output in real Cura, PrusaSlicer and OrcaSlicer.
- 30 more automated tests (51 in total).

### Fixed (found by loading 0.1.0's output into the real slicers)
- Cura: a converted bed temperature could be silently dropped, so Cura used its own material default instead (the 50 °C of Cura's Creality PLA on an Ender-3). Values are now only left out of a Cura profile when Cura derives exactly that value from other values in the same profile.
- PrusaSlicer → Cura: `infill_overlap = 10%` was written as 0.045.
- PrusaSlicer: `deretract_speed = 0` ("same as retraction speed") was converted as 0 mm/s.
- OrcaSlicer: per-axis speed limits were written under PrusaSlicer's key names, which Orca does not have.
- OrcaSlicer refused to slice start G-code containing a Cura placeholder with no Orca equivalent (`{machine_depth}`); bed size placeholders are now translated and unknown ones replaced by their value.
- Percent values for settings that accept "mm or %" were written without the `%` sign.

### Changed
- The 0.1.0 README said the output had not been imported into the real programs. It now has been, on Linux: Cura 5.13.0, PrusaSlicer 2.7.2 and OrcaSlicer 2.4.2 (see README, "How it was tested").

### Not tested
- Windows and macOS (including their launchers), Flatpak installs, other slicer versions, the GitHub workflows, and printing the converted profiles on a real printer.

## Earlier builds

### 0.1.0-wip - 2026-10-03
Added:
- First proof of concept: Cura ⇄ PrusaSlicer ⇄ OrcaSlicer profile conversion in all six directions.
- Cura formula/stack resolver with bundled Cura definitions (643 printers evaluate without formula errors).
- Readers: `.curaprofile`, `.inst.cfg`, Cura `.3mf`; PrusaSlicer `.ini`, config bundles, `.3mf`; OrcaSlicer `.json`, preset bundles, `.3mf`.
- 160-setting canonical model, G-code placeholder translation, conversion reports.
- tkinter window and command line; 21 automated tests.

Not tested:
- Importing the output into real Cura / PrusaSlicer / OrcaSlicer installations.
