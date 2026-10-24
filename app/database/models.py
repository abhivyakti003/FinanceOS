"""Database tables.

Key changes from the first version:
- Expense and Income are replaced by one `Transaction` table (debit/credit),
  which is how banks and the Account Aggregator framework report data.
- Every transaction belongs to an `Account`.
- Money uses Numeric(14, 2) instead of Float, so paise never get lost.
- Duplicate protection: the same bank transaction cannot be imported twice.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.db import Base

Money = Numeric(14, 2)


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Users and authentication
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    email_verified_at: Mapped[datetime] = mapped_column(DateTime)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # When the user accepted the Terms and Privacy Policy (DPDP Act consent).
    consented_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Notification preferences
    email_reminders: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    weekly_summary: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    last_weekly_summary_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EmailOTP(Base):
    """A one-time code sent to an email address.

    For registration, the account is NOT created until the code is verified.
    The name and hashed password wait here in the meantime.
    """

    __tablename__ = "email_otps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    purpose: Mapped[str] = mapped_column(String(20))  # "register" | "reset"
    code_hash: Mapped[str] = mapped_column(String(64))
    pending_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pending_password_hash: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Accounts and transactions
# ---------------------------------------------------------------------------


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    account_type: Mapped[str] = mapped_column(String(40))
    institution: Mapped[str | None] = mapped_column(String(100), nullable=True)
    masked_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Balance before the first recorded transaction. Current balance is
    # always opening_balance + credits - debits, so it can never drift.
    opening_balance: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | aa
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="account", cascade="all, delete-orphan", passive_deletes=True
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("account_id", "dedupe_hash", name="uq_txn_account_dedupe"),
        Index("ix_txn_user_date", "user_id", "txn_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)

    txn_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Money)  # always positive
    txn_type: Mapped[str] = mapped_column(String(6))  # "debit" | "credit"

    narration: Mapped[str] = mapped_column(Text, default="")  # raw bank text
    description: Mapped[str] = mapped_column(Text, default="")  # user's own note
    merchant: Mapped[str | None] = mapped_column(String(120), nullable=True)
    category: Mapped[str] = mapped_column(String(40), default="Other")
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # UPI, CARD, NEFT...
    reference_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False)
    category_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # user set it
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual|statement|aa
    dedupe_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    account: Mapped[Account] = relationship(back_populates="transactions")


class CategoryRule(Base):
    """Remembers the category a user picked for a merchant."""

    __tablename__ = "category_rules"
    __table_args__ = (UniqueConstraint("user_id", "merchant_key", name="uq_rule_user_merchant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    merchant_key: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


class Budget(Base):
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("user_id", "category", name="uq_budget_user_category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(40))
    monthly_limit: Mapped[Decimal] = mapped_column(Money)


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    target_amount: Mapped[Decimal] = mapped_column(Money)
    current_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Wealth (things not covered by bank accounts: property, gold, loans...)
# ---------------------------------------------------------------------------


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Money)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Liability(Base):
    __tablename__ = "liabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    category: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Money)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Account Aggregator consents
# ---------------------------------------------------------------------------


class AAConsent(Base):
    __tablename__ = "aa_consents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(30))
    consent_handle: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING|ACTIVE|REVOKED|FAILED
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Investments (mutual funds, stocks, EPF, NPS, FDs...)
# ---------------------------------------------------------------------------


class Holding(Base):
    __tablename__ = "holdings"
    __table_args__ = (UniqueConstraint("user_id", "identifier", name="uq_holding_user_identifier"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    holding_type: Mapped[str] = mapped_column(String(40))
    # ISIN + folio for imported holdings, so a re-import updates instead of duplicating.
    identifier: Mapped[str | None] = mapped_column(String(80), nullable=True)
    units: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    invested: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    current_value: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | cas
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Bills and reminders
# ---------------------------------------------------------------------------


class Bill(Base):
    __tablename__ = "bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    amount: Mapped[Decimal] = mapped_column(Money)
    category: Mapped[str] = mapped_column(String(40), default="Bills & Utilities")
    frequency: Mapped[str] = mapped_column(String(20), default="Monthly")  # Monthly|Quarterly|Yearly|Once
    next_due_date: Mapped[date] = mapped_column(Date)
    remind_days_before: Mapped[int] = mapped_column(Integer, default=3)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    last_reminded_for: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Family sharing
# ---------------------------------------------------------------------------


class FamilyShare(Base):
    """The owner lets the member see their finances (read-only)."""

    __tablename__ = "family_shares"
    __table_args__ = (UniqueConstraint("owner_id", "member_email", name="uq_share_owner_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    member_email: Mapped[str] = mapped_column(String(254), index=True)
    member_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    relation: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | accepted
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Credit score history
# ---------------------------------------------------------------------------


class CreditScore(Base):
    __tablename__ = "credit_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer)
    bureau: Mapped[str] = mapped_column(String(30))
    recorded_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


class LoginAttempt(Base):
    """Failed logins per email, tracked even for emails with no account,
    so the lockout can't be used to find out who is registered."""

    __tablename__ = "login_attempts"

    email: Mapped[str] = mapped_column(String(254), primary_key=True)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditLog(Base):
    """Security-relevant events: logins, password changes, exports, admin actions."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_created", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # kept after deletion
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    event: Mapped[str] = mapped_column(String(50), index=True)
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
