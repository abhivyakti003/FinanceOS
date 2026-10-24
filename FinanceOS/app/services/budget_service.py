"""Monthly budgets per category. One budget per category per user."""

from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.database.db import get_session
from app.database.models import Budget
from app.services.categorization_service import EXPENSE_CATEGORIES


class BudgetError(ValueError):
    pass


def set_budget(user_id: int, category: str, monthly_limit) -> Budget:
    """Create the budget, or update it if this category already has one."""
    if category not in EXPENSE_CATEGORIES:
        raise BudgetError("Choose a valid spending category.")
    try:
        limit = Decimal(str(monthly_limit)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise BudgetError("Enter a valid amount.") from exc
    if limit <= 0:
        raise BudgetError("Budget must be more than zero.")

    with get_session() as session:
        budget = session.scalar(select(Budget).where(Budget.user_id == user_id, Budget.category == category))
        if budget:
            budget.monthly_limit = limit
        else:
            budget = Budget(user_id=user_id, category=category, monthly_limit=limit)
            session.add(budget)
        session.flush()
        return budget


def list_budgets(user_id: int) -> list[Budget]:
    with get_session() as session:
        return list(session.scalars(select(Budget).where(Budget.user_id == user_id).order_by(Budget.category)))


def delete_budget(user_id: int, budget_id: int) -> bool:
    with get_session() as session:
        budget = session.scalar(select(Budget).where(Budget.id == budget_id, Budget.user_id == user_id))
        if budget is None:
            return False
        session.delete(budget)
        return True
