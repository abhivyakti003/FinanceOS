"""Back up the database into the backups/ folder.

    python scripts/backup.py

Schedule daily with backup.bat (Windows Task Scheduler) or cron.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.logging_config import setup_logging  # noqa: E402

setup_logging()

from app.services.backup_service import BackupError, create_backup, list_backups  # noqa: E402

if __name__ == "__main__":
    try:
        path = create_backup()
    except BackupError as exc:
        print(f"Backup failed: {exc}")
        sys.exit(1)
    print(f"Backup saved: {path}")
    print(f"{len(list_backups())} backup(s) kept in {path.parent}")
