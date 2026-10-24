import pandas as pd
import plotly.express as px
import streamlit as st

from app.services import wealth_service as ws
from app.ui.theme import page_header
from app.ui.common import current_user_id, fmt_inr

user_id = current_user_id()
page_header("Net worth", "Accounts + investments + other assets, minus loans.")

worth = ws.net_worth(user_id)
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Net worth", fmt_inr(worth["net_worth"]), border=True)
c2.metric(
    "Accounts", fmt_inr(worth["accounts"]), help="From the Accounts page. Card dues count as negative.", border=True
)
c3.metric("Investments", fmt_inr(worth["investments"]), help="From the Investments page.", border=True)
c4.metric("Other assets", fmt_inr(worth["assets"]), border=True)
c5.metric("Loans", fmt_inr(worth["liabilities"]), border=True)
st.caption(
    "Bank balances and investments come from their own pages, so add only other things here, "
    "like property, a vehicle or jewellery."
)

left, right = st.columns(2)

with left:
    st.subheader("Assets")
    with st.form("asset", clear_on_submit=True):
        name = st.text_input("Name", placeholder="Flat in Pune, car, gold jewellery")
        c1, c2 = st.columns(2)
        category = c1.selectbox("Type", ws.ASSET_CATEGORIES)
        amount = c2.number_input("Current value (₹)", min_value=0.0, step=1000.0)
        if st.form_submit_button("Add asset"):
            try:
                ws.add_asset(user_id, name, category, amount)
                st.rerun()
            except ws.WealthError as exc:
                st.error(str(exc))
    for asset in ws.list_assets(user_id):
        c1, c2 = st.columns([4, 1])
        c1.write(f"**{asset.name}** ({asset.category}): {fmt_inr(asset.amount)}")
        if c2.button("Remove", key=f"asset_{asset.id}"):
            ws.delete_asset(user_id, asset.id)
            st.rerun()

    breakdown = ws.asset_breakdown(user_id)
    if breakdown:
        df = pd.DataFrame({"Type": list(breakdown), "Value": [float(v) for v in breakdown.values()]})
        fig = px.pie(df, names="Type", values="Value", hole=0.5)
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")

with right:
    st.subheader("Loans and debts")
    with st.form("liability", clear_on_submit=True):
        name = st.text_input("Name", placeholder="SBI home loan")
        c1, c2 = st.columns(2)
        category = c1.selectbox("Type", ws.LIABILITY_CATEGORIES)
        amount = c2.number_input("Amount outstanding (₹)", min_value=0.0, step=1000.0)
        if st.form_submit_button("Add loan or debt"):
            try:
                ws.add_liability(user_id, name, category, amount)
                st.rerun()
            except ws.WealthError as exc:
                st.error(str(exc))
    for item in ws.list_liabilities(user_id):
        c1, c2 = st.columns([4, 1])
        c1.write(f"**{item.name}** ({item.category}): {fmt_inr(item.amount)}")
        if c2.button("Remove", key=f"liab_{item.id}"):
            ws.delete_liability(user_id, item.id)
            st.rerun()
