from html import escape

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.services import account_service, transaction_service
from app.services.analytics_service import category_breakdown, monthly_summary, period_summary
from app.services.forecast_service import forecast_next_month
from app.services.health_service import health_report
from app.services.notification_service import in_app_alerts
from app.services.recommendation_service import generate_recommendations
from app.services.wealth_service import net_worth
from app.ui.common import current_user_id, empty_state, fmt_inr, month_picker
from app.ui.theme import GREEN, RED, alert_list, chart_layout, hero

user_id = current_user_id()

if not transaction_service.list_transactions(user_id, limit=1):
    st.title("Welcome to FinanceOS")
    empty_state("Add your money in one of three ways to get started.")
    st.stop()

top_left, top_right = st.columns([3, 1])
with top_right:
    start, end = month_picker("overview_month", label="Month")
summary = period_summary(user_id, start, end)

with top_left:
    st.title(f"{start:%B %Y}")

saved = summary["savings"]
if summary["income"] > 0:
    tone = "pos" if saved >= 0 else "neg"
    verb = "kept" if saved >= 0 else "overspent by"
    hero(
        f'You spent <span class="fos-num">{escape(fmt_inr(summary["spending"]))}</span> '
        f'and {verb} <span class="{tone} fos-num">{escape(fmt_inr(abs(saved)))}</span>'
        f'<span class="soft"> of {escape(fmt_inr(summary["income"]))} earned.</span>'
    )
else:
    hero(
        f'You spent <span class="fos-num">{escape(fmt_inr(summary["spending"]))}</span>'
        f'<span class="soft"> this month. No income recorded yet.</span>'
    )

health = health_report(user_id)
forecast = forecast_next_month(user_id)
worth = net_worth(user_id)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Bank and cash", fmt_inr(account_service.total_balance(user_id)), border=True)
c2.metric("Net worth", fmt_inr(worth["net_worth"]), border=True)
c3.metric(
    "Health score",
    f"{health['score']}/100" if health["score"] is not None else "–",
    health["status"],
    delta_color="off",
    border=True,
)
c4.metric(
    "Next month, expected spend",
    fmt_inr(forecast["spending"]),
    f"from {forecast['months_used']} months" if forecast["months_used"] else "needs a full month",
    delta_color="off",
    border=True,
)

st.write("")
left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Where it went")
    cats = category_breakdown(user_id, start, end)
    if cats.empty:
        st.caption("No spending this month yet.")
        selected = None
    else:
        fig = px.pie(cats, names="category", values="amount", hole=0.62)
        fig.update_traces(
            textinfo="none", hovertemplate="%{label}<br>₹%{value:,.0f} · %{percent}<extra></extra>", sort=True
        )
        fig.update_layout(height=330, showlegend=True, legend=dict(orientation="v", x=1.02, y=0.5))
        st.plotly_chart(fig, width="stretch", key="overview_donut")
        selected = st.pills("See transactions for", cats["category"].tolist(), key="overview_cat")

with right:
    st.subheader("Needs attention")
    alert_list(in_app_alerts(user_id))
    st.write("")
    st.subheader("Suggestions")
    for tip in generate_recommendations(user_id)[:4]:
        st.markdown(f"- {tip}")

if selected:
    st.subheader(f"{selected} in {start:%B}")
    txns = transaction_service.list_transactions(user_id, start=start, end=end, category=selected)
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Date": t.txn_date,
                    "Merchant": t.merchant or "",
                    "Details": t.description or t.narration,
                    "Amount": float(t.amount),
                }
                for t in txns
                if t.txn_type == "debit"
            ]
        ),
        width="stretch",
        hide_index=True,
        column_config={
            "Amount": st.column_config.NumberColumn(format="₹%.2f"),
            "Date": st.column_config.DateColumn(format="DD MMM YYYY"),
        },
    )

st.write("")
st.subheader("Last 12 months")
months = monthly_summary(user_id, 12)
fig = go.Figure()
fig.add_bar(
    x=months["label"],
    y=months["income"],
    name="Income",
    marker_color=GREEN,
    hovertemplate="%{x}<br>Income ₹%{y:,.0f}<extra></extra>",
)
fig.add_bar(
    x=months["label"],
    y=months["spending"],
    name="Spending",
    marker_color=RED,
    hovertemplate="%{x}<br>Spending ₹%{y:,.0f}<extra></extra>",
)
fig.add_scatter(
    x=months["label"],
    y=months["savings"],
    name="Saved",
    mode="lines+markers",
    line=dict(color="#8A8F98", width=2, dash="dot"),
    hovertemplate="%{x}<br>Saved ₹%{y:,.0f}<extra></extra>",
)
fig.update_layout(barmode="group", bargap=0.35)
st.plotly_chart(chart_layout(fig, 340), width="stretch")
