@echo off
REM One-time setup: create a local .venv and install pinned deps.
REM Double-click this once before using run.bat. Re-running is safe.
setlocal
cd /d "%~dp0"

REM Prefer the py launcher (ships with python.org installers), fall
REM back to python on PATH. Being on PATH isn't enough to trust it --
REM some machines have a stale `py` registration left over from a
REM removed/reinstalled Python that resolves to a path that no longer
REM exists (seen as "did not find executable at 'C:\Python.exe'"), so
REM actually run --version rather than just `where`-checking it.
REM Note: use `if errorlevel` (runtime) not `if %errorlevel%==0`: the
REM latter is expanded when the whole if/else block is parsed, so a
REM nested check would see the previous command's result, not the
REM version check's.
py -3 --version >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
) else (
    python --version >nul 2>nul
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

REM If a previous run created .venv with a broken interpreter (e.g. the
REM stale `py` launcher above), python.exe exists on disk but won't
REM actually run -- wipe and recreate rather than limping along on it.
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" --version >nul 2>nul
    if errorlevel 1 (
        echo Existing .venv looks broken, recreating it ...
        rmdir /s /q ".venv"
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
