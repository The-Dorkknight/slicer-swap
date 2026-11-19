#!/bin/bash
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#
# SlicerSwap launcher for macOS. Double-click it in Finder.
# The first time macOS may refuse because the file is not signed: right-click it, choose Open, then Open.
cd "$(dirname "$0")" || exit 1

# Find a Python 3.8+; prefer one that has tkinter (the python.org one does; Apple's and Homebrew's may not).
PY=""
PY_ANY=""
HAVE_TK=""
for cand in python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 /usr/bin/python3; do
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
    echo "SlicerSwap needs Python 3.8 or newer, which was not found."
    echo
    echo "Install it from https://www.python.org/downloads/ (the installer includes the window toolkit),"
    echo "then double-click this file again."
    echo
    read -r -p "Press Enter to close. " _
    exit 1
fi

if [ "$#" -gt 0 ]; then
    exec "$PY" -m slicerswap "$@"
fi

if [ -n "$HAVE_TK" ]; then
    "$PY" -m slicerswap
    status=$?
    if [ $status -ne 0 ]; then
        echo
        echo "SlicerSwap stopped with an error (code $status). The messages above say why."
        read -r -p "Press Enter to close. " _
    fi
    exit $status
fi

echo "The SlicerSwap window needs Python's tkinter, which this Python ($PY) does not have."
echo
echo "Install Python from https://www.python.org/downloads/ (it includes tkinter),"
echo "or with Homebrew:  brew install python-tk"
echo
echo "Text mode - slicers found on this computer:"
echo
"$PY" -m slicerswap list
echo
echo "More: $0 --help"
read -r -p "Press Enter to close. " _
exit 1
