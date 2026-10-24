"""Tests run against a throwaway SQLite database, never your real data."""

import os
import tempfile
from datetime import date

# Set TEST_DATABASE_URL to run the tests against PostgreSQL instead.
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_tmp.name}"
os.environ["SECRET_KEY"] = "test-secret"
os.environ["EMAIL_DEV_MODE"] = "false"
os.environ["EMAIL_CHECK_DELIVERABILITY"] = "false"  # no DNS lookups in tests

import pytest  # noqa: E402

from app.database import models  # noqa: E402,F401
from app.database.db import Base, engine  # noqa: E402
from app.services import auth_service, email_service  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def outbox(monkeypatch):
    """Captures OTP emails instead of sending them."""
    sent = []

    def fake_send(to, code, purpose):
        sent.append({"to": to, "code": code, "purpose": purpose})

    monkeypatch.setattr(email_service, "send_otp_email", fake_send)
    return sent


@pytest.fixture
def make_user(outbox):
    counter = {"n": 0}

    def _make(email=None, password="Secret123"):  # noqa: S107  (test password)
        counter["n"] += 1
        email = email or f"user{counter['n']}@gmail.com"
        auth_service.start_registration(f"User {counter['n']}", email, password, accepted_terms=True)
        return auth_service.verify_registration(email, outbox[-1]["code"])

    return _make


@pytest.fixture
def user(make_user):
    return make_user()


@pytest.fixture
def bank(user):
    from app.services.account_service import create_account

    return create_account(user.id, "HDFC Savings", "Savings Account", 10000)


def d(y, m, day):
    return date(y, m, day)
