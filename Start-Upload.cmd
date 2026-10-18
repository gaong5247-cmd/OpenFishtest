@echo off
setlocal
cd /d "%~dp0"
where gh >nul 2>&1
if errorlevel 1 (
  echo GitHub CLI is missing. Install gh from https://cli.github.com/
  pause
  exit /b 1
)
gh auth status >nul 2>&1
if errorlevel 1 (
  echo Run gh auth login once in PowerShell, then start this again.
  pause
  exit /b 1
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" local_upload_server.py
) else (
  where py >nul 2>&1
  if errorlevel 1 (
    echo Python 3 is required.
    pause
    exit /b 1
  )
  py -3 local_upload_server.py
)
if errorlevel 1 (
  echo Upload helper could not start. Check localhost port 8765.
  pause
)
endlocal
