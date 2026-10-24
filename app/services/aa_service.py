"""Account Aggregator (AA) integration.

Real AA data needs either your own FIU registration or a partner such as
Setu, Finvu, OneMoney or Perfios, who give you sandbox and production keys.
Until you have those, `MockAAProvider` returns realistic sample data so you
can build and test the whole flow: consent -> fetch -> accounts and
transactions appear, categorised, in the app.

To go live, fill in `SetuAAProvider` (or write a class for your partner) and
set AA_PROVIDER=setu in .env. Nothing else in the app needs to change.
"""

import os
import random
import re
import uuid
from abc import ABC, abstractmethod
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.database.db import get_session
from app.database.models import AAConsent, Account, utcnow
from app.services.account_service import create_account, set_current_balance
from app.services.transaction_service import bulk_import

AA_TYPE_MAP = {
    "SAVINGS": "Savings Account",
    "CURRENT": "Current Account",
    "CREDIT_CARD": "Credit Card",
}


class AAError(ValueError):
    pass


class AAProvider(ABC):
    name = "base"

    @abstractmethod
    def create_consent(self, mobile: str) -> dict:
        """Start a consent request. Returns {"consent_handle": str, "redirect_url": str | None}."""

    @abstractmethod
    def consent_status(self, consent_handle: str) -> str:
        """Returns PENDING, ACTIVE, REJECTED, REVOKED or EXPIRED."""

    @abstractmethod
    def fetch_accounts(self, consent_handle: str) -> list[dict]:
        """Returns a list of accounts:
        {"institution", "masked_number", "type" (SAVINGS|CURRENT|CREDIT_CARD),
         "balance": Decimal, "transactions": [{"txn_date", "amount", "txn_type",
         "narration", "reference_id", "balance"}]}
        """


class MockAAProvider(AAProvider):
    """Sample data for development. Every consent is approved instantly."""

    name = "mock"

    def create_consent(self, mobile: str) -> dict:
        return {"consent_handle": f"mock-{uuid.uuid4().hex[:12]}", "redirect_url": None}

    def consent_status(self, consent_handle: str) -> str:
        return "ACTIVE"

    def fetch_accounts(self, consent_handle: str) -> list[dict]:
        today = date.today()
        start = today - timedelta(days=120)
        txns = []
        balance = Decimal("48000.00")

        def add(d, amount, kind, narration):
            nonlocal balance
            amount = Decimal(str(amount)).quantize(Decimal("0.01"))
            balance += amount if kind == "credit" else -amount
            txns.append(
                {
                    "txn_date": d,
                    "amount": amount,
                    "txn_type": kind,
                    "narration": narration,
                    "reference_id": None,
                    "balance": None,
                }
            )

        d = start
        while d <= today:
            # Seeded by consent + date, so re-syncing produces identical rows (deduped).
            rng = random.Random(f"{consent_handle}-{d.isoformat()}")
            rrn = lambda rng=rng: str(rng.randint(10**11, 10**12 - 1))  # noqa: E731
            if d.day == 1:
                add(d, 85000, "credit", "NEFT CR-ACME TECHNOLOGIES PVT LTD-SALARY FOR MONTH")
            if d.day == 3:
                add(d, 22000, "debit", f"UPI/DR/{rrn()}/Ramesh Kumar/SBIN/rameshk@oksbi/Rent")
            if d.day == 5:
                add(d, 649, "debit", f"UPI/DR/{rrn()}/NETFLIX/HDFC/netflix@hdfcbank/Subscription")
            if d.day == 10:
                add(d, 5000, "debit", "ACH D- GROWW SIP-MUTUAL FUND")
            if d.day == 15:
                add(d, 1299, "debit", f"UPI/DR/{rrn()}/AIRTEL/YESB/airtel@ybl/Broadband")
            if rng.random() < 0.45:
                add(
                    d,
                    rng.choice([189, 245, 312, 420, 560]),
                    "debit",
                    f"UPI/DR/{rrn()}/SWIGGY/YESB/swiggy.stores@ybl/Food",
                )
            if rng.random() < 0.25:
                add(d, rng.choice([140, 220, 310, 480]), "debit", f"UPI/DR/{rrn()}/UBER INDIA/ICIC/uber@icici/Ride")
            if rng.random() < 0.12:
                add(d, rng.choice([899, 1499, 2399, 3999]), "debit", f"UPI/DR/{rrn()}/AMAZON PAY/YESB/amazon@apl/Order")
            if rng.random() < 0.15:
                add(d, rng.choice([380, 650, 910]), "debit", f"UPI/DR/{rrn()}/BLINKIT/YESB/blinkit@ybl/Groceries")
            d += timedelta(days=1)

        return [
            {
                "institution": "HDFC Bank (sample)",
                "masked_number": "XXXXXX4321",
                "type": "SAVINGS",
                "balance": balance,
                "transactions": txns,
            }
        ]


