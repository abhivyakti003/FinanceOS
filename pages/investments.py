import pandas as pd
import plotly.express as px
import streamlit as st

from app.services import investment_service as inv
from app.services.investment_service import InvestmentError
from app.ui.common import current_user_id, fmt_inr
from app.ui.theme import chart_layout, page_header

user_id = current_user_id()
page_header("Investments", "Mutual funds, stocks, EPF, PPF, NPS, deposits and more.")

summary = inv.portfolio_summary(user_id)
c1, c2, c3 = st.columns(3)
c1.metric("Current value", fmt_inr(summary["current"]), border=True)
c2.metric("Invested", fmt_inr(summary["invested"]), border=True)
gain_text = f"{summary['gain_percent']:+.1f}%" if summary["gain_percent"] is not None else None
c3.metric("Gain", fmt_inr(summary["gain"]), gain_text, border=True)

tab_holdings, tab_add, tab_cas = st.tabs(["Holdings", "Add manually", "Import CAS"])

with tab_holdings:
    holdings = inv.list_holdings(user_id)
    if not holdings:
        st.caption("No investments yet. Add one by hand or import your CAS statement.")
    else:
        left, right = st.columns([3, 2], gap="large")
        with right:
            alloc = inv.allocation(user_id)
            df = pd.DataFrame({"Type": list(alloc), "Value": [float(v) for v in alloc.values()]})
            fig = px.pie(df, names="Type", values="Value", hole=0.62)
            fig.update_traces(textinfo="none", hovertemplate="%{label}<br>₹%{value:,.0f} · %{percent}<extra></extra>")
            fig.update_layout(legend=dict(orientation="v", x=1.0, y=0.5))
            st.plotly_chart(chart_layout(fig, 300, None), width="stretch")
        with left:
            table = pd.DataFrame(
                [
                    {
                        "id": h.id,
                        "Remove": False,
                        "Name": h.name,
                        "Type": h.holding_type,
                        "Invested": float(h.invested),
                        "Current value": float(h.current_value),
                        "Gain %": round((float(h.current_value) / float(h.invested) - 1) * 100, 1)
                        if h.invested
                        else None,
                        "Updated": h.updated_at.date(),
                    }
                    for h in holdings
                ]
            ).set_index("id")
            edited = st.data_editor(
                table,
                hide_index=True,
                width="stretch",
                key="holdings_editor",
                disabled=["Name", "Type", "Gain %", "Updated"],
                column_config={
                    "Invested": st.column_config.NumberColumn(format="₹%.0f", min_value=0),
                    "Current value": st.column_config.NumberColumn(format="₹%.0f", min_value=0),
                    "Gain %": st.column_config.NumberColumn(format="%.1f%%"),
                    "Remove": st.column_config.CheckboxColumn(width="small"),
                },
            )
            st.caption("Edit values directly in the table, then save.")
            changed = edited[
                (edited["Invested"] != table["Invested"]) | (edited["Current value"] != table["Current value"])
            ]
            removed = edited.index[edited["Remove"]].tolist()
            if len(changed) or removed:
                if st.button("Save changes", type="primary"):
                    for hid, row in changed.iterrows():
                        if hid not in removed:
                            inv.update_holding(
                                user_id, int(hid), current_value=row["Current value"], invested=row["Invested"]
                            )
                    for hid in removed:
                        inv.delete_holding(user_id, int(hid))
                    st.session_state.pop("holdings_editor", None)
                    st.rerun()

with tab_add:
    with st.form("add_holding", clear_on_submit=True):
        name = st.text_input("Name", placeholder="Parag Parikh Flexi Cap, HDFC Bank shares, EPF")
        c1, c2 = st.columns(2)
        kind = c1.selectbox("Type", inv.HOLDING_TYPES)
        units = c2.number_input("Units or shares (optional)", min_value=0.0, step=1.0, format="%.4f")
        c1, c2 = st.columns(2)
        invested = c1.number_input("Amount invested (₹)", min_value=0.0, step=1000.0)
        current = c2.number_input(
            "Current value (₹)", min_value=0.0, step=1000.0, help="Leave as 0 to use the invested amount."
        )
        if st.form_submit_button("Add investment", type="primary"):
            try:
                inv.add_holding(user_id, name, kind, invested, current, units or None)
                st.toast("Investment added")
                st.rerun()
            except InvestmentError as exc:
                st.error(str(exc))

with tab_cas:
    st.markdown(
        "A **Consolidated Account Statement** lists all your mutual funds (and demat holdings) in one PDF. "
        "Get it free by email from **camsonline.com** → Statements → CAS (mutual funds), or **nsdl.co.in / "
        "cdslindia.com** (stocks and mutual funds in demat)."
    )
    upload = st.file_uploader("CAS PDF", type=["pdf"], key="cas_upload")
    password = st.text_input("PDF password", type="password", help="Usually your PAN in capital letters.")
    if st.button("Import holdings", type="primary", disabled=upload is None):
        with st.spinner("Reading your statement..."):
            try:
                result = inv.import_cas(user_id, upload.getvalue(), password)
                st.success(f"Added {result['added']} and updated {result['updated']} holdings.")
            except InvestmentError as exc:
                st.error(str(exc))
