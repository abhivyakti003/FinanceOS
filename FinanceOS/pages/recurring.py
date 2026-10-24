import pandas as pd
import streamlit as st

from app.services import bill_service
from app.services.recurring_service import detect_recurring
from app.ui.theme import page_header
from app.ui.common import current_user_id, fmt_inr

user_id = current_user_id()
page_header("Recurring payments", "Subscriptions, rent, SIPs and EMIs found automatically from your transactions.")

items = detect_recurring(user_id)
if not items:
    st.info("Nothing recurring found yet. This needs at least three payments to the same merchant.")
    st.stop()

active = [i for i in items if i["active"]]
st.metric(
    "Active recurring payments per month",
    fmt_inr(sum(i["monthly_cost"] for i in active)),
    f"{len(active)} active",
    delta_color="off",
    border=True,
)

st.dataframe(
    pd.DataFrame(
        [
            {
                "Merchant": i["merchant"],
                "Category": i["category"],
                "How often": i["frequency"],
                "Amount": i["average_amount"],
                "Per month": i["monthly_cost"],
                "Last paid": i["last_date"],
                "Next expected": i["next_expected"] if i["active"] else None,
                "Status": "Active" if i["active"] else "Stopped",
            }
            for i in items
        ]
    ),
    width="stretch",
    hide_index=True,
    column_config={
        "Amount": st.column_config.NumberColumn(format="₹%.0f"),
        "Per month": st.column_config.NumberColumn(format="₹%.0f"),
        "Last paid": st.column_config.DateColumn(format="DD MMM YYYY"),
        "Next expected": st.column_config.DateColumn(format="DD MMM YYYY"),
    },
)

if active:
    st.subheader("Get reminders")
    existing = {b.name.lower() for b in bill_service.list_bills(user_id)}
    candidates = [i for i in active if (i["merchant"] or "").lower() not in existing]
    if candidates:
        names = {i["merchant"]: i for i in candidates}
        chosen = st.multiselect("Add these as bills so we remind you before they're due", list(names))
        if st.button("Add as bills", type="primary", disabled=not chosen):
            for name in chosen:
                bill_service.create_from_recurring(user_id, names[name])
            st.toast(f"Added {len(chosen)} bill{'s' if len(chosen) != 1 else ''}")
            st.rerun()
    else:
        st.caption("All active recurring payments already have bill reminders.")
