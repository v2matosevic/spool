@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  python -m venv .venv
  if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import flask, waitress, yt_dlp, curl_cffi, webview, mcp" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto failed
)
if not exist ".spotify-venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" scripts\setup_spotify.py
  if errorlevel 1 goto failed
)
".venv\Scripts\pythonw.exe" launch.pyw
exit /b 0
:failed
echo Spool setup failed. Python 3.10 or newer is required. See README.md.
pause
exit /b 1
