@echo off
setlocal
cd /d "%~dp0"
if exist "D:\CodexCache\tmp\" (
    set "TEMP=D:\CodexCache\tmp"
    set "TMP=D:\CodexCache\tmp"
)
if exist "D:\CodexCache\pip\" set "PIP_CACHE_DIR=D:\CodexCache\pip"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import PIL" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -X utf8 cli.py list >nul 2>&1
if not errorlevel 1 (
    start "" "http://127.0.0.1:18764"
    exit /b 0
)
".venv\Scripts\python.exe" -X utf8 app.py --open
if not errorlevel 1 exit /b 0
:failed
pause
exit /b 1
