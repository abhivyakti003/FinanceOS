from datetime import date

import pytest

from app.services import (
    analytics_service as an,
)
from app.services import (
    anomaly_service,
    budget_service,
    forecast_service,
    goal_service,
    health_service,
    recommendation_service,
    recurring_service,
    report_service,
    wealth_service,
)
from app.services import (
    transaction_service as ts,
)
from app.services.budget_service import BudgetError
from app.services.goal_service import GoalError

TODAY = date(2026, 9, 20)


def add(user, account, day, amount, kind, text, category=None):
    return ts.add_transaction(user.id, account.id, day, amount, kind, description=text, category=category)


@pytest.fixture
def history(user, bank):
    """Six months of salary, rent, food and Netflix."""
    for m in range(3, 9):
        add(user, bank, date(2026, m, 1), 80000, "credit", "Salary", "Salary")
        add(user, bank, date(2026, m, 3), 20000, "debit", "Rent", "Rent")
        add(user, bank, date(2026, m, 5), 649, "debit", "Netflix", "Entertainment")
        for day in (6, 12, 18, 24):
            add(user, bank, date(2026, m, day), 400 + m * 10, "debit", "Swiggy", "Food & Dining")
    return user


def test_summary_and_savings(history):
    s = an.period_summary(history.id, date(2026, 3, 1), date(2026, 8, 31))
    assert s["income"] == 480000
    assert s["spending"] > 0
    assert s["savings_rate"] > 50


def test_monthly_summary_keeps_years_apart(user, bank):
    add(user, bank, date(2025, 9, 10), 100, "debit", "a")
    add(user, bank, date(2026, 9, 10), 300, "debit", "b")
    df = an.monthly_summary(user.id, 13, TODAY)
    assert df.iloc[0]["label"] == "Sep 2025" and df.iloc[0]["spending"] == 100
    assert df.iloc[-1]["label"] == "Sep 2026" and df.iloc[-1]["spending"] == 300


def test_transfers_and_investments_are_not_spending(user, bank):
    add(user, bank, date(2026, 8, 1), 5000, "debit", "Groww SIP", "Investments")
    add(user, bank, date(2026, 8, 2), 3000, "debit", "cc bill", "Transfer")
    add(user, bank, date(2026, 8, 3), 100, "debit", "tea", "Food & Dining")
    s = an.period_summary(user.id, date(2026, 8, 1), date(2026, 8, 31))
    assert s["spending"] == 100 and s["invested"] == 5000


def test_budget_upsert_and_zero_guard(user, bank):
    budget_service.set_budget(user.id, "Food & Dining", 5000)
    budget_service.set_budget(user.id, "Food & Dining", 6000)
    assert len(budget_service.list_budgets(user.id)) == 1
    with pytest.raises(BudgetError):
        budget_service.set_budget(user.id, "Rent", 0)
    add(user, bank, date(2026, 9, 5), 3000, "debit", "zomato", "Food & Dining")
    util = an.budget_utilization(user.id, TODAY)
    assert util[0]["percent"] == 50.0


def test_goal_zero_target_rejected_and_progress(history):
    with pytest.raises(GoalError):
        goal_service.add_goal(history.id, "Bad", 0)
    goal_service.add_goal(history.id, "Trip", 100000, 25000)
    progress = goal_service.goal_progress(history.id, TODAY)[0]
    assert progress["percent"] == 25.0
    assert progress["eta_months"] >= 1


def test_forecast_uses_complete_months(history):
    f = forecast_service.forecast_next_month(history.id, TODAY)
    assert f["months_used"] == 6
    assert 20000 < f["spending"] < 25000
    assert f["income"] == pytest.approx(80000, rel=0.01)


def test_forecast_handles_year_boundary(user, bank):
    for m, y in [(10, 2025), (11, 2025), (12, 2025), (1, 2026)]:
        add(user, bank, date(y, m, 10), 1000 * m, "debit", "x")
    f = forecast_service.forecast_next_month(user.id, date(2026, 2, 15))
    assert f["months_used"] == 4
    assert f["spending"] >= 0


def test_health_score_without_budgets_is_not_punished(history):
    report = health_service.health_report(history.id, TODAY)
    assert report["budget_points"] == 15
    assert report["score"] >= 50


def test_health_score_without_data(user):
    assert health_service.health_report(user.id, TODAY)["score"] is None


def test_recurring_detection(history):
    found = {r["merchant"]: r for r in recurring_service.detect_recurring(history.id, TODAY)}
    assert "Netflix" in found and found["Netflix"]["frequency"] == "Monthly"


def test_anomaly_detection(history, bank):
    add(history, bank, date(2026, 9, 10), 6000, "debit", "Swiggy party", "Food & Dining")
    anomalies = anomaly_service.detect_anomalies(history.id, today=TODAY)
    assert anomalies and anomalies[0]["amount"] == 6000


def test_net_worth(user, bank):
    wealth_service.add_asset(user.id, "Gold", "Gold & jewellery", 50000)
    wealth_service.add_liability(user.id, "Car loan", "Car Loan", 20000)
    assert float(wealth_service.net_worth(user.id)["net_worth"]) == 10000 + 50000 - 20000


def test_recommendations_and_report(history):
    budget_service.set_budget(history.id, "Food & Dining", 1000)
    goal_service.add_goal(history.id, "Laptop", 90000, 10000, date(2027, 3, 1))
    assert recommendation_service.generate_recommendations(history.id)
    pdf = report_service.generate_report(history.id, date(2026, 3, 1), date(2026, 8, 31))
    assert pdf.startswith(b"%PDF") and len(pdf) > 5000
