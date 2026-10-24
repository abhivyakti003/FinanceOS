"""Runs the daily jobs (reminder emails and database backup) in a loop.

Used by the `worker` service in docker-compose.yml. On Windows, use Task
Scheduler with notify.bat and backup.bat instead.

Settings: DAILY_JOBS_HOUR (0-23, server local time, default 8).
"""

import logging
import os
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.logging_config import setup_logging  # noqa: E402

setup_logging()
log = logging.getLogger("financeos.scheduler")

from app.database.init_db import upgrade_database  # noqa: E402
from app.services import backup_service, notification_service  # noqa: E402

HOUR = int(os.getenv("DAILY_JOBS_HOUR", "8"))


def run_daily_jobs(today: date) -> None:
    try:
        result = notification_service.run_daily(today)
        log.info("Notifications sent: %s", result)
    except Exception:
        log.exception("Notification job failed")
    try:
        path = backup_service.create_backup()
        log.info("Backup saved: %s", path.name)
    except Exception:
        log.exception("Backup job failed")


def main() -> None:
    upgrade_database()
    log.info("Scheduler started; daily jobs run at %02d:00", HOUR)
    last_run: date | None = None
    while True:
        now = datetime.now()
        if now.hour >= HOUR and last_run != now.date():
            run_daily_jobs(now.date())
            last_run = now.date()
        time.sleep(300)


if __name__ == "__main__":
    main()
