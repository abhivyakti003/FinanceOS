"""Transactions: add, list, edit, delete, bulk import.

Every function takes user_id and every query filters by it, so one user can
never read or change another user's data.
"""

import hashlib
import uuid
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

import pandas as pd
from sqlalchemy import or_, select

from app.database.db import get_session, use_session
from app.database.models import Account, CategoryRule, Transaction
from app.services import categorization_service as cat

TXN_TYPES = {"debit", "credit"}


class TransactionError(ValueError):
    pass


def _money(value) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TransactionError("Enter a valid amount.") from exc
    return amount


def _owned_account(session, user_id: int, account_id: int) -> Account:
    account = session.scalar(select(Account).where(Account.id == account_id, Account.user_id == user_id))
    if account is None:
        raise TransactionError("Account not found.")
    return account


def user_rules(user_id: int) -> dict[str, str]:
    with get_session() as session:
        rows = session.execute(
            select(CategoryRule.merchant_key, CategoryRule.category).where(CategoryRule.user_id == user_id)
        )
        return {key: category for key, category in rows}


def import_hash(
    txn_date: date,
    amount: Decimal,
    txn_type: str,
    narration: str,
    reference_id: str | None,
    balance=None,
    occurrence: int = 0,
) -> str:
    parts = [
        txn_date.isoformat(),
        f"{amount:.2f}",
        txn_type,
        " ".join((narration or "").lower().split()),
        reference_id or "",
        "" if balance is None else f"{Decimal(str(balance)):.2f}",
        str(occurrence),
    ]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def add_transaction(
    user_id: int,
    account_id: int,
    txn_date: date,
    amount,
    txn_type: str,
    description: str = "",
    narration: str = "",
    category: str | None = None,
    merchant: str | None = None,
    session=None,
) -> Transaction:
    """Add one manual transaction. If category is None it is suggested automatically."""
    amount = _money(amount)
    if amount <= 0:
        raise TransactionError("Amount must be more than zero.")
    if txn_type not in TXN_TYPES:
        raise TransactionError("Type must be debit or credit.")
    if txn_date is None:
        raise TransactionError("Choose a date.")
    if txn_date > date.today() + timedelta(days=1):
        raise TransactionError("Date can't be in the future.")
    if category is not None and category not in cat.ALL_CATEGORIES:
        raise TransactionError("Choose a valid category.")

    text = narration or description or ""
    parsed = cat.parse_narration(text)
    merchant = (merchant or "").strip() or parsed["merchant"]

    with use_session(session) as session:
        account = _owned_account(session, user_id, account_id)
        if category is None:
            category, is_transfer = cat.suggest_category(
                text, txn_type, merchant, user_rules(user_id), account.account_type
            )
            locked = False
        else:
            is_transfer = category == cat.TRANSFER_CATEGORY
            locked = True

        txn = Transaction(
            user_id=user_id,
            account_id=account.id,
            txn_date=txn_date,
            amount=amount,
            txn_type=txn_type,
            narration=narration or "",
            description=description or "",
            merchant=merchant,
            category=category,
            mode=parsed["mode"],
            reference_id=parsed["reference_id"],
            is_transfer=is_transfer,
            category_locked=locked,
            source="manual",
            dedupe_hash=uuid.uuid4().hex,  # manual entries can legitimately repeat
        )
        session.add(txn)
        session.flush()
        return txn


