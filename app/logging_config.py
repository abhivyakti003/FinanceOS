"""Logging: readable lines to the console and a rotating file in logs/.

Never log passwords, OTP codes, API keys or transaction details.
"""

import logging
import logging.handlers
import os

from app.config import PROJECT_ROOT

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    log_dir = PROJECT_ROOT / "logs"
    try:
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / "financeos.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        root.warning("Couldn't create logs folder; logging to console only.")

    for noisy in ("alembic.runtime.migration", "urllib3", "matplotlib", "pdfminer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _configured = True
