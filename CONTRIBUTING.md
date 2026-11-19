# Contributing

Thanks for helping. Main repository: https://github.com/The-Dorkknight/slicer-swap

- Contributions are accepted under the same licence as the project (PolyForm Noncommercial License 1.0.0, see LICENSE.md). By opening a pull request you agree to that.
- Most useful right now: reports from **Windows and macOS** (does it find your slicers? do the launchers start?), real profiles that convert badly (attach them and the report to an issue), and backups that don't restore cleanly.
- Run `python3 -m unittest discover -s tests` before sending. If your change affects what is written into a slicer, also run the checks in `tools/host_tests/` against the real program and say which versions you used.
- Mapping changes go in `slicerswap/mapping.py`. The key-validity tests check every mapped key against each slicer's option list.
- Anything that writes into a slicer's folder must read its work back, must never overwrite or delete a user's file without a safety copy, and must say plainly what it did.
- Keep it dependency-free and quick on low-end hardware (7th-gen Core i3 baseline).
