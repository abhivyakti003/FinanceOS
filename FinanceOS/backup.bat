@echo off
rem Backs up the database to the backups folder. Schedule daily in Task Scheduler.
cd /d "%~dp0"
call venv\Scripts\activate.bat
python scripts\backup.py >> backups.log 2>&1
