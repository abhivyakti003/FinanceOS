"""Create or upgrade the database to the latest schema.

Run once after installing, and again after pulling code that changes tables:
    python -m app.database.init_db

To change a table later:
    1. Edit app/database/models.py
    2. alembic revision --autogenerate -m "describe the change"
    3. python -m app.database.init_db
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[2]


def upgrade_database() -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")


if __name__ == "__main__":
    upgrade_database()
    print("Database is up to date.")
