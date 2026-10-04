@echo off
rem One-click start for Windows: makes a private Python environment the first time, installs, opens the lead desk.
cd /d "%~dp0"
if not exist .venv (
  echo First run: setting up, this takes a minute...
  python -m venv .venv || (echo Python 3.11+ is needed: https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
if not exist .env (
  copy .env.example .env >nul
  echo.
  echo A file called .env was created. Open it in Notepad, paste your keys, save it, then run start.bat again.
  echo The lead desk works without keys for browsing the sample leads, but "Find leads" needs them.
  echo.
)
start "" http://127.0.0.1:8765/
.venv\Scripts\python -m app --port 8765
pause
