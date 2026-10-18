@echo off
setlocal
cd /d "%~dp0"
where gh >nul 2>&1
if errorlevel 1 (
  echo GitHub CLI is missing. Install it from https://cli.github.com/
  pause
  exit /b 1
)
gh auth status >nul 2>&1
if errorlevel 1 (
  echo Please run gh auth login once in PowerShell.
  pause
  exit /b 1
)
where git >nul 2>&1
if errorlevel 1 (
  echo Git is required for normal Contributor PR publishing.
  echo Install Git for Windows if not already present.
  pause
  exit /b 1
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import chess" >nul 2>&1
  if errorlevel 1 (
    echo Installing chess PGN parser into the local Python environment...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
      pause
      exit /b 1
    )
  )
  echo Starting OpenFishtest with the current venv...
  ".venv\Scripts\python.exe" contributor_gui.py
) else (
  where py >nul 2>&1
  if errorlevel 1 (
    echo Python 3 is required.
    pause
    exit /b 1
  )
  py -3 -c "import chess" >nul 2>&1
  if errorlevel 1 (
    echo Installing chess PGN parser...
    py -3 -m pip install -r requirements.txt
    if errorlevel 1 (
      pause
      exit /b 1
    )
  )
  echo Starting OpenFishtest Contributor...
  py -3 contributor_gui.py
)
if errorlevel 1 pause
endlocal
