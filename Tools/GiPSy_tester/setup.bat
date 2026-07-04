@echo off
REM One-time setup: create a local .venv and install pinned deps.
REM Double-click this once before using run.bat. Re-running is safe.
setlocal
cd /d "%~dp0"

REM Prefer the py launcher (ships with python.org installers), fall
REM back to python on PATH.
REM Note: use `if errorlevel` (runtime) not `if %errorlevel%==0`: the
REM latter is expanded when the whole if/else block is parsed, so a
REM nested check would see the previous command's result, not `where`'s.
where py >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
) else (
    where python >nul 2>nul
    if not errorlevel 1 (
        set "PY=python"
    ) else (
        echo.
        echo ERROR: Python 3 was not found.
        echo Install it from https://www.python.org/downloads/ and be sure
        echo to tick "Add python.exe to PATH", then run this again.
        echo.
        pause
        exit /b 1
    )
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment in .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo ERROR: failed to create the virtual environment.
        pause
        exit /b 1
    )
)

echo Installing requirements ...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo ERROR: failed to install requirements.
    pause
    exit /b 1
)

echo.
echo Setup complete. You can now start the tool with run.bat
echo.
pause
