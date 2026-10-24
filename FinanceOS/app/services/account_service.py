"""Bank accounts, cards, wallets and cash.

An account's balance is never stored directly. It is always
opening_balance + credits - debits, so it can't get out of sync with the
transactions. Credit cards carry a negative balance when money is owed.
"""

from decimal import Decimal

from sqlalchemy import case, func, select

from app.database.db import get_session, use_session
from app.database.models import Account, Transaction

ACCOUNT_TYPES = [
    "Savings Account",
    "Current Account",
    "Salary Account",
    "Credit Card",
    "Cash",
    "Wallet",
    "Investment Account",
]
LIABILITY_ACCOUNT_TYPES = {"Credit Card"}


class AccountError(ValueError):
    pass


def _to_decimal(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def create_account(
    user_id: int,
    name: str,
    account_type: str,
    opening_balance=0,
    institution: str | None = None,
    masked_number: str | None = None,
    source: str = "manual",
    session=None,
) -> Account:
    """For a credit card, pass the amount currently owed as a positive number."""
    name = (name or "").strip()
    if not name:
        raise AccountError("Enter an account name.")
    if account_type not in ACCOUNT_TYPES:
        raise AccountError("Choose a valid account type.")

    opening = _to_decimal(opening_balance)
    if account_type in LIABILITY_ACCOUNT_TYPES:
        opening = -abs(opening)

    with use_session(session) as session:
        account = Account(
            user_id=user_id,
            name=name,
            account_type=account_type,
            institution=(institution or "").strip() or None,
            masked_number=(masked_number or "").strip() or None,
            opening_balance=opening,
            source=source,
        )
        session.add(account)
        session.flush()
        return account


def ensure_cash_account(user_id: int) -> Account:
    with get_session() as session:
        account = session.scalar(select(Account).where(Account.user_id == user_id, Account.account_type == "Cash"))
    return account or create_account(user_id, "Cash", "Cash", 0)


def list_accounts(user_id: int) -> list[Account]:
    with get_session() as session:
        return list(
            session.scalars(select(Account).where(Account.user_id == user_id).order_by(Account.created_at, Account.id))
        )


def get_account(user_id: int, account_id: int) -> Account:
    with get_session() as session:
        account = session.scalar(select(Account).where(Account.id == account_id, Account.user_id == user_id))
    if account is None:
        raise AccountError("Account not found.")
    return account


def _net_flows(session, user_id: int) -> dict[int, Decimal]:
    signed = case(
        (Transaction.txn_type == "credit", Transaction.amount),
        else_=-Transaction.amount,
    )
    rows = session.execute(
        select(Transaction.account_id, func.coalesce(func.sum(signed), 0))
        .where(Transaction.user_id == user_id)
        .group_by(Transaction.account_id)
    )
    return {account_id: _to_decimal(total) for account_id, total in rows}


def account_balances(user_id: int) -> dict[int, Decimal]:
    with get_session() as session:
        flows = _net_flows(session, user_id)
        accounts = session.scalars(select(Account).where(Account.user_id == user_id))
        return {a.id: _to_decimal(a.opening_balance) + flows.get(a.id, Decimal("0")) for a in accounts}


def accounts_with_balances(user_id: int) -> list[dict]:
    balances = account_balances(user_id)
    return [
        {
            "id": a.id,
            "name": a.name,
            "type": a.account_type,
            "institution": a.institution,
            "masked_number": a.masked_number,
            "source": a.source,
            "balance": balances.get(a.id, Decimal("0")),
        }
        for a in list_accounts(user_id)
    ]


def total_balance(user_id: int) -> Decimal:
    """Cash-like money: bank, cash and wallets minus credit card dues."""
    return sum(account_balances(user_id).values(), Decimal("0"))


def liquid_balance(user_id: int) -> Decimal:
    """Money available to spend (excludes investment accounts and card dues)."""
    total = Decimal("0")
    for row in accounts_with_balances(user_id):
        if row["type"] in {"Savings Account", "Current Account", "Salary Account", "Cash", "Wallet"}:
            total += row["balance"]
    return total


def balance_by_type(user_id: int) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for row in accounts_with_balances(user_id):
        result[row["type"]] = result.get(row["type"], Decimal("0")) + row["balance"]
    return result


def set_current_balance(user_id: int, account_id: int, actual_balance, session=None) -> None:
    """Make the computed balance match what the bank shows today.

    For credit cards, pass the amount owed as a positive number.
    """
    with use_session(session) as session:
        account = session.scalar(select(Account).where(Account.id == account_id, Account.user_id == user_id))
        if account is None:
            raise AccountError("Account not found.")
        target = _to_decimal(actual_balance)
        if account.account_type in LIABILITY_ACCOUNT_TYPES:
            target = -abs(target)
        session.flush()
        flow = _net_flows(session, user_id).get(account_id, Decimal("0"))
        account.opening_balance = target - flow


def rename_account(user_id: int, account_id: int, name: str) -> None:
    name = (name or "").strip()
    if not name:
        raise AccountError("Enter an account name.")
    with get_session() as session:
        account = session.scalar(select(Account).where(Account.id == account_id, Account.user_id == user_id))
        if account is None:
            raise AccountError("Account not found.")
        account.name = name


def delete_account(user_id: int, account_id: int) -> bool:
    """Deletes the account and all its transactions."""
    with get_session() as session:
        account = session.scalar(select(Account).where(Account.id == account_id, Account.user_id == user_id))
        if account is None:
            return False
        session.delete(account)
        return True
