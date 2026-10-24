import pandas as pd
import plotly.express as px
import streamlit as st

from app.services.analytics_service import category_breakdown, merchant_breakdown, period_summary
from app.services.anomaly_service import detect_anomalies
from app.services.insights_service import spending_insights
from app.ui.theme import page_header
from app.ui.common import current_user_id, fmt_inr, period_picker

user_id = current_user_id()
page_header("Insights", "Patterns in your spending for any period.")

start, end = period_picker("insights")
summary = period_summary(user_id, start, end)
info = spending_insights(user_id, start, end)

if info["count"] == 0:
    st.info("No spending in this period.")
    st.stop()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Spending", fmt_inr(summary["spending"]), border=True)
c2.metric("Payments", info["count"], border=True)
c3.metric("Average payment", fmt_inr(info["average"]), border=True)
c4.metric(
    "Biggest payment", fmt_inr(info["highest"]["amount"]), info["highest"]["category"], delta_color="off", border=True
)

st.write(
    f"Most spent on **{info['top_category']}**. Most frequent: **{info['most_frequent_category']}**."
    + (f" Top merchant: **{info['top_merchant']}**." if info["top_merchant"] else "")
)

left, right = st.columns(2)
with left:
    st.subheader("By category")
    cats = category_breakdown(user_id, start, end)
    fig = px.bar(cats, x="amount", y="category", orientation="h")
    fig.update_layout(
        height=420,
        margin=dict(l=0, r=0, t=10, b=0),
        yaxis=dict(autorange="reversed", title=None),
        xaxis=dict(title=None, tickprefix="₹"),
    )
    st.plotly_chart(fig, width="stretch")

with right:
    st.subheader("Top merchants")
    merchants = merchant_breakdown(user_id, start, end)
    st.dataframe(
        merchants.rename(columns={"merchant": "Merchant", "amount": "Spent", "count": "Payments"}),
        width="stretch",
        hide_index=True,
        column_config={"Spent": st.column_config.NumberColumn(format="₹%.0f")},
    )

st.subheader("Largest payments")
st.dataframe(
    pd.DataFrame(info["top_five"]).rename(columns=str.title),
    width="stretch",
    hide_index=True,
    column_config={"Amount": st.column_config.NumberColumn(format="₹%.2f")},
)

anomalies = [a for a in detect_anomalies(user_id, (end - start).days + 1, end) if start <= a["date"] <= end]
if anomalies:
    st.subheader("Unusual spends")
    for a in anomalies:
        st.warning(
            f"{a['date']:%d %b}: {fmt_inr(a['amount'])} on {a['category']}, {a['times_usual']}x your usual {fmt_inr(a['usual'])}"
        )
