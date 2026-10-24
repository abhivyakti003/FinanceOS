"""Quick facts about spending in a period."""

from datetime import date

from app.services.analytics_service import spending_frame
from app.services.transaction_service import transactions_frame


def spending_insights(user_id: int, start: date | None = None, end: date | None = None) -> dict:
    df = transactions_frame(user_id, start, end)
    spend = spending_frame(df)
    income = (
        df[(df["txn_type"] == "credit") & (~df["is_transfer"]) & (df["category"] != "Refund")] if not df.empty else df
    )

    if spend.empty:
        return {
            "count": 0,
            "average": 0.0,
            "highest": None,
            "top_category": None,
            "most_frequent_category": None,
            "top_merchant": None,
            "largest_income": None,
            "top_five": [],
        }

    highest = spend.loc[spend["amount"].idxmax()]
    by_cat = spend.groupby("category")["amount"].sum()
    merchants = spend[spend["merchant"] != ""]
    top_merchant = merchants.groupby("merchant")["amount"].sum().idxmax() if not merchants.empty else None
    largest_income = None
    if not income.empty:
        row = income.loc[income["amount"].idxmax()]
        largest_income = {
            "category": row["category"],
            "amount": float(row["amount"]),
            "narration": row["narration"] or row["description"],
        }

    top_five = spend.sort_values("amount", ascending=False).head(5)
    return {
        "count": int(len(spend)),
        "average": round(float(spend["amount"].mean()), 2),
        "highest": {
            "amount": float(highest["amount"]),
            "category": highest["category"],
            "merchant": highest["merchant"],
            "date": highest["txn_date"].date(),
        },
        "top_category": by_cat.idxmax(),
        "most_frequent_category": spend["category"].value_counts().idxmax(),
        "top_merchant": top_merchant,
        "largest_income": largest_income,
        "top_five": [
            {
                "date": r["txn_date"].date(),
                "category": r["category"],
                "merchant": r["merchant"] or "",
                "amount": float(r["amount"]),
                "details": r["description"] or r["narration"],
            }
            for _, r in top_five.iterrows()
        ],
    }