def bulk_import(user_id: int, account_id: int, rows: list[dict], source: str = "statement", session=None) -> dict:
    """Insert parsed statement rows, skipping ones already imported.

    Each row: {"txn_date", "amount", "txn_type", "narration", "reference_id"?, "balance"?}
    Returns {"inserted": n, "skipped": n}.
    """
    rules = user_rules(user_id)
    inserted = skipped = 0

    with use_session(session) as session:
        account = _owned_account(session, user_id, account_id)
        existing = set(session.scalars(select(Transaction.dedupe_hash).where(Transaction.account_id == account.id)))
        seen: Counter = Counter()

        for row in rows:
            amount = _money(row["amount"])
            if amount <= 0 or row["txn_type"] not in TXN_TYPES:
                skipped += 1
                continue
            narration = str(row.get("narration") or "").strip()
            parsed = cat.parse_narration(narration)
            reference = row.get("reference_id") or parsed["reference_id"]

            base_key = (row["txn_date"], amount, row["txn_type"], narration.lower(), reference, row.get("balance"))
            occurrence = seen[base_key]
            seen[base_key] += 1
            digest = import_hash(
                row["txn_date"], amount, row["txn_type"], narration, reference, row.get("balance"), occurrence
            )
            if digest in existing:
                skipped += 1
                continue
            existing.add(digest)

            category, is_transfer = cat.suggest_category(
                narration, row["txn_type"], parsed["merchant"], rules, account.account_type
            )
            session.add(
                Transaction(
                    user_id=user_id,
                    account_id=account.id,
                    txn_date=row["txn_date"],
                    amount=amount,
                    txn_type=row["txn_type"],
                    narration=narration,
                    description="",
                    merchant=parsed["merchant"],
                    category=category,
                    mode=parsed["mode"],
                    reference_id=reference,
                    is_transfer=is_transfer,
                    source=source,
                    dedupe_hash=digest,
                )
            )
            inserted += 1

        if inserted:
            session.flush()  # make the new rows visible to the transfer check
            detect_internal_transfers(user_id, session=session)
    return {"inserted": inserted, "skipped": skipped}


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def list_transactions(
    user_id: int,
    start: date | None = None,
    end: date | None = None,
    account_id: int | None = None,
    category: str | None = None,
    txn_type: str | None = None,
    search: str | None = None,
    include_transfers: bool = True,
    limit: int | None = None,
) -> list[Transaction]:
    query = select(Transaction).where(Transaction.user_id == user_id)
    if start:
        query = query.where(Transaction.txn_date >= start)
    if end:
        query = query.where(Transaction.txn_date <= end)
    if account_id:
        query = query.where(Transaction.account_id == account_id)
    if category:
        query = query.where(Transaction.category == category)
    if txn_type:
        query = query.where(Transaction.txn_type == txn_type)
    if not include_transfers:
        query = query.where(Transaction.is_transfer.is_(False))
    if search:
        like = f"%{search.strip()}%"
        query = query.where(
            or_(
                Transaction.narration.ilike(like),
                Transaction.description.ilike(like),
                Transaction.merchant.ilike(like),
                Transaction.category.ilike(like),
            )
        )
    query = query.order_by(Transaction.txn_date.desc(), Transaction.id.desc())
    if limit:
        query = query.limit(limit)
    with get_session() as session:
        return list(session.scalars(query))


def get_transaction(user_id: int, txn_id: int) -> Transaction:
    with get_session() as session:
        txn = session.scalar(select(Transaction).where(Transaction.id == txn_id, Transaction.user_id == user_id))
    if txn is None:
        raise TransactionError("Transaction not found.")
    return txn


