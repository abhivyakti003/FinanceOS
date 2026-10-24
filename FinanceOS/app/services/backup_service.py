"""Database backups.

SQLite: copies the database safely while the app is running (SQLite's own
backup method), into the backups/ folder, keeping the newest BACKUP_KEEP.
PostgreSQL: runs pg_dump (installed with PostgreSQL) into the same folder.

Restore a SQLite backup: stop the app, copy the backup file over
financeos.db, start the app.
Restore a PostgreSQL backup: pg_restore -d <database> <file.dump>
"""

import os
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from app import config
from app.database.db import DATABASE_URL, IS_SQLITE

BACKUP_DIR = config.PROJECT_ROOT / "backups"


class BackupError(RuntimeError):
    pass


def create_backup() -> Path:
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    url = make_url(DATABASE_URL)

    if IS_SQLITE:
        source_path = Path(url.database)
        if not source_path.exists():
            raise BackupError("The database file doesn't exist yet.")
        target = BACKUP_DIR / f"financeos-{stamp}.db"
        source = sqlite3.connect(str(source_path))
        dest = sqlite3.connect(str(target))
        try:
            with dest:
                source.backup(dest)
        finally:
            dest.close()
            source.close()
    else:
        pg_dump = shutil.which("pg_dump")
        if not pg_dump:
            raise BackupError("pg_dump wasn't found. Add PostgreSQL's bin folder to PATH.")
        target = BACKUP_DIR / f"financeos-{stamp}.dump"
        env = {"PGPASSWORD": url.password or ""}
        result = subprocess.run(  # noqa: S603  (fixed arguments from our own settings)
            [
                pg_dump,
                "-Fc",
                "-h",
                url.host or "localhost",
                "-p",
                str(url.port or 5432),
                "-U",
                url.username or "",
                "-f",
                str(target),
                url.database,
            ],
            env={**os.environ, **env},
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise BackupError(f"pg_dump failed: {result.stderr.strip()[:300]}")

    prune()
    from app.services import audit_service

    audit_service.record("backup_created", None, None, target.name)
    return target


def list_backups() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("financeos-*"), reverse=True)


def prune(keep: int | None = None) -> int:
    keep = keep or config.BACKUP_KEEP
    removed = 0
    for old in list_backups()[keep:]:
        old.unlink(missing_ok=True)
        removed += 1
    return removed
