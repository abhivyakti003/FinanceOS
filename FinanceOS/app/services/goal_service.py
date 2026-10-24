"""Savings goals with progress, ETA and required monthly saving."""

import math
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.database.db import get_session
from app.database.models import Goal
from app.services.forecast_service import average_monthly_savings


class GoalError(ValueError):
    pass


def _money(value, allow_zero=False) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise GoalError("Enter a valid amount.") from exc
    if amount < 0 or (amount == 0 and not allow_zero):
        raise GoalError("Amount must be more than zero.")
    return amount


def add_goal(user_id: int, name: str, target_amount, current_amount=0, target_date: date | None = None) -> Goal:
    name = (name or "").strip()
    if not name:
        raise GoalError("Enter a goal name.")
    target = _money(target_amount)
    current = _money(current_amount, allow_zero=True)
    if target_date and target_date <= date.today():
        raise GoalError("Target date must be in the future.")
    with get_session() as session:
        goal = Goal(user_id=user_id, name=name, target_amount=target, current_amount=current, target_date=target_date)
        session.add(goal)
        session.flush()
        return goal


def list_goals(user_id: int) -> list[Goal]:
    with get_session() as session:
        return list(session.scalars(select(Goal).where(Goal.user_id == user_id).order_by(Goal.id)))


def add_contribution(user_id: int, goal_id: int, amount) -> Goal:
    """Add (or with a negative amount, withdraw) money saved toward a goal."""
    try:
        delta = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise GoalError("Enter a valid amount.") from exc
    with get_session() as session:
        goal = session.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id))
        if goal is None:
            raise GoalError("Goal not found.")
        goal.current_amount = max(goal.current_amount + delta, Decimal("0"))
        return goal


def delete_goal(user_id: int, goal_id: int) -> bool:
    with get_session() as session:
        goal = session.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id))
        if goal is None:
            return False
        session.delete(goal)
        return True


def _months_between(start: date, end: date) -> int:
    return max((end.year - start.year) * 12 + end.month - start.month, 0)


def goal_progress(user_id: int, today: date | None = None) -> list[dict]:
    today = today or date.today()
    monthly_savings = average_monthly_savings(user_id, today=today)
    results = []
    for goal in list_goals(user_id):
        target = float(goal.target_amount)
        current = float(goal.current_amount)
        remaining = max(target - current, 0.0)
        percent = round(min(current / target * 100, 100), 1) if target > 0 else 0.0

        if remaining == 0:
            eta_months = 0
        elif monthly_savings > 0:
            eta_months = math.ceil(remaining / monthly_savings)
        else:
            eta_months = None  # not saving yet, so no ETA

        required = None
        on_track = None
        if goal.target_date and remaining > 0:
            months_left = _months_between(today, goal.target_date)
            required = round(remaining / months_left, 2) if months_left > 0 else remaining
            on_track = monthly_savings >= required
        elif remaining == 0:
            on_track = True

        results.append(
            {
                "id": goal.id,
                "name": goal.name,
                "current": current,
                "target": target,
                "remaining": remaining,
                "percent": percent,
                "target_date": goal.target_date,
                "eta_months": eta_months,
                "required_monthly": required,
                "on_track": on_track,
            }
        )
    return results
