@echo off
rem Sends bill reminders and Monday summaries. Schedule this daily in Task Scheduler.
cd /d "%~dp0"
call venv\Scripts\activate.bat
python scripts\send_notifications.py >> notifications.log 2>&1
