@echo off
REM Launch the GiPSy Autopilot Tester using the local .venv.
REM Run setup.bat once first to create the environment.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo The environment isn't set up yet.
    echo Please run setup.bat once first, then try again.
    echo.
    pause
    exit /b 1
)

REM pythonw.exe = no extra console window behind the Tkinter GUI.
start "" ".venv\Scripts\pythonw.exe" run.py
