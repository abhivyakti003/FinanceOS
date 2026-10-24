"""Numbers for the dashboard and reports.

Definitions used everywhere:
- Income   = credits that aren't transfers or refunds
- Spending = debits that aren't transfers or investments, minus refunds
- Invested = debits in the Investments category
- Savings  = Income - Spending (so money you invest counts as saved)
"""

from datetime import date, timedelta

import pandas as pd

from app.services import categorization_service as cat
from app.services.transaction_service import transactions_frame

# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------


def month_start(d: date) -> date:
    return d.replace(day=1)


def add_months(d: date, months: int) -> date:
    year = d.year + (d.month - 1 + months) // 12
    month = (d.month - 1 + months) % 12 + 1
    return date(year, month, 1)


def month_end(d: date) -> date:
    return add_months(month_start(d), 1) - timedelta(days=1)


def last_complete_months(n: int, today: date | None = None) -> tuple[date, date]:
    """Start and end dates covering the last n full calendar months."""
    today = today or date.today()
    end = month_start(today) - timedelta(days=1)
    start = add_months(month_start(today), -n)
    return start, end


# ---------------------------------------------------------------------------
# Core split of a transactions frame
# ---------------------------------------------------------------------------


def _split(df: pd.DataFrame) -> dict[str, float]:
    if df.empty:
        return {"income": 0.0, "spending": 0.0, "invested": 0.0, "refunds": 0.0}
    real = df[~df["is_transfer"]]
    credits = real[real["txn_type"] == "credit"]
    debits = real[real["txn_type"] == "debit"]
    refunds = credits.loc[credits["category"] == "Refund", "amount"].sum()
    income = credits.loc[credits["category"] != "Refund", "amount"].sum()
    invested = debits.loc[debits["category"] == "Investments", "amount"].sum()
    spending = debits.loc[~debits["category"].isin(cat.NON_SPENDING_CATEGORIES), "amount"].sum()
    return {
        "income": float(income),
        "spending": float(max(spending - refunds, 0)),
        "invested": float(invested),
        "refunds": float(refunds),
    }


def spending_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Only the debits that count as spending."""
    if df.empty:
        return df
    return df[(~df["is_transfer"]) & (df["txn_type"] == "debit") & (~df["category"].isin(cat.NON_SPENDING_CATEGORIES))]


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def period_summary(user_id: int, start: date | None = None, end: date | None = None) -> dict:
    parts = _split(transactions_frame(user_id, start, end))
    savings = parts["income"] - parts["spending"]
    rate = round(savings / parts["income"] * 100, 1) if parts["income"] > 0 else None
    return {**parts, "savings": savings, "savings_rate": rate}


def monthly_summary(user_id: int, months: int = 12, today: date | None = None) -> pd.DataFrame:
    """One row per calendar month (including empty months), oldest first.

    Months are keyed by year AND month, so Jan 2026 and Jan 2027 stay separate.
    """
    today = today or date.today()
    start = add_months(month_start(today), -(months - 1))
    df = transactions_frame(user_id, start, month_end(today))

    rows = []
    for i in range(months):
        m = add_months(start, i)
        if df.empty:
            chunk = df
        else:
            mask = (df["txn_date"].dt.year == m.year) & (df["txn_date"].dt.month == m.month)
            chunk = df[mask]
        parts = _split(chunk)
        rows.append(
            {
                "month": m,
                "label": m.strftime("%b %Y"),
                "income": parts["income"],
                "spending": parts["spending"],
                "invested": parts["invested"],
                "savings": parts["income"] - parts["spending"],
                "has_data": not chunk.empty,
            }
        )
    return pd.DataFrame(rows)


def category_breakdown(user_id: int, start: date | None = None, end: date | None = None) -> pd.DataFrame:
    spend = spending_frame(transactions_frame(user_id, start, end))
    if spend.empty:
        return pd.DataFrame(columns=["category", "amount"])
    return (
        spend.groupby("category", as_index=False)["amount"]
        .sum()
        .sort_values("amount", ascending=False)
        .reset_index(drop=True)
    )


def merchant_breakdown(user_id: int, start: date | None = None, end: date | None = None, top: int = 10) -> pd.DataFrame:
    spend = spending_frame(transactions_frame(user_id, start, end))
    if spend.empty:
        return pd.DataFrame(columns=["merchant", "amount", "count"])
    spend = spend.assign(merchant=spend["merchant"].fillna("Unknown"))
    return (
        spend.groupby("merchant", as_index=False)
        .agg(amount=("amount", "sum"), count=("amount", "size"))
        .sort_values("amount", ascending=False)
        .head(top)
        .reset_index(drop=True)
    )


def budget_utilization(user_id: int, month: date | None = None) -> list[dict]:
    """Spending against each monthly budget for the given month (default: this month)."""
    from app.services.budget_service import list_budgets  # avoid circular import

    month = month_start(month or date.today())
    by_category = category_breakdown(user_id, month, month_end(month))
    spent_map = dict(zip(by_category["category"], by_category["amount"], strict=False))

    result = []
    for budget in list_budgets(user_id):
        limit = float(budget.monthly_limit)
        spent = float(spent_map.get(budget.category, 0.0))
        pct = round(spent / limit * 100, 1) if limit > 0 else 0.0
        result.append(
            {
                "id": budget.id,
                "category": budget.category,
                "limit": limit,
                "spent": spent,
                "remaining": limit - spent,
                "percent": pct,
            }
        )
    return result
