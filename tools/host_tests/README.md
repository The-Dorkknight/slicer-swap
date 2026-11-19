# Checks against the real slicers

The unit tests in `tests/` prove SlicerSwap agrees with itself. These two scripts ask the
**real programs** instead: they hand SlicerSwap's output to Cura, PrusaSlicer and OrcaSlicer
and read back what each program made of it.

Nothing here touches your own slicer settings. Every check works in a throwaway folder that
is deleted afterwards (add `--keep` to look inside).

| Script | What it asks the real program |
|---|---|
| `check_prusa_orca.py` | Does PrusaSlicer / OrcaSlicer slice a cube with the converted profile, and does it report back every value that was written? Do installed presets land where the program looks for them? |
| `check_cura.py` | After a SlicerSwap restore, a profile install and a plug-in install: does Cura show the printer, list the profiles as selectable, load the plug-in, and report the intended value for every setting once the profile is switched on? |
| `check_cura_plugins.py` | The plug-in cases: a sound tool plug-in loads; a newer version replaces an older one; a plug-in whose tool-bar icon has `fill` on its `<svg>` tag is refused by SlicerSwap and, copied in by hand, really does make Cura crash while starting; SlicerSwap shows it red and the others "not confirmed"; removing it lets Cura start again; switched-off and unloadable plug-ins are reported with Cura's own reason. `--also PLUGIN` adds a plug-in of your own that must install and load. |
| `SSWTestHook/` | A tiny Cura plug-in used by `check_cura.py`. It runs inside Cura, writes down what Cura itself sees (printers, profiles, plug-ins, every resolved setting) and closes Cura again. It is only ever copied into the throwaway folder. |

## Running them (Linux)

```sh
python3 tools/host_tests/check_prusa_orca.py --prusa /usr/bin/prusa-slicer --orca /path/to/OrcaSlicer
python3 tools/host_tests/check_cura.py --cura /path/to/UltiMaker-Cura-5.13.0-linux-X64.AppImage
python3 tools/host_tests/check_cura_plugins.py --cura /path/to/UltiMaker-Cura-5.13.0-linux-X64.AppImage
```

Cura and OrcaSlicer need a display even for this. On a machine without one:

```sh
xvfb-run -s "-screen 0 1440x900x24" python3 tools/host_tests/check_cura.py --cura ...
```

`check_cura.py` starts Cura three times and takes about four minutes; `check_cura_plugins.py` starts it
seven times (two of them are the crashes it is there to prove) and takes about two. Both are
Linux-only because they give Cura a private home through the `XDG_*` folders.

## Last results

Run again on 2026-11-17 and 2026-11-19, Linux x86-64, with the code of SlicerSwap 0.2.2-wip. All three scripts
passed with the same figures as on 2026-10-07 (0.2.1-wip), shown below, plus the new step 8.

**PrusaSlicer 2.7.2** - sliced with profiles converted from Cura, OrcaSlicer and PrusaSlicer;
kept 123 of 123, 103 of 103 and 108 of 108 values. Two newer settings
(`chamber_temperature`, PrusaSlicer 2.8.0+, and `first_layer_infill_speed`, 2.9.1+) are
ignored by 2.7.2; the conversion report says so.

**OrcaSlicer 2.4.2** - sliced with presets converted from Cura, PrusaSlicer and OrcaSlicer;
kept 142 of 142, 117 of 117 and 114 of 114 values.

**Cura 5.13.0** - restored printer shown as the active printer; both installed profiles listed
as selectable custom profiles; Cura agreed on 96 of 96 and 95 of 95 intended values; the
plug-in was installed by Cura's package manager, loaded, and listed in Cura's package list.
For information, SlicerSwap's own re-implementation of Cura's setting formulas matched Cura on
686 of 689 and 682 of 689 settings of that printer. The differences are prime-tower settings
(a one-nozzle printer has no prime tower), an internal material id, and `initial_bottom_layers`,
whose formula changed between Cura 5.13 and the newer Cura data bundled with SlicerSwap.

**Cura 5.13.0, plug-in faults** (`check_cura_plugins.py`, 26 checks, 27 with `--also`) - the faulty tool plug-in was refused;
the sound one was loaded and Cura closed normally (exit code 0); version 1.0.1 installed over 1.0.0 left
one copy; with the faulty plug-in copied in by hand Cura died about 5 seconds into starting (exit by
signal 11, segmentation fault) although its log said "Loaded plugin FaultyIconTool", and Cura's own crash
record said "Segmentation fault"; SlicerSwap showed the faulty one red and the sound one "not confirmed";
after removal with SlicerSwap Cura started normally again, for the hand-copied folder and for the one on
Cura's package list; the switched-off, raising, missing-module and too-old plug-ins were each reported
with Cura's reason. Run with `--also` on **Hybrid Supports 0.1.2-wip**: installed, loaded, on Cura's
package list.

**Cura 5.13.0, damaged package list** (step 8 of `check_cura_plugins.py`, new in 0.2.2-wip; 32 checks
in all) - with a cut-short `packages.json`, SlicerSwap refused to install and changed nothing; Remove
still worked (folder moved aside, list untouched); real Cura started with the damaged list, still loaded
the plug-in from its folder, and left the file as it was; the Plug-ins tab showed the warning.

Not covered by these scripts: Windows and macOS, Flatpak installs, and any slicer version
other than the three above.
