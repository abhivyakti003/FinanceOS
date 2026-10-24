import json
import smtplib
import sqlite3
from datetime import date

import pytest

from app import config
from app.database.db import normalize_url
from app.services import (
    account_service,
    admin_service,
    auth_service,
    backup_service,
    email_service,
)
from app.services import (
    transaction_service as ts,
)
from app.services.admin_service import AdminError
from app.services.auth_service import AuthError

# ---- Database URL handling ---------------------------------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///x.db", "sqlite:///x.db"),
    ],
)
def test_normalize_url(given, expected):
    assert normalize_url(given) == expected


def test_many_users_data_kept_apart(make_user):
    users = [make_user() for _ in range(5)]
    for i, u in enumerate(users):
        acct = account_service.create_account(u.id, "Bank", "Savings Account", 0)
        for _ in range(i + 1):
            ts.add_transaction(u.id, acct.id, date.today(), 100, "debit", description="tea")
    for i, u in enumerate(users):
        assert len(ts.list_transactions(u.id)) == i + 1


# ---- Admin ---------------------------------------------------------------


@pytest.fixture
def admin(make_user, monkeypatch):
    user = make_user("boss@gmail.com")
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"boss@gmail.com"})
    return user


def test_only_admins_get_admin_data(admin, make_user):
    normal = make_user()
    assert admin_service.is_admin(admin) and not admin_service.is_admin(normal)
    with pytest.raises(AdminError):
        admin_service.list_users(normal.id)
    stats = admin_service.platform_stats(admin.id)
    assert stats["users"] == 2
    listed = admin_service.list_users(admin.id)
    assert {"name", "email", "transactions"} <= set(listed[0])
    assert "balance" not in listed[0]  # admins never see money


def test_disable_blocks_login(admin, make_user):
    victim = make_user("v@gmail.com")
    admin_service.set_active(admin.id, victim.id, False)
    with pytest.raises(AuthError, match="disabled"):
        auth_service.authenticate("v@gmail.com", "Secret123")
    admin_service.set_active(admin.id, victim.id, True)
    assert auth_service.authenticate("v@gmail.com", "Secret123").last_login_at is not None
    with pytest.raises(AdminError):
        admin_service.set_active(admin.id, admin.id, False)


def test_admin_delete_user(admin, make_user):
    victim = make_user("del@gmail.com")
    account_service.create_account(victim.id, "Bank", "Savings Account", 10)
    admin_service.delete_user(admin.id, victim.id)
    assert auth_service.get_user(victim.id) is None
    assert account_service.list_accounts(victim.id) == []


# ---- Backups -------------------------------------------------------------


def test_sqlite_backup(user, tmp_path, monkeypatch):
    from app.database.db import IS_SQLITE

    if not IS_SQLITE:
        pytest.skip("SQLite only")
    monkeypatch.setattr(backup_service, "BACKUP_DIR", tmp_path)
    path = backup_service.create_backup()
    con = sqlite3.connect(path)
    assert con.execute("select count(*) from users").fetchone()[0] == 1
    con.close()
    for _ in range(3):
        backup_service.create_backup()
    assert backup_service.prune(keep=2) >= 0
    assert len(backup_service.list_backups()) <= max(2, config.BACKUP_KEEP)


# ---- Email sending -----------------------------------------------------------


def _configure(monkeypatch, **values):
    base = dict(
        EMAIL_DEV_MODE=False,
        EMAIL_PROVIDER="smtp",
        SMTP_HOST="smtp.gmail.com",
        SMTP_PORT=587,
        SMTP_USE_SSL=False,
        SMTP_USERNAME="a@gmail.com",
        SMTP_PASSWORD="x",
        SMTP_FROM="FinanceOS <a@gmail.com>",
    )
    base.update(values)
    for key, value in base.items():
        monkeypatch.setattr(config, key, value)


