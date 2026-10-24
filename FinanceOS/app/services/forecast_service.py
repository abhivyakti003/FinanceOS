"""Next-month forecasts.

Uses full calendar months keyed by year and month, and ignores the current
unfinished month (a half-finished month would drag the forecast down).

Method: with fewer than 3 months of history we use the average. With more,
we blend a straight-line trend over the last 12 months with the average of
the last 3 months, which is steadier than either alone. The old Random
Forest model was removed: tree models can't predict beyond the values they
were trained on, so they can't follow a trend.
"""

from datetime import date

import numpy as np

from app.services.account_service import total_balance
from app.services.analytics_service import monthly_summary


def _complete_history(user_id: int, months: int = 12, today: date | None = None):
    today = today or date.today()
    df = monthly_summary(user_id, months + 1, today)
    df = df.iloc[:-1]  # drop the current, unfinished month
    # Skip leading months from before the user had any data.
    if df["has_data"].any():
        first = df.index[df["has_data"]][0]
        df = df.loc[first:]
    else:
        df = df.iloc[0:0]
    return df


def predict_series(values: list[float]) -> float:
    values = [float(v) for v in values]
    n = len(values)
    if n == 0:
        return 0.0
    recent_avg = float(np.mean(values[-3:]))
    if n < 3:
        return round(recent_avg, 2)
    x = np.arange(n)
    slope, intercept = np.polyfit(x, values, 1)
    trend = slope * n + intercept
    blended = 0.5 * trend + 0.5 * recent_avg
    # Keep the forecast within a sensible range of what has actually happened.
    blended = min(max(blended, 0.0), max(values) * 1.5)
    return round(float(blended), 2)


def forecast_next_month(user_id: int, today: date | None = None) -> dict:
    history = _complete_history(user_id, today=today)
    spending = predict_series(history["spending"].tolist())
    income = predict_series(history["income"].tolist())
    savings = income - spending
    return {
        "months_used": len(history),
        "spending": spending,
        "income": income,
        "savings": round(savings, 2),
        "projected_balance": round(float(total_balance(user_id)) + savings, 2),
    }


def average_monthly_savings(user_id: int, months: int = 6, today: date | None = None) -> float:
    history = _complete_history(user_id, months, today)
    if history.empty:
        return 0.0
    return round(float(history["savings"].mean()), 2)
