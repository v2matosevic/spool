@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pip install --upgrade "yt-dlp[default]"
if errorlevel 1 (
  echo Update failed. Check your internet connection.
) else (
  echo Engine updated. The running app keeps its loaded version until restarted.
  echo This updater does not stop downloads or close the app.
)
pause
