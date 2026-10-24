"""Export all of a user's data, update preferences, and delete the account.

Required under India's DPDP Act: people must be able to get their data and
have it erased.
"""

import io

import pandas as pd
from sqlalchemy import delete, select

from app.database.db import get_session
from app.database.models import (
    AAConsent,
    Account,
    Asset,
    Bill,
    Budget,
    CategoryRule,
    CreditScore,
    EmailOTP,
    FamilyShare,
    Goal,
    Holding,
    Liability,
    Transaction,
    User,
)
from app.services import audit_service
from app.services.auth_service import AuthError, verify_password

_EXPORT = [
    (
        "Accounts",
        Account,
        ["name", "account_type", "institution", "masked_number", "opening_balance", "source", "created_at"],
    ),
    (
        "Transactions",
        Transaction,
        [
            "txn_date",
            "txn_type",
            "amount",
            "category",
            "merchant",
            "description",
            "narration",
            "mode",
            "reference_id",
            "is_transfer",
            "source",
            "account_id",
        ],
    ),
    ("Budgets", Budget, ["category", "monthly_limit"]),
    ("Goals", Goal, ["name", "target_amount", "current_amount", "target_date"]),
    ("Investments", Holding, ["name", "holding_type", "units", "invested", "current_value", "source", "updated_at"]),
    ("Assets", Asset, ["name", "category", "amount"]),
    ("Loans", Liability, ["name", "category", "amount"]),
    ("Bills", Bill, ["name", "amount", "category", "frequency", "next_due_date", "last_paid_date", "active"]),
    ("Credit scores", CreditScore, ["recorded_on", "bureau", "score"]),
]


def export_excel(user_id: int) -> bytes:
    buffer = io.BytesIO()
    with get_session() as session, pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        user = session.get(User, user_id)
        pd.DataFrame([{"Name": user.name, "Email": user.email, "Joined": user.created_at}]).to_excel(
            writer, sheet_name="Profile", index=False
        )
        for sheet, model, columns in _EXPORT:
            rows = session.scalars(select(model).where(model.user_id == user_id))
            data = [{c: getattr(r, c) for c in columns} for r in rows]
            frame = pd.DataFrame(data, columns=columns)
            for col in frame.columns:
                if frame[col].map(lambda v: v.__class__.__name__ == "Decimal").any():
                    frame[col] = frame[col].astype(float)
            frame.to_excel(writer, sheet_name=sheet, index=False)
    audit_service.record("data_export", user_id, None)
    return buffer.getvalue()


def set_preferences(user_id: int, email_reminders: bool, weekly_summary: bool) -> None:
    with get_session() as session:
        user = session.get(User, user_id)
        user.email_reminders = bool(email_reminders)
        user.weekly_summary = bool(weekly_summary)


def delete_account(user_id: int, password: str) -> None:
    """Permanently delete the user and everything they own (user's own request)."""
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None or not verify_password(password, user.password_hash):
            raise AuthError("Your password is incorrect.")
        audit_service.record("account_deleted", user.id, user.email, "by the user", session=session)
        delete_user_data(session, user)


def delete_user_data(session, user: User) -> None:
    """Remove a user and every row they own, inside an open session."""
    user_id, email = user.id, user.email
    # Delete children explicitly too, in case foreign keys are off.
    for model in (
        Transaction,
        CategoryRule,
        Bill,
        Account,
        Budget,
        Goal,
        Holding,
        Asset,
        Liability,
        CreditScore,
        AAConsent,
    ):
        session.execute(delete(model).where(model.user_id == user_id))
    session.execute(delete(FamilyShare).where(FamilyShare.owner_id == user_id))
    session.execute(delete(FamilyShare).where(FamilyShare.member_email == email))
    session.execute(delete(EmailOTP).where(EmailOTP.email == email))
    session.delete(user)
