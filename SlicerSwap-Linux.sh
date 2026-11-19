#!/bin/sh
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#
# SlicerSwap launcher for Linux. Double-click it and choose "Run" (or "Run in Terminal").
# Give it files/options to use the command line instead:  ./SlicerSwap-Linux.sh --help
cd "$(dirname "$0")" || exit 1

say() {   # show a message even when started without a terminal
    if [ -t 1 ]; then
        printf '%s\n' "$1"
    elif command -v zenity >/dev/null 2>&1; then
        zenity --info --no-wrap --title="SlicerSwap" --text="$1" 2>/dev/null
    elif command -v kdialog >/dev/null 2>&1; then
        kdialog --title "SlicerSwap" --msgbox "$1"
    elif command -v xmessage >/dev/null 2>&1; then
        xmessage -center "$1"
    else
        printf '%s\n' "$1"
    fi
}

# Find a Python 3.8+; prefer one that has tkinter (a computer can have several, and only some have it).
PY=""
PY_ANY=""
HAVE_TK=""
for cand in python3 python3.14 python3.13 python3.12 python3.11 python3.10 python3.9 python3.8 python; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
        [ -z "$PY_ANY" ] && PY_ANY="$cand"
        if "$cand" -c 'import tkinter' 2>/dev/null; then
            PY="$cand"
            HAVE_TK=1
            break
        fi
    fi
done
[ -z "$PY" ] && PY="$PY_ANY"
if [ -z "$PY" ]; then
    say "SlicerSwap needs Python 3.8 or newer, which was not found.

Linux Mint / Ubuntu / Debian:  sudo apt install python3 python3-tk
Fedora:                        sudo dnf install python3 python3-tkinter
Arch / Manjaro:                sudo pacman -S python tk"
    exit 1
fi

# with arguments: plain command line
if [ "$#" -gt 0 ]; then
    exec "$PY" -m slicerswap "$@"
fi

if [ -n "$HAVE_TK" ]; then
    exec "$PY" -m slicerswap
fi

# no tkinter: say how to get the window, and fall back to text mode
MSG="The SlicerSwap window needs Python's tkinter, which is not installed.

Linux Mint / Ubuntu / Debian:  sudo apt install python3-tk
Fedora:                        sudo dnf install python3-tkinter
Arch / Manjaro:                sudo pacman -S tk

Until then SlicerSwap works in text mode from a terminal:
  ./SlicerSwap-Linux.sh list
  ./SlicerSwap-Linux.sh --help"
if [ -t 1 ]; then
    printf '%s\n\n' "$MSG"
    echo "Text mode - slicers found on this computer:"
    echo
    "$PY" -m slicerswap list
    echo
    printf 'Press Enter to close. '
    read -r _
else
    say "$MSG"
fi
exit 1
