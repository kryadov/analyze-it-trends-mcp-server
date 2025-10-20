@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM Change to the directory of this script
cd /d "%~dp0"

REM Detect Python launcher or python
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PYLAUNCH=py"
) else (
  set "PYLAUNCH=python"
)

REM Create a virtual environment if it does not exist
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment (.venv)
  %PYLAUNCH% -m venv .venv
)

REM Activate the virtual environment
call ".venv\Scripts\activate.bat"

REM Upgrade pip and install dependencies
python -m pip install --upgrade pip
if exist "requirements.txt" (
  python -m pip install -r requirements.txt
)

REM Create .env from example if missing
if not exist ".env" (
  if exist ".env.example" (
    copy /Y ".env.example" ".env" >nul
    echo Created .env from .env.example. Please review and edit credentials as needed.
  )
)

REM Run the MCP server (stdio)
python server.py

endlocal
