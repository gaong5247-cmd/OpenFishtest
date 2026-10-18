@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 (
  echo Python 3 launcher was not found. Install Python 3.10+ for Windows.
  pause
  exit /b 1
)
where git >nul 2>&1
if errorlevel 1 (
  echo Git is required for automatic GitHub PR submission.
  echo Install Git for Windows; do not download executables from unknown sources.
  pause
  exit /b 1
)
where gh >nul 2>&1
if errorlevel 1 (
  echo GitHub CLI gh was not found.
  echo Install GitHub CLI and sign in once using: gh auth login
  pause
  exit /b 1
)
py -3 -c "import chess" >nul 2>&1
if errorlevel 1 (
  echo Installing python-chess for legal PGN and opening book validation...
  py -3 -m pip install -r requirements.txt
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
echo Starting OpenFishtest one-click Contributor...
py -3 contributor_gui.py
if errorlevel 1 pause
endlocal