def transactions_frame(user_id: int, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """All transactions as a DataFrame with float amounts (for analytics and charts)."""
    columns = [
        "id",
        "account_id",
        "txn_date",
        "amount",
        "txn_type",
        "category",
        "merchant",
        "narration",
        "description",
        "is_transfer",
        "mode",
    ]
    txns = list_transactions(user_id, start=start, end=end)
    if not txns:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(
        [
            {
                "id": t.id,
                "account_id": t.account_id,
                "txn_date": pd.Timestamp(t.txn_date),
                "amount": float(t.amount),
                "txn_type": t.txn_type,
                "category": t.category,
                "merchant": t.merchant,
                "narration": t.narration,
                "description": t.description,
                "is_transfer": bool(t.is_transfer),
                "mode": t.mode,
            }
            for t in txns
        ]
    )
    return df


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------


def update_transaction(
    user_id: int,
    txn_id: int,
    *,
    category: str | None = None,
    description: str | None = None,
    amount=None,
    txn_date: date | None = None,
    learn: bool = True,
) -> Transaction:
    """Edit a transaction. Changing the category teaches FinanceOS: other
    transactions from the same merchant get the same category, now and later."""
    if category is not None and category not in cat.ALL_CATEGORIES:
        raise TransactionError("Choose a valid category.")

    learned_key = None
    with get_session() as session:
        txn = session.scalar(select(Transaction).where(Transaction.id == txn_id, Transaction.user_id == user_id))
        if txn is None:
            raise TransactionError("Transaction not found.")

        if amount is not None:
            new_amount = _money(amount)
            if new_amount <= 0:
                raise TransactionError("Amount must be more than zero.")
            txn.amount = new_amount
        if txn_date is not None:
            txn.txn_date = txn_date
        if description is not None:
            txn.description = description.strip()
        if category is not None and category != txn.category:
            txn.category = category
            txn.is_transfer = category == cat.TRANSFER_CATEGORY
            txn.category_locked = True
            learned_key = cat.merchant_key(txn.merchant) if learn else None

        if learned_key:
            rule = session.scalar(
                select(CategoryRule).where(CategoryRule.user_id == user_id, CategoryRule.merchant_key == learned_key)
            )
            if rule:
                rule.category = category
            else:
                session.add(CategoryRule(user_id=user_id, merchant_key=learned_key, category=category))

            # Apply to other transactions from this merchant the user hasn't set by hand.
            for other in session.scalars(
                select(Transaction).where(
                    Transaction.user_id == user_id,
                    Transaction.id != txn.id,
                    Transaction.category_locked.is_(False),
                    Transaction.merchant.is_not(None),
                )
            ):
                if cat.merchant_key(other.merchant) == learned_key and other.txn_type == txn.txn_type:
                    other.category = category
                    other.is_transfer = category == cat.TRANSFER_CATEGORY
        return txn


def delete_transaction(user_id: int, txn_id: int) -> bool:
    with get_session() as session:
        txn = session.scalar(select(Transaction).where(Transaction.id == txn_id, Transaction.user_id == user_id))
        if txn is None:
            return False
        session.delete(txn)
        return True


def delete_transactions(user_id: int, txn_ids: list[int]) -> int:
    count = 0
    for txn_id in txn_ids:
        count += delete_transaction(user_id, txn_id)
    return count


# ---------------------------------------------------------------------------
# Transfers between the user's own accounts
# ---------------------------------------------------------------------------


def detect_internal_transfers(
    user_id: int, window_days: int = 2, min_amount: Decimal = Decimal("500"), session=None
) -> int:
    """Mark money moved between the user's own accounts as transfers.

    A debit in one account and a credit of the exact same amount in another of
    the user's accounts within `window_days` are treated as one transfer, so it
    isn't counted as both spending and income. Returns pairs found.
    """
    with use_session(session) as session:
        txns = list(
            session.scalars(
                select(Transaction).where(
                    Transaction.user_id == user_id,
                    Transaction.is_transfer.is_(False),
                    Transaction.category_locked.is_(False),
                    Transaction.amount >= min_amount,
                )
            )
        )
        credits = [t for t in txns if t.txn_type == "credit"]
        used: set[int] = set()
        pairs = 0
        for debit in (t for t in txns if t.txn_type == "debit"):
            for credit in credits:
                if (
                    credit.id not in used
                    and credit.account_id != debit.account_id
                    and credit.amount == debit.amount
                    and abs((credit.txn_date - debit.txn_date).days) <= window_days
                ):
                    for t in (debit, credit):
                        t.is_transfer = True
                        t.category = cat.TRANSFER_CATEGORY
                    used.add(credit.id)
                    pairs += 1
                    break
        return pairs
