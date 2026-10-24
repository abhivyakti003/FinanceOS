"""Financial health score out of 100.

- Savings rate (40 points): share of income left after spending.
- Budget discipline (30 points): how well last month stayed within budgets.
  Users without budgets get a neutral 15 instead of 0.
- Emergency fund (30 points): how many months of spending your liquid
  balance covers.

Uses the last 3 complete months, or this month if that's all there is.
"""

from datetime import date

from app.services.account_service import liquid_balance
from app.services.analytics_service import (
    add_months,
    budget_utilization,
    last_complete_months,
    month_start,
    monthly_summary,
    period_summary,
)


def _savings_points(rate: float | None) -> int:
    if rate is None:
        return 0
    if rate >= 30:
        return 40
    if rate >= 20:
        return 32
    if rate >= 10:
        return 24
    if rate > 0:
        return 14
    return 0


def _budget_points(utilization: list[dict]) -> int:
    if not utilization:
        return 15
    points = 30
    for item in utilization:
        if item["percent"] > 100:
            points -= 10
        elif item["percent"] > 90:
            points -= 5
    return max(points, 0)


def _emergency_points(months_covered: float | None) -> int:
    if months_covered is None:
        return 15
    if months_covered >= 6:
        return 30
    if months_covered >= 3:
        return 22
    if months_covered >= 1:
        return 12
    return 4


def status_for(score: int | None) -> str:
    if score is None:
        return "Not enough data"
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Good"
    if score >= 50:
        return "Fair"
    return "Needs attention"


def health_report(user_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    history = monthly_summary(user_id, 4, today).iloc[:-1]
    if history["has_data"].any():
        start, end = last_complete_months(3, today)
    else:
        start, end = month_start(today), today

    summary = period_summary(user_id, start, end)
    if summary["income"] <= 0:
        return {
            "score": None,
            "status": status_for(None),
            "savings_points": 0,
            "budget_points": 0,
            "emergency_points": 0,
            "savings_rate": None,
            "months_covered": None,
            "message": "Add income transactions or import a statement to get your score.",
        }

    months_in_period = max(round((end - start).days / 30.4), 1)
    avg_spending = summary["spending"] / months_in_period
    months_covered = round(float(liquid_balance(user_id)) / avg_spending, 1) if avg_spending > 0 else None

    last_month = add_months(month_start(today), -1)
    utilization = budget_utilization(user_id, last_month if history["has_data"].any() else today)

    s = _savings_points(summary["savings_rate"])
    b = _budget_points(utilization)
    e = _emergency_points(months_covered)
    score = s + b + e
    return {
        "score": score,
        "status": status_for(score),
        "savings_points": s,
        "budget_points": b,
        "emergency_points": e,
        "savings_rate": summary["savings_rate"],
        "months_covered": months_covered,
        "message": None,
    }
