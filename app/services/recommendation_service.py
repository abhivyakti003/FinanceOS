"""Plain-language suggestions based on the user's own numbers."""

from datetime import date

from app.config import CURRENCY_SYMBOL as RS
from app.services.analytics_service import budget_utilization
from app.services.anomaly_service import detect_anomalies
from app.services.goal_service import goal_progress
from app.services.health_service import health_report
from app.services.recurring_service import detect_recurring


def generate_recommendations(user_id: int, today: date | None = None) -> list[str]:
    today = today or date.today()
    tips: list[str] = []

    health = health_report(user_id, today)
    if health["score"] is None:
        return [health["message"]]

    rate = health["savings_rate"]
    if rate is not None and rate < 20:
        tips.append(
            f"You're saving {rate:.0f}% of your income. Aim for at least 20% by trimming your biggest spending category."
        )
    if health["months_covered"] is not None and health["months_covered"] < 3:
        tips.append(
            f"Your savings cover about {health['months_covered']} months of spending. Build an emergency fund of 3 to 6 months."
        )

    for item in budget_utilization(user_id, today):
        if item["percent"] > 100:
            tips.append(
                f"{item['category']} is over budget this month: {RS}{item['spent']:,.0f} of {RS}{item['limit']:,.0f}."
            )
        elif item["percent"] > 80:
            tips.append(f"{item['category']} has used {item['percent']:.0f}% of this month's budget.")

    for goal in goal_progress(user_id, today):
        if goal["on_track"] is False and goal["required_monthly"]:
            tips.append(f"To reach '{goal['name']}' on time, save {RS}{goal['required_monthly']:,.0f} a month.")

    subs = [
        r
        for r in detect_recurring(user_id, today)
        if r["active"] and r["category"] in {"Entertainment", "Other", "Shopping"}
    ]
    if subs:
        total = sum(r["monthly_cost"] for r in subs)
        tips.append(
            f"You have {len(subs)} active subscription{'s' if len(subs) != 1 else ''} costing about {RS}{total:,.0f} a month. Cancel any you don't use."
        )

    anomalies = detect_anomalies(user_id, 30, today)
    if anomalies:
        a = anomalies[0]
        tips.append(
            f"Unusual spend: {RS}{a['amount']:,.0f} on {a['category']} on {a['date']:%d %b}, {a['times_usual']}x your usual."
        )

    if not tips:
        tips.append("Your finances look healthy. Keep going.")
    return tips
