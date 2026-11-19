# Security

Please report security problems privately via GitHub: the repository's **Security** tab → **Report a vulnerability**. Don't open a public issue for them.

What SlicerSwap is built to withstand, and where reports are most wanted:

- **Profile files from strangers.** SlicerSwap never executes code from them. Cura formulas are parsed and restricted to plain expressions with a fixed set of helper functions before evaluation.
- **Backups (`.slicerpack`) from strangers.** Paths inside a backup are checked so a restore cannot write outside the slicer's settings folders, and every file is compared with its checksum. A backup can still contain a *plug-in* or a start G-code you did not expect: look at the item list before restoring someone else's backup.
- **Plug-ins.** SlicerSwap does not run a plug-in; it hands it to Cura. Once Cura loads it, the plug-in is a program with your user rights. SlicerSwap checks for one known *fault* (an icon that crashes Cura); that is not a safety check, and it cannot tell a harmful plug-in from a harmless one. Only install plug-ins from people you trust.
- **Secrets.** Backups leave out passwords, API keys and account logins unless you untick that option. If you find a secret that still ends up in a default backup, please report it.

SlicerSwap never uses the network.
