@echo off
cd /d "%~dp0"
title FinanceOS
if not exist venv\Scripts\activate.bat (
  echo  Run setup.bat first.
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
streamlit run streamlit_app.py
