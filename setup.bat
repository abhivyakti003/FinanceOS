@echo off
cd /d "%~dp0"
title FinanceOS setup
echo.
echo  Setting up FinanceOS. This takes a few minutes the first time.
echo.

rem Prefer Python 3.12 or 3.13: every package has ready-made installers for them.
set "PY="
py -3.12 --version >nul 2>&1 && set "PY=py -3.12"
if not defined PY (py -3.13 --version >nul 2>&1 && set "PY=py -3.13")
if not defined PY (python --version >nul 2>&1 && set "PY=python")
if not defined PY (
  echo  Python was not found. Install Python 3.12 from https://www.python.org/downloads/
  echo  and tick "Add python.exe to PATH" on the first screen. Then run setup.bat again.
  pause
  exit /b 1
)
echo  Using:
%PY% --version

if not exist venv\Scripts\python.exe (
  %PY% -m venv venv || (echo  Could not create the virtual environment. & pause & exit /b 1)
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
echo  Installing packages...
pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo  Installing packages failed. If you have Python 3.14, install Python 3.12 from python.org,
  echo  delete the venv folder, and run setup.bat again.
  pause
  exit /b 1
)

if not exist .env python scripts\configure.py
python -m app.database.init_db
echo.
echo  All set. Double-click run.bat to start FinanceOS.
echo  To change the sender email later, run: python scripts\configure.py
pause
