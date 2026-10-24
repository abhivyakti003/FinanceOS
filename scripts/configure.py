"""Create or update the .env settings file.

Run from the project folder:
    python scripts/configure.py

Sets up the account that SENDS verification codes and reminders.
Users of the app can still sign up with any email address.
"""

import getpass
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
EMAIL_RE = r"[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}"


def read_env() -> dict:
    values = {}
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def ask_email(prompt: str, current: str = "") -> str:
    shown = f"{prompt} [{current}]: " if current else f"{prompt}: "
    while True:
        value = input(shown).strip() or current
        if re.fullmatch(EMAIL_RE, value or ""):
            return value
        print("  That doesn't look like an email address. Try again.")


def ask_secret(prompt: str, current: str = "") -> str:
    keep = " (press Enter to keep the current one)" if current else ""
    while True:
        value = getpass.getpass(f"{prompt}, hidden while typing{keep}: ").replace(" ", "") or current
        if value:
            return value
        print("  This can't be empty.")


def main() -> None:
    print("\nFinanceOS email setup")
    print("=" * 44)
    print("FinanceOS needs one account to SEND sign-up codes and reminders.")
    print("Your users can sign up with ANY email; this is only the sender.\n")
    print("  1. Gmail  (needs an App Password; may be blocked on office/college Wi-Fi)")
    print("  2. Brevo  (free, sends over the normal web port, works on most networks)\n")

    env = read_env()
    default = "2" if env.get("EMAIL_PROVIDER") == "brevo" else "1"
    choice = input(f"Choose 1 or 2 [{default}]: ").strip() or default

    if choice == "2":
        print("\nBrevo setup: sign up at brevo.com, add and verify your sender email under")
        print("Senders, then create a key under SMTP & API -> API Keys.\n")
        sender = ask_email("Verified sender email", parse_from(env.get("SMTP_FROM", "")))
        api_key = ask_secret("Brevo API key", env.get("BREVO_API_KEY", ""))
        env.update({"EMAIL_PROVIDER": "brevo", "BREVO_API_KEY": api_key, "SMTP_FROM": f"FinanceOS <{sender}>"})
    else:
        print("\nGmail App Password:")
        print("  Turn on 2-Step Verification: https://myaccount.google.com/security")
        print("  Create an App Password:      https://myaccount.google.com/apppasswords\n")
        address = ask_email("Sender Gmail address", env.get("SMTP_USERNAME", ""))
        password = ask_secret("App Password (16 letters)", env.get("SMTP_PASSWORD", ""))
        env.update(
            {
                "EMAIL_PROVIDER": "smtp",
                "SMTP_HOST": "smtp.gmail.com",
                "SMTP_PORT": "587",
                "SMTP_USERNAME": address,
                "SMTP_PASSWORD": password,
                "SMTP_FROM": f"FinanceOS <{address}>",
            }
        )

    if "ADMIN_EMAILS" not in env:
        admin = input("\nYour own email, to make you the app admin (Enter to skip): ").strip().lower()
        if re.fullmatch(EMAIL_RE, admin):
            env["ADMIN_EMAILS"] = admin

    env.setdefault("SECRET_KEY", secrets.token_hex(32))
    if not env["SECRET_KEY"]:
        env["SECRET_KEY"] = secrets.token_hex(32)
    env["EMAIL_DEV_MODE"] = "false"
    env.setdefault("EMAIL_CHECK_DELIVERABILITY", "true")
    env.setdefault("OTP_EXPIRY_MINUTES", "10")
    env.setdefault("AA_PROVIDER", "mock")
    if env.get("DATABASE_URL") == "sqlite:///financeos.db":
        env.pop("DATABASE_URL")  # the app finds its database in the project folder by itself

    ENV.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n", encoding="utf-8")
    print(f"\nSaved settings to {ENV}")

    target = input("\nSend a test email? Type an address you can check (or press Enter to skip): ").strip()
    if target:
        sys.path.insert(0, str(ROOT))
        from app.services import email_service

        try:
            email_service.send_email(target, "FinanceOS test email", "Your FinanceOS email is working.")
            print(f"Sent. Check {target} (and the spam folder).")
        except Exception as exc:
            print(f"\nCouldn't send: {exc}")
            print("Run this again to fix the settings: python scripts\\configure.py")


def parse_from(value: str) -> str:
    match = re.search(r"<([^>]+)>", value or "")
    return match.group(1) if match else (value or "")


if __name__ == "__main__":
    main()
