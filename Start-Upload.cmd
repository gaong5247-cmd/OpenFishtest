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
  echo Run gh auth login in PowerShell once then start again.
  pause
  exit /b 1
)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import chess" >nul 2>&1
  if errorlevel 1 (
    echo Installing PGN parser into the local Python environment...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
      pause
      exit /b 1
    )
  )
  ".venv\Scripts\python.exe" local_upload_server.py
) else (
  where py >nul 2>&1
  if errorlevel 1 (
    echo Python 3 is required.
    pause
    exit /b 1
  )
  py -3 -c "import chess" >nul 2>&1
  if errorlevel 1 (
    echo Installing PGN parser...
    py -3 -m pip install -r requirements.txt
    if errorlevel 1 (
      pause
      exit /b 1
    )
  )
  py -3 local_upload_server.py
)
if errorlevel 1 (
  echo Could not start. Another instance may be on 127.0.0.1 port 8765.
  pause
)
endlocal
