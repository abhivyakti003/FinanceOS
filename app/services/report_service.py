"""PDF report generated in memory and returned as bytes.

The built-in PDF fonts can't draw the rupee sign (it showed up as a black
box), so the report uses "Rs." instead.
"""

import io
from datetime import date
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services import chart_service
from app.services.account_service import total_balance
from app.services.analytics_service import (
    budget_utilization,
    category_breakdown,
    monthly_summary,
    period_summary,
)
from app.services.anomaly_service import detect_anomalies
from app.services.auth_service import get_user
from app.services.bill_service import list_bills
from app.services.forecast_service import forecast_next_month
from app.services.goal_service import goal_progress
from app.services.health_service import health_report
from app.services.insights_service import spending_insights
from app.services.investment_service import portfolio_summary
from app.services.recommendation_service import generate_recommendations
from app.services.recurring_service import detect_recurring
from app.services.wealth_service import net_worth

BLUE = colors.HexColor("#1f4e79")


def rs(value) -> str:
    return f"Rs. {float(value):,.0f}"


def _table(data, col_widths=None):
    table = Table(data, colWidths=col_widths, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5f8")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9d2db")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _image(png: bytes | None, width_cm: float = 16):
    if not png:
        return None
    img = Image(io.BytesIO(png))
    ratio = img.imageHeight / img.imageWidth
    img.drawWidth = width_cm * cm
    img.drawHeight = width_cm * cm * ratio
    return img


def generate_report(user_id: int, start: date, end: date) -> bytes:
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor=BLUE, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=BLUE, spaceBefore=12, spaceAfter=6)
    body = styles["BodyText"]

    user = get_user(user_id)
    summary = period_summary(user_id, start, end)
    health = health_report(user_id)
    worth = net_worth(user_id)
    forecast = forecast_next_month(user_id)

    story = [
        Paragraph("FinanceOS financial report", h1),
        Paragraph(escape(f"{user.name if user else ''} | {start:%d %b %Y} to {end:%d %b %Y}"), body),
        Spacer(1, 10),
    ]

    rate = f"{summary['savings_rate']:.1f}%" if summary["savings_rate"] is not None else "-"
    score = f"{health['score']}/100 ({health['status']})" if health["score"] is not None else health["status"]
    story.append(
        _table(
            [
                ["Summary", ""],
                ["Income", rs(summary["income"])],
                ["Spending", rs(summary["spending"])],
                ["Invested", rs(summary["invested"])],
                ["Savings", rs(summary["savings"])],
                ["Savings rate", rate],
                ["Bank and cash balance (today)", rs(total_balance(user_id))],
                ["Investments (today)", rs(portfolio_summary(user_id)["current"])],
                ["Net worth (today)", rs(worth["net_worth"])],
                ["Financial health score", score],
                ["Expected spending next month", rs(forecast["spending"])],
            ],
            [9 * cm, 6 * cm],
        )
    )

    # Categories
    cats = category_breakdown(user_id, start, end)
    story.append(Paragraph("Where your money went", h2))
    if cats.empty:
        story.append(Paragraph("No spending in this period.", body))
    else:
        chart = _image(chart_service.category_chart(cats["category"].tolist(), cats["amount"].tolist()))
        if chart:
            story.append(chart)
        total = cats["amount"].sum()
        rows = [["Category", "Amount", "Share"]] + [
            [r.category, rs(r.amount), f"{r.amount / total * 100:.1f}%"] for r in cats.itertuples()
        ]
        story.append(_table(rows, [7 * cm, 4 * cm, 3 * cm]))

    # Monthly trend
    months = monthly_summary(user_id, 12)
    months = months[months["has_data"]]
    if not months.empty:
        story.append(Paragraph("Monthly trend", h2))
        chart = _image(
            chart_service.monthly_chart(
                months["label"].tolist(), months["income"].tolist(), months["spending"].tolist()
            )
        )
        if chart:
            story.append(chart)

    # Budgets
    budgets = budget_utilization(user_id, end)
    if budgets:
        story.append(Paragraph(f"Budgets for {end:%B %Y}", h2))
        chart = _image(
            chart_service.budget_chart([b["category"] for b in budgets], [b["percent"] for b in budgets]), 14
        )
        if chart:
            story.append(chart)
        story.append(
            _table(
                [["Category", "Budget", "Spent", "Used"]]
                + [[b["category"], rs(b["limit"]), rs(b["spent"]), f"{b['percent']:.0f}%"] for b in budgets],
                [6 * cm, 3.5 * cm, 3.5 * cm, 2.5 * cm],
            )
        )

    # Goals
    goals = goal_progress(user_id)
    if goals:
        story.append(Paragraph("Goals", h2))
        rows = [["Goal", "Saved", "Target", "Progress", "ETA"]]
        for g in goals:
            eta = "Done" if g["eta_months"] == 0 else (f"{g['eta_months']} months" if g["eta_months"] else "-")
            rows.append([g["name"], rs(g["current"]), rs(g["target"]), f"{g['percent']:.0f}%", eta])
        story.append(_table(rows, [5 * cm, 3 * cm, 3 * cm, 2.5 * cm, 2.5 * cm]))

    # Top expenses
    insights = spending_insights(user_id, start, end)
    if insights["top_five"]:
        story.append(Paragraph("Largest expenses", h2))
        rows = [["Date", "Category", "Merchant", "Amount"]] + [
            [f"{t['date']:%d %b %Y}", t["category"], (t["merchant"] or "")[:30], rs(t["amount"])]
            for t in insights["top_five"]
        ]
        story.append(_table(rows, [3 * cm, 4 * cm, 5.5 * cm, 3.5 * cm]))

    # Recurring
    recurring = [r for r in detect_recurring(user_id) if r["active"]]
    if recurring:
        story.append(Paragraph("Recurring payments", h2))
        rows = [["Merchant", "How often", "Amount", "Next expected"]] + [
            [r["merchant"] or "", r["frequency"], rs(r["average_amount"]), f"{r['next_expected']:%d %b %Y}"]
            for r in recurring[:10]
        ]
        story.append(_table(rows, [5.5 * cm, 3 * cm, 3.5 * cm, 4 * cm]))

    # Unusual spends
    anomalies = detect_anomalies(user_id)
    if anomalies:
        story.append(Paragraph("Unusual spends", h2))
        rows = [["Date", "Category", "Amount", "vs usual"]] + [
            [f"{a['date']:%d %b %Y}", a["category"], rs(a["amount"]), f"{a['times_usual']}x"] for a in anomalies[:10]
        ]
        story.append(_table(rows, [3.5 * cm, 5 * cm, 4 * cm, 3 * cm]))

    bills = list_bills(user_id)
    if bills:
        story.append(Paragraph("Upcoming bills", h2))
        story.append(
            _table(
                [["Bill", "Amount", "Due", "Repeats"]]
                + [[b.name, rs(b.amount), f"{b.next_due_date:%d %b %Y}", b.frequency] for b in bills[:12]],
                [6 * cm, 3.5 * cm, 3.5 * cm, 3 * cm],
            )
        )

    story.append(Paragraph("Suggestions", h2))
    for tip in generate_recommendations(user_id):
        story.append(Paragraph(escape("- " + tip.replace("₹", "Rs. ")), body))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title="FinanceOS report",
        author="FinanceOS",
    )
    doc.build(story)
    return buffer.getvalue()
