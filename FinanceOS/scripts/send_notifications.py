"""Send bill reminders and (on Mondays) weekly summaries.

Run once a day, for example with Windows Task Scheduler pointing at notify.bat:
    python scripts/send_notifications.py
Add --weekly-now to send weekly summaries today regardless of the day.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.logging_config import setup_logging  # noqa: E402

setup_logging()

from app.database.init_db import upgrade_database  # noqa: E402
from app.services import notification_service  # noqa: E402


def main() -> None:
    upgrade_database()
    today = date.today()
    reminders = notification_service.send_bill_reminders(today)
    weekly = notification_service.send_weekly_summaries(today, force="--weekly-now" in sys.argv)
    print(f"{today}: {reminders} bill reminder(s), {weekly} weekly summary email(s) sent.")


if __name__ == "__main__":
    main()
