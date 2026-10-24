"""Flags unusually large spends, compared with what's normal for that category.

Replaces the old Isolation Forest, which looked at amounts alone (so every
rent payment looked "unusual") and couldn't explain its decisions. This
version says why: "3.2x your usual Shopping spend".
"""

from datetime import date, timedelta

import numpy as np

from app.services.analytics_service import spending_frame
from app.services.transaction_service import transactions_frame

MIN_HISTORY = 5  # need this many past spends in a category to judge
MULTIPLIER = 3.0  # flag when a spend is 3x the category's median...
MIN_AMOUNT = 500.0  # ...and at least this much, to skip tiny noise


def detect_anomalies(user_id: int, lookback_days: int = 60, today: date | None = None) -> list[dict]:
    today = today or date.today()
    df = spending_frame(transactions_frame(user_id, today - timedelta(days=365), today))
    if df.empty:
        return []

    cutoff = today - timedelta(days=lookback_days)
    results = []
    for category, group in df.groupby("category"):
        if category in {"Rent", "EMI & Loans", "Insurance", "Education"}:
            continue  # big by nature, not suspicious
        recent = group[group["txn_date"].dt.date >= cutoff]
        for _, row in recent.iterrows():
            history = group[group["id"] != row["id"]]["amount"]
            if len(history) < MIN_HISTORY:
                continue
            median = float(np.median(history))
            q3 = float(np.percentile(history, 75))
            q1 = float(np.percentile(history, 25))
            threshold = max(median * MULTIPLIER, q3 + 3 * (q3 - q1), MIN_AMOUNT)
            if row["amount"] >= threshold and median > 0:
                results.append(
                    {
                        "id": int(row["id"]),
                        "date": row["txn_date"].date(),
                        "category": category,
                        "merchant": row["merchant"] or "",
                        "amount": float(row["amount"]),
                        "usual": round(median, 2),
                        "times_usual": round(float(row["amount"]) / median, 1),
                    }
                )
    return sorted(results, key=lambda r: r["date"], reverse=True)
