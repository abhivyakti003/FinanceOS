"""Application settings, loaded from environment variables or a .env file.

Copy `.env.example` to `.env` and fill in the values. Never commit `.env`.
"""

import os
import secrets
import warnings
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
load_dotenv(ENV_FILE)


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


APP_NAME = "FinanceOS"
APP_VERSION = "1.0.0"

# "development" on your laptop, "production" on a server. Production refuses
# to start with unsafe settings (see validate_settings below).
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

# Shown in emails and the Privacy Policy.
SUPPORT_EMAIL = os.getenv("SUPPORT_EMAIL", "")
CURRENCY_SYMBOL = "₹"

# Default database lives in the project folder, wherever you start the app from.
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{(PROJECT_ROOT / 'financeos.db').as_posix()}"

# Used to hash OTP codes. Must be set in production so codes survive restarts.
SECRET_KEY = os.getenv("SECRET_KEY") or ""
_SECRET_KEY_MISSING = not SECRET_KEY
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    warnings.warn(
        "SECRET_KEY is not set. A temporary key is being used, so pending "
        "OTP codes will stop working after a restart. Run setup.bat (or "
        "python scripts/configure.py) to create your .env file.",
        stacklevel=1,
    )

# ---- Email / SMTP -------------------------------------------------------
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = _int("SMTP_PORT", 587)
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USERNAME)
SMTP_USE_SSL = _bool("SMTP_USE_SSL", SMTP_PORT == 465)

# Development only: print OTP emails to the server console instead of sending.
EMAIL_DEV_MODE = _bool("EMAIL_DEV_MODE", False)

# "smtp" (Gmail etc.) or "brevo" (sends over HTTPS; works where email ports are blocked)
EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "smtp").strip().lower()
BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
SMTP_TIMEOUT = _int("SMTP_TIMEOUT", 15)

# Check that the email's domain can actually receive mail (DNS MX lookup).
EMAIL_CHECK_DELIVERABILITY = _bool("EMAIL_CHECK_DELIVERABILITY", True)

# ---- OTP rules ----------------------------------------------------------
OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = _int("OTP_EXPIRY_MINUTES", 10)
OTP_MAX_ATTEMPTS = 5  # wrong guesses allowed per code
OTP_RESEND_COOLDOWN_SECONDS = 60
OTP_MAX_PER_HOUR = 5  # codes sent to one email per hour

# ---- Admin ---------------------------------------------------------------
# Comma-separated emails that can open the Admin page (user list and stats).
ADMIN_EMAILS = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}

# Log users out after this many minutes without activity.
SESSION_TIMEOUT_MINUTES = _int("SESSION_TIMEOUT_MINUTES", 30)

# Automatic backups kept by scripts/backup.py
BACKUP_KEEP = _int("BACKUP_KEEP", 14)

# ---- Login protection ---------------------------------------------------
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15


def validate_settings() -> tuple[list[str], list[str]]:
    """Return (errors, warnings). In production, errors stop the app from starting."""
    errors: list[str] = []
    warns: list[str] = []
    provider_ready = (
        bool(BREVO_API_KEY and SMTP_FROM)
        if EMAIL_PROVIDER == "brevo"
        else bool(SMTP_HOST and SMTP_USERNAME and SMTP_PASSWORD)
    )
    if IS_PRODUCTION:
        if _SECRET_KEY_MISSING or len(SECRET_KEY) < 32:
            errors.append("SECRET_KEY must be set to a random value of at least 32 characters.")
        if EMAIL_DEV_MODE:
            errors.append("EMAIL_DEV_MODE must be false in production.")
        if not provider_ready:
            errors.append("Email sending isn't configured (SMTP or Brevo settings).")
        if DATABASE_URL.startswith("sqlite"):
            warns.append("Using SQLite. PostgreSQL is recommended for production.")
        if not ADMIN_EMAILS:
            warns.append("ADMIN_EMAILS is empty, so nobody can open the Admin page.")
        if not SUPPORT_EMAIL:
            warns.append("SUPPORT_EMAIL is empty; set it so users can contact you.")
    else:
        if _SECRET_KEY_MISSING:
            warns.append("SECRET_KEY isn't set. Run python scripts/configure.py.")
        if not provider_ready and not EMAIL_DEV_MODE:
            warns.append("Email isn't configured, so sign-up codes can't be sent.")
    return errors, warns
