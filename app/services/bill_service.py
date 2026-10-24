"""Bills and payment reminders (rent, electricity, credit card, insurance, EMI...)."""

import calendar
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.database.db import get_session
from app.database.models import Bill
from app.services.categorization_service import EXPENSE_CATEGORIES, TRANSFER_CATEGORY

FREQUENCIES = ["Monthly", "Quarterly", "Yearly", "Once"]
_MONTHS = {"Monthly": 1, "Quarterly": 3, "Yearly": 12}


class BillError(ValueError):
    pass


def shift_months(d: date, months: int) -> date:
    """Same day N months later, clamped to the month's last day (31 Jan -> 28/29 Feb)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def next_after(due: date, frequency: str) -> date | None:
    if frequency == "Once":
        return None
    return shift_months(due, _MONTHS[frequency])


def add_bill(
    user_id: int,
    name: str,
    amount,
    next_due_date: date,
    frequency: str = "Monthly",
    category: str = "Bills & Utilities",
    remind_days_before: int = 3,
    account_id: int | None = None,
) -> Bill:
    name = (name or "").strip()
    if not name:
        raise BillError("Enter a bill name.")
    try:
        amount_d = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise BillError("Enter a valid amount.") from exc
    if amount_d <= 0:
        raise BillError("Amount must be more than zero.")
    if frequency not in FREQUENCIES:
        raise BillError("Choose how often this bill repeats.")
    if category not in EXPENSE_CATEGORIES + [TRANSFER_CATEGORY]:
        raise BillError("Choose a valid category.")
    if next_due_date is None:
        raise BillError("Choose the next due date.")
    if not 0 <= int(remind_days_before) <= 30:
        raise BillError("Reminder must be between 0 and 30 days before.")

    if account_id is not None:
        from app.services.account_service import get_account

        get_account(user_id, account_id)  # ownership check

    with get_session() as session:
        bill = Bill(
            user_id=user_id,
            name=name,
            amount=amount_d,
            next_due_date=next_due_date,
            frequency=frequency,
            category=category,
            remind_days_before=int(remind_days_before),
            account_id=account_id,
            active=True,
        )
        session.add(bill)
        session.flush()
        return bill


def list_bills(user_id: int, include_inactive: bool = False) -> list[Bill]:
    query = select(Bill).where(Bill.user_id == user_id)
    if not include_inactive:
        query = query.where(Bill.active.is_(True))
    with get_session() as session:
        return list(session.scalars(query.order_by(Bill.next_due_date)))


def _owned(session, user_id: int, bill_id: int) -> Bill:
    bill = session.scalar(select(Bill).where(Bill.id == bill_id, Bill.user_id == user_id))
    if bill is None:
        raise BillError("Bill not found.")
    return bill


def mark_paid(
    user_id: int,
    bill_id: int,
    paid_on: date | None = None,
    record_transaction: bool = False,
    account_id: int | None = None,
) -> Bill:
    """Move the bill to its next due date, and optionally record the payment.

    Both happen in one database transaction: either both are saved or neither.
    """
    from app.services.account_service import ensure_cash_account
    from app.services.transaction_service import add_transaction

    paid_on = paid_on or date.today()
    use_account = account_id
    if record_transaction and use_account is None:
        with get_session() as session:
            bill = _owned(session, user_id, bill_id)
            use_account = bill.account_id
        if use_account is None:
            use_account = ensure_cash_account(user_id).id

    with get_session() as session:
        bill = _owned(session, user_id, bill_id)
        bill.last_paid_date = paid_on
        upcoming = next_after(bill.next_due_date, bill.frequency)
        if upcoming is None:
            bill.active = False
        else:
            # If several periods were missed, jump to the first due date after the payment.
            while upcoming <= paid_on:
                upcoming = next_after(upcoming, bill.frequency)
            bill.next_due_date = upcoming
        bill.last_reminded_for = None
        if record_transaction:
            add_transaction(
                user_id,
                use_account,
                paid_on,
                bill.amount,
                "debit",
                description=f"{bill.name} (bill)",
                category=bill.category,
                session=session,
            )
        return bill


def snooze(user_id: int, bill_id: int, days: int = 3) -> None:
    with get_session() as session:
        bill = _owned(session, user_id, bill_id)
        bill.next_due_date = bill.next_due_date + timedelta(days=days)


def delete_bill(user_id: int, bill_id: int) -> bool:
    with get_session() as session:
        bill = session.scalar(select(Bill).where(Bill.id == bill_id, Bill.user_id == user_id))
        if bill is None:
            return False
        session.delete(bill)
        return True


def bill_status(bill: Bill, today: date | None = None) -> dict:
    today = today or date.today()
    days = (bill.next_due_date - today).days
    if days < 0:
        label, level = f"Overdue by {-days} day{'s' if days != -1 else ''}", "overdue"
    elif days == 0:
        label, level = "Due today", "today"
    elif days <= bill.remind_days_before:
        label, level = f"Due in {days} day{'s' if days != 1 else ''}", "soon"
    else:
        label, level = f"Due {bill.next_due_date:%d %b}", "later"
    return {"days": days, "label": label, "level": level}


def due_soon(user_id: int, today: date | None = None, within_days: int | None = None) -> list[tuple[Bill, dict]]:
    """Bills that are overdue, or due within their reminder window (or `within_days`)."""
    today = today or date.today()
    result = []
    for bill in list_bills(user_id):
        status = bill_status(bill, today)
        window = within_days if within_days is not None else bill.remind_days_before
        if status["days"] <= window:
            result.append((bill, status))
    return result


def monthly_bill_total(user_id: int) -> Decimal:
    total = Decimal("0")
    for bill in list_bills(user_id):
        if bill.frequency in _MONTHS:
            total += bill.amount / _MONTHS[bill.frequency]
    return total.quantize(Decimal("0.01"))


def create_from_recurring(user_id: int, item: dict) -> Bill:
    """Turn a detected recurring payment into a bill with reminders."""
    frequency = item["frequency"] if item["frequency"] in _MONTHS else "Monthly"
    category = item["category"] if item["category"] in EXPENSE_CATEGORIES else "Bills & Utilities"
    due = item["next_expected"]
    today = date.today()
    while due < today:
        due = next_after(due, frequency)
    return add_bill(user_id, item["merchant"] or "Recurring payment", item["average_amount"], due, frequency, category)
