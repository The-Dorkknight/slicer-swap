# **SLICER SWAP. WORK IN PROGRESS: MANY FEATURES MAY BE BROKEN**

<p align="center"><img src="docs/images/icon-512.png" alt="SlicerSwap icon" width="128" style="height:auto"></p>

# SlicerSwap

One window for the settings of **Cura**, **PrusaSlicer** and **OrcaSlicer**:

- **Convert** print profiles between the three, in any direction, with a plain-English report.
- **Back up** your profiles, materials, printers, plug-ins and app settings into one file.
- **Restore** a backup, all of it or only the parts you tick, with a safety copy and an undo.
- **Install** converted profiles straight into a slicer, and Cura plug-ins and scripts into Cura.

**Licence:** source-available under the [PolyForm Noncommercial License 1.0.0](LICENSE.md) (free for personal / non-commercial use; not OSI open source).
**No warranty, no liability.** Converted presets can contain wrong temperatures, speeds or start G-code, and a restore changes your slicer's settings folder. Check every preset in the slicer before printing.

Version `0.2.1-wip` · Copyright Matthew Armstrong ([The-Dorkknight](https://github.com/The-Dorkknight))

<p align="center"><img src="docs/images/gui-slicers.webp" alt="SlicerSwap listing Cura, PrusaSlicer and OrcaSlicer with what each one holds" width="640" style="height:auto"></p>

## Start it

Download the repository (green **Code** button → **Download ZIP**, then unzip) or `git clone` it. Then double-click the file for your system:

| System | Double-click | First time only |
|---|---|---|
| **Linux** | `SlicerSwap-Linux.sh` (choose **Run** if asked) | `sudo apt install python3 python3-tk` on Mint / Ubuntu / Debian. Fedora: `sudo dnf install python3 python3-tkinter`. Arch: `sudo pacman -S python tk` |
| **Windows** | `SlicerSwap-Windows.bat` | Install Python from [python.org](https://www.python.org/downloads/); tick **Add python.exe to PATH** |
| **macOS** | `SlicerSwap-Mac.command` | Install Python from [python.org](https://www.python.org/downloads/). macOS may block the file the first time: right-click it → **Open** → **Open** |

Each launcher finds Python by itself and tells you what to install if something is missing. SlicerSwap is pure Python (3.8 or newer) with no extra packages, and runs comfortably on a 7th-gen Core i3.

If double-clicking the Linux file opens it in a text editor, right-click it → **Properties** → **Permissions** → tick **Allow executing file as program**.

## What exists and what doesn't

| Works now | Not yet / not possible |
|---|---|
| Finds every Cura version, PrusaSlicer and OrcaSlicer settings folder on Linux, Windows and macOS, incl. Flatpak; other folders can be added by hand | Snap packages and AppImage "portable home" folders are not found automatically (use **Add a settings folder…**) |
| Back up profiles, materials, printers, plug-ins, scripts, app settings and everything else in the settings folder, to one `.slicerpack` file | Bambu Studio, SuperSlicer, Simplify3D, IdeaMaker |
| Passwords, API keys and account logins are left out of backups by default | Moving a backup from one slicer to another (a Cura backup only restores into Cura; use **Convert** for profiles) |
| Restore everything or only ticked items; shows per item whether it is new, identical or different | Restoring a backup into an *older* Cura than it came from is refused unless you allow it |
| Safety copy before every restore, and **Undo last restore** | Undo for installs (installs never overwrite: they add a new name) |
| Convert Cura ⇄ PrusaSlicer ⇄ OrcaSlicer: 160 settings incl. speeds, accelerations, walls, infill, supports, adhesion, fan, temperatures, retraction, machine limits, start/end G-code placeholders | Multi-extruder profiles (extruder 1 only); per-object, modifier and painted settings |
| Put converted profiles straight into the slicer, read back and checked | Creating a **Cura printer** from a PrusaSlicer/Orca printer preset: Cura profiles are installed for a printer that already exists in Cura; bed size and start G-code are written to a text file to type in |
| Install Cura plug-ins (`.curapackage`, `.zip`, folder) through Cura's own package manager, then confirm from Cura's own files that it loaded **and** that Cura finished starting. A plug-in with the known icon fault that stops Cura from starting is refused | Plug-ins for PrusaSlicer / OrcaSlicer: neither has a plug-in system. Orca's vendor network plug-in folder is included in backups only |
| Install Cura post-processing scripts (`.py`) | Downloading plug-ins from the Cura Marketplace (SlicerSwap never uses the network) |
| Window (tkinter) and full command line | Windows `.exe` / macOS `.app` builds |

## Using the window

<p align="center"><img src="docs/images/gui-disclaimer.webp" alt="First-start notice" width="560" style="height:auto"></p>

**First start:** read the notice, tick the box and press **I agree**. It is remembered in `~/.config/slicerswap/` (Windows: your user folder).

### 1. Slicers

Shows each slicer found, its version, how many of your own profiles, materials, printers and plug-ins it holds, and whether it is open right now. Click a row to see everything in it.

- **Look again** rescans. **Add a settings folder…** adds one SlicerSwap didn't find (a portable install, another disk, an old computer's copied folder).
- **Back up the selected slicer…** jumps to the Back up tab.

Counts are things you made or installed yourself. The hundreds of profiles that ship with a slicer are not counted and not backed up; a reinstall brings those back.

### 2. Convert

<p align="center"><img src="docs/images/gui-convert.webp" alt="Converting a Cura profile and putting it straight into OrcaSlicer" width="640" style="height:auto"></p>

1. **Add files…**
   - Cura: *Preferences → Configure Cura → Profiles → Export* (`.curaprofile`), a saved project `.3mf`, or a `.inst.cfg`.
   - PrusaSlicer: *File → Export → Export Config* (`.ini`), a config bundle, or a project `.3mf`.
   - OrcaSlicer: the process, filament **and** printer `.json` together, a preset bundle, or a project `.3mf`.
2. **Convert to** OrcaSlicer, PrusaSlicer or Cura, and choose where the result goes:
   - **and save the new files in a folder**: you import them yourself (see the table below), or
   - **and put them straight into:** an installed slicer. For Cura, also pick which of your Cura printers the profile is for.
3. **Options** (only the relevant ones show): the new preset name; for Cura input, the **Cura printer type** the profile was made for and the **Cura material** (Cura needs both to work out its hidden values); **Force nozzle / bed °C**; system presets to inherit from.
4. Press **Convert** (or **Convert and install**). **Summary** lists what to check; **Full report** lists every value.

Installing never overwrites: if a preset of that name exists, the new one is called `name (2)`. Start the slicer afterwards and look under your own / user presets.

| Saved to a folder | Files | How to import by hand |
|---|---|---|
| OrcaSlicer | `*.orca_machine.json`, `*.orca_filament.json`, `*.orca_process.json` | *File → Import → Import Configs*, select all three |
| PrusaSlicer | `*.prusa_bundle.ini` or `*.prusa_config.ini` | *File → Import → Import Config Bundle* / *Import Config* |
| Cura | `*.curaprofile` + `*.cura_machine_settings.txt` | Select the matching printer, then *Preferences → Configure Cura → Profiles → Import*. Type the machine settings (bed size, start G-code) into *Printers → Machine Settings* by hand |

### 3. Back up

<p align="center"><img src="docs/images/gui-backup.webp" alt="Back up tab with tick boxes for profiles, printers, plug-ins, scripts and settings" width="640" style="height:auto"></p>

1. Choose the slicer under **Back up from**.
2. Tick what to keep. Everything is ticked to start with; a group's box ticks or unticks the whole group.
3. Leave **Leave out passwords, API keys and account logins** ticked unless the backup stays private and you want them in it.
4. **Save backup…** and choose where. The file is read back and every entry compared before SlicerSwap says "Saved and checked".

Making a backup changes nothing in the slicer. If the slicer is open, changes it has not saved yet are not in the backup, and SlicerSwap says so.

### 4. Restore

<p align="center"><img src="docs/images/gui-restore.webp" alt="Restore tab comparing a backup with the slicer: one profile missing, one script different" width="640" style="height:auto"></p>

1. **Choose backup…** and pick a `.slicerpack`. The backup is checked for damage first.
2. **Restore into**: the slicer to put it in (a backup only goes back into the same kind of slicer).
3. The list compares the backup with that slicer **as it is now**: *not there yet*, *already there, identical*, or *different: replaces N file(s)*. Only items that would change something are ticked.
4. Close the slicer, then press **Restore ticked items** and confirm.

<p align="center"><img src="docs/images/gui-restore-done.webp" alt="After a restore: files added and replaced, checked, safety copy location" width="640" style="height:auto"></p>

Every file is written to a temporary name, read back and compared with the backup. Files that get replaced are first saved to a safety copy; **Undo last restore…** puts them back and removes the files the restore added (only if they are still unchanged).

A restore only adds and replaces. It never deletes things that are in the slicer but not in the backup.

### 5. Plug-ins (Cura)

<p align="center"><img src="docs/images/gui-plugins.webp" alt="Plug-ins tab: two plug-ins confirmed loaded, one flagged because it stops Cura from starting" width="640" style="height:auto"></p>

1. **Install plug-in file…** takes a `.curapackage` or a `.zip` of the plug-in folder (GitHub's *Download ZIP* works). **Install plug-in folder…** takes the unpacked folder.
2. SlicerSwap first **checks the plug-in for a fault that stops Cura from starting** (see below). If it is sound, it is handed to **Cura's own package manager**, the way the Marketplace does. Cura installs it on its next start and lists it under *Marketplace → Manage packages*, where Cura can also disable or remove it.
3. Press **Start Cura**. The list then updates by itself for two minutes; you don't need to press anything. (**Check** does the same at any time.)

What the colours mean, in the **What Cura says** column:

| Colour | Meaning |
|---|---|
| Green: *Loaded by Cura at …* | Cura loaded the plug-in **and** finished starting. |
| Amber: *Queued* / *NOT CONFIRMED* | Cura has not been started since, or Cura logged the plug-in as loaded but that start never finished. If Cura crashed, its own crash record is quoted. |
| Red | It stops Cura from starting, it is switched off inside Cura, it was made for a different Cura version, or Cura reported an error. The reason is Cura's own, word for word. |

If you can't see a loaded plug-in in Cura: tool-bar buttons only appear once a model is loaded. It is also listed under *Marketplace → Manage packages* (the cog).

- **Install script (.py)…** copies a post-processing script; it appears in Cura under *Extensions → Post Processing → Modify G-Code*.
- **Remove selected** asks Cura to remove a packaged plug-in on its next start; a plug-in that was copied in by hand is moved to a `plugins-removed-by-slicerswap` folder next to Cura's plug-in folder (nothing is deleted). Both work while Cura cannot start.

A plug-in is a program that runs inside Cura with your user rights. Only install plug-ins from people you trust.

#### The fault that stops Cura from starting

<p align="center"><img src="docs/images/gui-plugin-refused.webp" alt="SlicerSwap refusing a plug-in whose tool-bar icon would crash Cura" width="560" style="height:auto"></p>

Cura recolours tool-bar icons by adding `fill="…"` to the icon's `<svg>` tag. If the icon already has a `fill` there, the file becomes invalid and Cura crashes (segmentation fault) while its window is being built, on every start. Cura writes "Loaded plugin …" into its log just *before* that, so the log alone looks fine. This is the fault Hybrid Supports 0.1.0-wip had; it was reproduced in Cura 5.13.0.

SlicerSwap therefore:

- **refuses to install** a plug-in with that fault, and says which file;
- **shows an already-installed one in red** before you start Cura, so you can remove it;
- **never shows green on the log alone**: after a crash the other plug-ins read *NOT CONFIRMED*, with Cura's crash record;
- **leaves such a plug-in out of a restore**, and says so; a backup that contains one carries a warning.

<p align="center"><img src="docs/images/gui-plugins-crash.webp" alt="After Cura crashed while starting: the faulty plug-in in red, the others not confirmed" width="640" style="height:auto"></p>

## What it looks like in the slicers

Presets and a plug-in installed by SlicerSwap, shown by the real programs (PrusaSlicer 2.7.2, OrcaSlicer 2.4.2, Cura 5.13):

<p align="center"><img src="docs/images/in-prusaslicer.webp" alt="PrusaSlicer listing installed presets under User presets" width="560" style="height:auto"></p>
<p align="center"><img src="docs/images/in-orcaslicer.webp" alt="OrcaSlicer listing installed presets under User presets" width="360" style="height:auto"></p>
<p align="center"><img src="docs/images/in-cura-plugin.webp" alt="Cura's Manage packages window listing the plug-in installed by SlicerSwap" width="640" style="height:auto"></p>

All screenshots were taken from the real programs on a Linux virtual display, with a demo user's settings.

## What is in a backup

A `.slicerpack` is an ordinary zip: a list (`slicerpack.json`) with a checksum for every file, plus the files.

| Slicer | Backed up | Left out |
|---|---|---|
| Cura | Custom profiles, custom materials, printers with their extruders and machine settings, plug-ins, post-processing scripts, preferences (`cura.cfg`), anything else in the settings folders | Logs, caches, Cura's built-in profiles |
| PrusaSlicer | Print, filament, printer and physical-printer presets, SLA presets, preferences (`PrusaSlicer.ini`), installed vendor bundles, custom shapes | Cache, PrusaSlicer's own snapshots, built-in presets |
| OrcaSlicer | Process, filament and printer presets of every user account folder, preferences (`OrcaSlicer.conf`), the vendor network plug-in folder | Orca's built-in `system` presets, logs, downloaded update data |

With passwords left out (the default), these are blanked inside the backup: Cura's UltiMaker account login and network/cloud printer links (the printer comes back as a plain, unlinked printer), PrusaSlicer's print host API key / user / password, OrcaSlicer's printer access codes and account section. Your slicer's own files are not touched.

Safety copies made before a restore are kept in `~/.local/share/slicerswap/safety-copies` (Windows: `%LOCALAPPDATA%\slicerswap`, macOS: `~/Library/Application Support/slicerswap`).

## Command line

Everything the window does also works from a terminal. `./SlicerSwap-Linux.sh ARGS` and `python3 -m slicerswap ARGS` are the same thing.

```sh
python3 -m slicerswap list                                   # slicers found and what they hold
python3 -m slicerswap backup cura -o "my cura.slicerpack"    # back up (add --everything for a full copy)
python3 -m slicerswap backup orca --only profile printer     # only some kinds
python3 -m slicerswap restore "my cura.slicerpack" --dry-run # show what a restore would do
python3 -m slicerswap restore "my cura.slicerpack"           # do it
python3 -m slicerswap undo cura                              # undo the last restore
python3 -m slicerswap plugin install MyPlugin.curapackage    # hand a plug-in to Cura
python3 -m slicerswap plugin check                           # did Cura load it?

python3 -m slicerswap "Fast PETG.curaprofile" --to orca --cura-machine creality_ender3
python3 -m slicerswap config.ini --to cura --install --cura-printer "Creality Ender-3"
python3 -m slicerswap proc.json fil.json printer.json --to prusa -o out/
python3 -m slicerswap --list-cura-machines | grep -i ender
python3 -m slicerswap --version
```

Each command has its own `--help`. Use `--folder PATH` to work on a settings folder that isn't in the usual place, and `--slicer-version 5.8` when several Cura versions are installed.

## Troubleshooting

| Problem | Fix |
|---|---|
| The launcher says Python or tkinter is missing | Install what it names (table under **Start it**). The command line works without tkinter. |
| A slicer is not listed | Start that slicer once so it creates its settings folder, press **Look again**, or use **Add a settings folder…**. |
| "… seems to be open. Continue anyway?" | Close the slicer and try again. A slicer only reads these files when it starts and may overwrite them when it closes. |
| A restored or installed profile doesn't show in Cura | Select the printer it was made for; Cura only lists a custom profile for the printer type it belongs to, and for a material/nozzle that has its quality type. |
| Cura crashes every time it starts, right after its splash screen | A plug-in may be the cause. Open the **Plug-ins** tab: a plug-in with the known icon fault is red, "STOPS CURA FROM STARTING". Select it, press **Remove selected**, start Cura. If none is red, remove the plug-in you installed last. |
| "Not installed. … would stop Cura from starting" | The plug-in's tool-bar icon has the fault described under **Plug-ins**. It needs a fixed version from its author; SlicerSwap will not install it. |
| Plug-in shows red | The column shows the reason: switched off inside Cura, made for a different Cura version, or Cura's own error message (for example a missing Python module). |
| Plug-in shows amber "NOT CONFIRMED" | Cura logged it as loaded but did not finish starting. Start Cura again and press **Check**. |
| Plug-in stays "Queued" | Cura has not been started since. Press **Start Cura**; the list updates by itself. |
| Plug-in is green but you can't see it in Cura | Load a model: Cura hides tool-bar buttons until then. It is also under *Marketplace → Manage packages*. |
| **Start Cura** asks you to choose the program | SlicerSwap looks for Cura AppImages in your home, Applications, Downloads and Desktop folders (Windows: Program Files; macOS: Applications). Pick it once by hand, or start Cura yourself and press **Check**. |
| "The backup was made with Cura …, which is newer than this …" | Restoring into an older Cura can make it reject files. Tick **Allow a backup from a newer Cura version** if you want to try; the safety copy and Undo still apply. |
| Report says PrusaSlicer "is older than these settings" | Nothing is broken: your PrusaSlicer ignores a few settings that only newer versions have. The report names them. |
| Report says an Orca preset "inherits … which wasn't found" | Add the parent preset files too, or use the Orca profiles folder option. |
| Start G-code still contains `{if …}` after converting to Cura | Cura can't run that logic. Edit those lines by hand (the report lists them). |

## How it was tested, and what was not

Run on Linux with the code of this version (details and scripts in [tools/host_tests](tools/host_tests/README.md)):

- **Real Cura 5.13.0:** a SlicerSwap restore into an empty Cura brought back the printer as the active printer; two converted profiles were listed as selectable and, once switched on, Cura reported the intended value for 96 of 96 and 95 of 95 settings; a plug-in handed to Cura's package manager was installed and loaded by Cura and listed under *Manage packages*.
- **Plug-in faults, in real Cura 5.13.0:** a tool plug-in with the icon fault was refused by SlicerSwap; copied in by hand it made Cura die 5 seconds into starting (exit by segmentation fault) although Cura's log said "Loaded plugin"; SlicerSwap showed it red before Cura was started and did not show the other plug-ins green afterwards; removing it with SlicerSwap let Cura start again, both for a hand-copied folder and for one on Cura's package list. A newer version installed over an older one left exactly one copy. A switched-off plug-in, one made for an older Cura, one that raises an error and one with a missing module were each reported with Cura's own reason.
- **Hybrid Supports 0.1.2-wip** (a real tool plug-in): installed with SlicerSwap, loaded by Cura and on Cura's package list; installed with its own installer, SlicerSwap reported it correctly, and it survived a SlicerSwap backup and restore into another Cura.
- **Real PrusaSlicer 2.7.2:** sliced a cube with converted profiles and reported back 123 of 123, 103 of 103 and 108 of 108 written values; installed presets appear under *User presets*.
- **Real OrcaSlicer 2.4.2:** sliced a cube with converted presets and reported back 142 of 142, 117 of 117 and 114 of 114 written values; installed presets appear under *User presets*.
- The window was driven by hand through backup, restore, undo, convert-and-install, plug-in install, the refusal of a faulty plug-in, **Start Cura** with its automatic check (good start and crashed start) and removing the faulty plug-in; the Linux launcher was run. 60 automated tests pass on Python 3.11, 3.12 and 3.13 (the stated minimum, 3.8, was not run).

**Not tested:** Windows and macOS (the folder locations come from each program's source code, and the Windows and Mac launchers have never been run; finding and starting Cura there is untested too); Flatpak installs; other slicer versions, including whether other Cura versions crash on the icon fault in the same way; real printers (no G-code produced here has been printed); the GitHub workflows.

## Known limitations

- Single extruder only. Per-object settings, modifiers, painted supports/seams are not converted.
- Some concepts differ between slicers and are approximated; each one is listed in the report (seam modes, combing vs "avoid crossing walls", fan ramp-up, support density vs spacing, infill patterns one slicer lacks, Orca's per-plate bed temperatures).
- Cura profiles are installed for an existing Cura printer. SlicerSwap does not create Cura printers from other slicers' printer presets.
- The bundled Cura data is from Cura's `main` branch (September 2026, see `slicerswap/data/cura/UPSTREAM_COMMIT.txt`); one formula already differs from Cura 5.13. When an installed Cura program is found, its own quality files are used instead of the bundled ones.
- The PrusaSlicer setting list is from 2.9.6. Older versions ignore the newer settings; the report names them. The OrcaSlicer list is from its development branch (2.5.0-dev); OrcaSlicer 2.4.2 accepted every setting written in the tests, but there is no such per-version check for Orca yet.
- Detecting that a slicer is open is a best guess from the process list.
- The plug-in check knows one fault (the tool-bar icon). A plug-in can stop Cura in other ways; SlicerSwap then shows *NOT CONFIRMED* rather than naming the culprit. An icon with the same fault used inside a plug-in's own panel is only warned about, because that case was not reproduced.
- A backup restores into the same slicer on any of the three systems in principle, but cross-system restores (e.g. Windows backup into Linux) are untested.

See [HOW_IT_WORKS.md](HOW_IT_WORKS.md) for what is read and written, and [CHANGELOG.md](CHANGELOG.md).

## Why converting is harder than it looks

A Cura profile is not a list of values. It stores only what you changed; everything else comes from a stack of containers (your changes, the quality profile, the material, the nozzle, the printer definition, Cura's base definition), and about half of Cura's ~740 settings are **Python formulas** of other settings. SlicerSwap ships Cura's setting definitions and evaluates those formulas the way Cura does, for the printer you pick. PrusaSlicer and OrcaSlicer store explicit values with `inherits` chains and percentages, which are resolved too.

## Developing

```sh
python3 -m unittest discover -s tests      # 60 tests, standard library only
python3 tools/host_tests/check_prusa_orca.py --prusa /usr/bin/prusa-slicer --orca /path/to/OrcaSlicer
python3 tools/host_tests/check_cura.py --cura /path/to/UltiMaker-Cura.AppImage
python3 tools/host_tests/check_cura_plugins.py --cura /path/to/UltiMaker-Cura.AppImage
python3 tools/update_data.py --help        # refresh bundled Cura/Prusa/Orca reference data
```

Contributions: see [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md). Third-party data: [THIRD_PARTY.md](THIRD_PARTY.md).
