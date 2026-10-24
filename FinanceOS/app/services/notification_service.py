"""Alerts shown in the app, plus reminder and weekly summary emails.

In-app alerts are calculated each time a page loads. Emails are sent by
running `python scripts/send_notifications.py` once a day (schedule it with
Windows Task Scheduler or cron; see README).
"""

import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.config import CURRENCY_SYMBOL as RS
from app.database.db import get_session
from app.database.models import Bill, User
from app.services import email_service
from app.services.analytics_service import budget_utilization, category_breakdown, period_summary
from app.services.anomaly_service import detect_anomalies
from app.services.bill_service import bill_status, due_soon
from app.services.goal_service import goal_progress

log = logging.getLogger(__name__)


def in_app_alerts(user_id: int, today: date | None = None) -> list[dict]:
    """Things that need attention now. Each alert: {"level": "error"|"warning"|"info", "text"}."""
    today = today or date.today()
    alerts: list[dict] = []

    for bill, status in due_soon(user_id, today):
        level = "error" if status["level"] == "overdue" else "warning"
        alerts.append({"level": level, "text": f"{bill.name}: {RS}{bill.amount:,.0f}, {status['label'].lower()}"})

    for item in budget_utilization(user_id, today):
        if item["percent"] > 100:
            alerts.append(
                {
                    "level": "error",
                    "text": f"{item['category']} is over budget: {RS}{item['spent']:,.0f} of {RS}{item['limit']:,.0f}",
                }
            )
        elif item["percent"] > 80:
            alerts.append(
                {"level": "warning", "text": f"{item['category']} has used {item['percent']:.0f}% of its budget"}
            )

    for a in detect_anomalies(user_id, 7, today)[:3]:
        alerts.append(
            {
                "level": "info",
                "text": f"Unusual spend: {RS}{a['amount']:,.0f} on {a['category']} ({a['times_usual']}x usual)",
            }
        )

    for g in goal_progress(user_id, today):
        if g["on_track"] is False and g["target_date"] and (g["target_date"] - today).days < 90:
            alerts.append(
                {
                    "level": "warning",
                    "text": f"'{g['name']}' is behind schedule. Save {RS}{g['required_monthly']:,.0f}/month to catch up",
                }
            )
    return alerts


def _users(session):
    return list(session.scalars(select(User)))


def send_bill_reminders(today: date | None = None) -> int:
    """Email each user about bills entering their reminder window. Returns emails sent."""
    today = today or date.today()
    sent = 0
    with get_session() as session:
        users = {u.id: u for u in _users(session) if u.email_reminders}
        bills = list(session.scalars(select(Bill).where(Bill.active.is_(True))))
    for bill in bills:
        user = users.get(bill.user_id)
        if user is None:
            continue
        status = bill_status(bill, today)
        if status["days"] > bill.remind_days_before or bill.last_reminded_for == bill.next_due_date:
            continue
        try:
            email_service.send_email(
                user.email,
                f"Reminder: {bill.name} {status['label'].lower()}",
                f"Hi {user.name},\n\n{bill.name} ({RS}{bill.amount:,.2f}) is {status['label'].lower()} "
                f"(due {bill.next_due_date:%d %b %Y}).\n\nOnce paid, mark it as paid in FinanceOS so we "
                "remind you about the next one.\n\nTurn off reminders any time in Settings.",
            )
        except Exception:
            log.warning("Bill reminder to user %s failed", user.id, exc_info=True)
            continue
        with get_session() as session:
            stored = session.get(Bill, bill.id)
            stored.last_reminded_for = bill.next_due_date
        sent += 1
    return sent


def weekly_summary_text(user: User, today: date) -> str:
    start = today - timedelta(days=7)
    end = today - timedelta(days=1)
    s = period_summary(user.id, start, end)
    cats = category_breakdown(user.id, start, end).head(3)
    lines = [
        f"Hi {user.name}, here's your week ({start:%d %b} to {end:%d %b}).",
        "",
        f"Spent: {RS}{s['spending']:,.0f}",
        f"Received: {RS}{s['income']:,.0f}",
        f"Invested: {RS}{s['invested']:,.0f}",
    ]
    if not cats.empty:
        lines += ["", "Top categories:"] + [f"  {r.category}: {RS}{r.amount:,.0f}" for r in cats.itertuples()]
    upcoming = [b for b, st in due_soon(user.id, today, within_days=7)]
    if upcoming:
        lines += ["", "Bills due this week:"] + [
            f"  {b.name}: {RS}{b.amount:,.0f} on {b.next_due_date:%d %b}" for b in upcoming
        ]
    lines += ["", "Turn off weekly summaries any time in Settings."]
    return "\n".join(lines)


def send_weekly_summaries(today: date | None = None, force: bool = False) -> int:
    """Sends on Mondays (or any day with force=True), once per user per day."""
    today = today or date.today()
    if today.weekday() != 0 and not force:
        return 0
    sent = 0
    with get_session() as session:
        users = [u for u in _users(session) if u.weekly_summary and u.last_weekly_summary_on != today]
    for user in users:
        try:
            email_service.send_email(user.email, "Your FinanceOS week", weekly_summary_text(user, today))
        except Exception:
            log.warning("Weekly summary to user %s failed", user.id, exc_info=True)
            continue
        with get_session() as session:
            session.get(User, user.id).last_weekly_summary_on = today
        sent += 1
    return sent


def run_daily(today: date | None = None) -> dict:
    return {"reminders": send_bill_reminders(today), "weekly_summaries": send_weekly_summaries(today)}
