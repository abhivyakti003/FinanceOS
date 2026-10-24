"""Finds subscriptions, SIPs, EMIs, rent and other repeating payments."""

from datetime import date, timedelta

import numpy as np

from app.services.transaction_service import transactions_frame

FREQUENCIES = [
    ("Weekly", 7, 2),
    ("Monthly", 30, 5),
    ("Quarterly", 91, 10),
    ("Yearly", 365, 20),
]


def _group_key(row) -> str | None:
    merchant = row["merchant"]
    if isinstance(merchant, str) and merchant.strip():
        return merchant.strip().lower()
    return None


def detect_recurring(user_id: int, today: date | None = None, min_occurrences: int = 3) -> list[dict]:
    today = today or date.today()
    df = transactions_frame(user_id, today - timedelta(days=400), today)
    if df.empty:
        return []
    df = df[(df["txn_type"] == "debit") & (~df["is_transfer"])].copy()
    df["key"] = df.apply(_group_key, axis=1)
    df = df.dropna(subset=["key"])

    results = []
    for _key, group in df.groupby("key"):
        if len(group) < min_occurrences:
            continue
        group = group.sort_values("txn_date")
        dates = group["txn_date"].dt.date.tolist()
        gaps = np.diff([d.toordinal() for d in dates])
        if len(gaps) == 0 or gaps.min() == 0:
            continue  # several payments on the same day isn't a subscription
        median_gap = float(np.median(gaps))
        amounts = group["amount"].to_numpy()
        variation = float(np.std(amounts) / np.mean(amounts)) if np.mean(amounts) > 0 else 1.0
        if variation > 0.2:
            continue  # amounts vary too much to be a fixed payment

        for name, days, tolerance in FREQUENCIES:
            if abs(median_gap - days) <= tolerance and np.all(np.abs(gaps - days) <= tolerance * 2):
                last = dates[-1]
                next_due = last + timedelta(days=days)
                active = (today - last).days <= days + tolerance * 2
                monthly_cost = float(np.mean(amounts)) * 30 / days
                results.append(
                    {
                        "merchant": group["merchant"].iloc[-1],
                        "category": group["category"].iloc[-1],
                        "frequency": name,
                        "average_amount": round(float(np.mean(amounts)), 2),
                        "monthly_cost": round(monthly_cost, 2),
                        "occurrences": len(group),
                        "last_date": last,
                        "next_expected": next_due,
                        "active": active,
                    }
                )
                break
    return sorted(results, key=lambda r: (not r["active"], -r["monthly_cost"]))


def upcoming_payments(user_id: int, days: int = 14, today: date | None = None) -> list[dict]:
    today = today or date.today()
    return [
        r
        for r in detect_recurring(user_id, today)
        if r["active"] and today <= r["next_expected"] <= today + timedelta(days=days)
    ]
