@echo off
rem Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
rem Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
rem
rem SlicerSwap launcher for Windows. Double-click it.
rem Give it files/options to use the command line instead:  SlicerSwap-Windows.bat --help
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul && py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && python -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo SlicerSwap needs Python 3.8 or newer, which was not found.
    echo.
    echo Install it from https://www.python.org/downloads/
    echo In the installer tick "Add python.exe to PATH" and keep "tcl/tk and IDLE" ticked.
    echo Then double-click this file again.
    echo.
    pause
    exit /b 1
)

if not "%~1"=="" (
    %PY% -m slicerswap %*
    exit /b %errorlevel%
)

%PY% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo The SlicerSwap window needs tkinter, which this Python does not have.
    echo Run the Python installer again, choose Modify, and tick "tcl/tk and IDLE".
    echo.
    echo Text mode - slicers found on this computer:
    echo.
    %PY% -m slicerswap list
    echo.
    echo More: SlicerSwap-Windows.bat --help
    pause
    exit /b 1
)

%PY% -m slicerswap
if errorlevel 1 (
    echo.
    echo SlicerSwap stopped with an error. The messages above say why.
    pause
)
endlocal