class SetuAAProvider(AAProvider):
    """Skeleton for Setu's Account Aggregator API. Fill in with your sandbox keys.

    Docs: https://docs.setu.co/data/account-aggregator
    Typical flow:
      1. POST /consents with the user's mobile (+ purpose, date range, FI types)
         -> consent id + a URL where the user approves in their AA app.
      2. Poll GET /consents/{id} (or receive a webhook) until status is ACTIVE.
      3. POST /sessions to request data, then GET /sessions/{id} for FI data (JSON).
    """

    name = "setu"

    def __init__(self):
        self.base_url = os.getenv("SETU_AA_BASE_URL", "")
        self.client_id = os.getenv("SETU_CLIENT_ID", "")
        self.client_secret = os.getenv("SETU_CLIENT_SECRET", "")
        self.product_instance_id = os.getenv("SETU_PRODUCT_INSTANCE_ID", "")
        if not all([self.base_url, self.client_id, self.client_secret, self.product_instance_id]):
            raise AAError("Setu AA keys are missing. Add them to .env or use AA_PROVIDER=mock.")

    def create_consent(self, mobile: str) -> dict:
        raise NotImplementedError("Call Setu's create-consent API here.")

    def consent_status(self, consent_handle: str) -> str:
        raise NotImplementedError("Call Setu's get-consent API here.")

    def fetch_accounts(self, consent_handle: str) -> list[dict]:
        raise NotImplementedError("Create a data session and map the FI data into the dict format above.")


def get_provider() -> AAProvider:
    name = os.getenv("AA_PROVIDER", "mock").lower()
    if name == "setu":
        return SetuAAProvider()
    return MockAAProvider()


def is_mock() -> bool:
    return get_provider().name == "mock"


# ---------------------------------------------------------------------------
# App-level flow
# ---------------------------------------------------------------------------


def start_link(user_id: int, mobile: str) -> AAConsent:
    mobile = re.sub(r"\D", "", mobile or "")[-10:]
    if not re.fullmatch(r"[6-9]\d{9}", mobile):
        raise AAError("Enter the 10-digit mobile number linked to your bank account.")
    provider = get_provider()
    result = provider.create_consent(mobile)
    with get_session() as session:
        consent = AAConsent(
            user_id=user_id, provider=provider.name, consent_handle=result["consent_handle"], status="PENDING"
        )
        session.add(consent)
        session.flush()
        consent.redirect_url = result.get("redirect_url")  # not stored, only returned
        return consent


def list_consents(user_id: int) -> list[AAConsent]:
    with get_session() as session:
        return list(
            session.scalars(select(AAConsent).where(AAConsent.user_id == user_id).order_by(AAConsent.id.desc()))
        )


def sync_consent(user_id: int, consent_id: int) -> dict:
    """Check consent status and, if active, pull accounts and transactions."""
    provider = get_provider()
    with get_session() as session:
        consent = session.scalar(select(AAConsent).where(AAConsent.id == consent_id, AAConsent.user_id == user_id))
        if consent is None:
            raise AAError("Consent not found.")
        status = provider.consent_status(consent.consent_handle)
        consent.status = status
        handle = consent.consent_handle
    if status != "ACTIVE":
        return {"status": status, "accounts": 0, "inserted": 0, "skipped": 0}

    inserted = skipped = 0
    fi_accounts = provider.fetch_accounts(handle)
    for fi in fi_accounts:
        account_type = AA_TYPE_MAP.get(fi["type"], "Savings Account")
        # Each bank account is saved in one transaction: account, rows and balance together.
        with get_session() as session:
            account = session.scalar(
                select(Account).where(
                    Account.user_id == user_id,
                    Account.masked_number == fi["masked_number"],
                    Account.institution == fi["institution"],
                )
            )
            if account is None:
                account = create_account(
                    user_id,
                    f"{fi['institution']} {fi['masked_number'][-4:]}",
                    account_type,
                    0,
                    institution=fi["institution"],
                    masked_number=fi["masked_number"],
                    source="aa",
                    session=session,
                )
            counts = bulk_import(user_id, account.id, fi["transactions"], source="aa", session=session)
            inserted += counts["inserted"]
            skipped += counts["skipped"]
            balance = abs(fi["balance"]) if account_type == "Credit Card" else fi["balance"]
            set_current_balance(user_id, account.id, balance, session=session)

    with get_session() as session:
        consent = session.get(AAConsent, consent_id)
        consent.last_fetched_at = utcnow()
    return {"status": status, "accounts": len(fi_accounts), "inserted": inserted, "skipped": skipped}


def revoke_consent(user_id: int, consent_id: int) -> None:
    with get_session() as session:
        consent = session.scalar(select(AAConsent).where(AAConsent.id == consent_id, AAConsent.user_id == user_id))
        if consent is None:
            raise AAError("Consent not found.")
        consent.status = "REVOKED"