def test_gmail_falls_back_to_port_465(monkeypatch):
    _configure(monkeypatch)
    sent = []

    class Blocked:
        def __init__(self, *a, **k):
            raise TimeoutError("handshake timed out")

    class Works:
        def __init__(self, host, port, **k):
            self.port = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, *a):
            pass

        def send_message(self, msg):
            sent.append((self.port, msg["To"]))

    monkeypatch.setattr(smtplib, "SMTP", Blocked)
    monkeypatch.setattr(smtplib, "SMTP_SSL", Works)
    email_service.send_email("x@gmail.com", "hi", "body")
    assert sent == [(465, "x@gmail.com")]


def test_blocked_network_gives_clear_message(monkeypatch):
    _configure(monkeypatch)

    class Blocked:
        def __init__(self, *a, **k):
            raise TimeoutError("timed out")

    monkeypatch.setattr(smtplib, "SMTP", Blocked)
    monkeypatch.setattr(smtplib, "SMTP_SSL", Blocked)
    with pytest.raises(email_service.EmailSendError, match="blocking email ports"):
        email_service.send_email("x@gmail.com", "hi", "body")


def test_wrong_app_password_message(monkeypatch):
    _configure(monkeypatch)

    class BadLogin:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **k):
            pass

        def login(self, *a):
            raise smtplib.SMTPAuthenticationError(535, b"bad")

    monkeypatch.setattr(smtplib, "SMTP", BadLogin)
    with pytest.raises(email_service.EmailSendError, match="App Password"):
        email_service.send_email("x@gmail.com", "hi", "body")


def test_brevo_request(monkeypatch):
    _configure(monkeypatch, EMAIL_PROVIDER="brevo", BREVO_API_KEY="key123")
    captured = {}

    class Resp:
        def read(self):
            return b"{}"

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["key"] = request.headers["Api-key"]
        captured["body"] = json.loads(request.data)
        return Resp()

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    email_service.send_email("x@gmail.com", "Code", "123456")
    assert captured["url"].endswith("/v3/smtp/email")
    assert captured["key"] == "key123"
    assert captured["body"]["sender"]["email"] == "a@gmail.com"
    assert captured["body"]["to"] == [{"email": "x@gmail.com"}]


# ---- Atomic operations and audit log ---------------------------------------


def test_bill_payment_is_atomic(user, bank, monkeypatch):
    """If recording the transaction fails, the bill must not be marked paid."""
    from datetime import timedelta

    from app.services import bill_service, transaction_service

    bill = bill_service.add_bill(user.id, "Rent", 20000, date.today() + timedelta(days=3), "Monthly", "Rent")

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(transaction_service, "add_transaction", boom)
    with pytest.raises(RuntimeError):
        bill_service.mark_paid(user.id, bill.id, record_transaction=True, account_id=bank.id)
    after = bill_service.list_bills(user.id)[0]
    assert after.next_due_date == bill.next_due_date and after.last_paid_date is None


def test_statement_import_is_atomic(user, bank, monkeypatch):
    from pathlib import Path

    from app.services import account_service as acc
    from app.services import import_service

    parsed = import_service.parse_statement(
        (Path(__file__).resolve().parents[1] / "samples" / "hdfc_style_statement.csv").read_bytes(), "s.csv"
    )

    def boom(*a, **k):
        raise RuntimeError("crash while updating balance")

    monkeypatch.setattr(import_service, "set_current_balance", boom)
    with pytest.raises(RuntimeError):
        import_service.import_statement(user.id, bank.id, parsed)
    assert ts.list_transactions(user.id) == []  # nothing half-saved
    assert acc.account_balances(user.id)[bank.id] == 10000


def test_audit_log_records_security_events(make_user):
    from app.services import audit_service

    u = make_user("audit@gmail.com")
    with pytest.raises(AuthError):
        auth_service.authenticate("audit@gmail.com", "Wrong1234")
    auth_service.authenticate("audit@gmail.com", "Secret123")
    auth_service.change_password(u.id, "Secret123", "Newpass123")
    events = [e.event for e in audit_service.for_user(u.id)]
    assert {"register", "login_failed", "login_success", "password_changed"} <= set(events)


def test_production_settings_validation(monkeypatch):
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "EMAIL_DEV_MODE", True)
    errors, _ = config.validate_settings()
    assert any("EMAIL_DEV_MODE" in e for e in errors)
