from datetime import date, timedelta

import pandas as pd
import streamlit as st

from app.services import account_service, categorization_service as cat, transaction_service as ts
from app.services.transaction_service import TransactionError
from app.ui.theme import page_header
from app.ui.common import current_user_id, fmt_inr

user_id = current_user_id()
page_header("Transactions", "Everything in and out of your accounts. Edit categories right in the table.")

accounts = account_service.list_accounts(user_id)
if not accounts:
    accounts = [account_service.ensure_cash_account(user_id)]
account_names = {a.id: a.name for a in accounts}

# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------
with st.expander("Add a transaction", expanded=False):
    kind = st.radio("Type", ["Spent", "Received"], horizontal=True, key="new_kind")
    txn_type = "debit" if kind == "Spent" else "credit"
    categories = cat.EXPENSE_CATEGORIES if txn_type == "debit" else cat.INCOME_CATEGORIES
    with st.form("add_txn", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        account_id = c1.selectbox("Account", list(account_names), format_func=account_names.get)
        amount = c2.number_input("Amount (₹)", min_value=0.0, step=10.0, format="%.2f")
        txn_date = c3.date_input("Date", date.today(), max_value=date.today())
        description = st.text_input("Description", placeholder="e.g. Swiggy dinner, Salary for September")
        category = st.selectbox("Category", ["Detect automatically"] + categories + [cat.TRANSFER_CATEGORY])
        if st.form_submit_button("Add transaction", type="primary"):
            try:
                txn = ts.add_transaction(
                    user_id,
                    account_id,
                    txn_date,
                    amount,
                    txn_type,
                    description=description,
                    category=None if category == "Detect automatically" else category,
                )
                st.toast(f"Added {fmt_inr(txn.amount)} as {txn.category}")
                st.rerun()
            except TransactionError as exc:
                st.error(str(exc))

# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
today = date.today()
c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
start, end = today - timedelta(days=90), today
date_range = c1.date_input("Dates", (start, end), max_value=today)
if isinstance(date_range, tuple) and len(date_range) == 2:
    start, end = date_range
account_filter = c2.selectbox(
    "Account", [None] + list(account_names), format_func=lambda i: "All accounts" if i is None else account_names[i]
)
category_filter = c3.selectbox(
    "Category", [None] + cat.ALL_CATEGORIES, format_func=lambda c: "All categories" if c is None else c
)
search = c4.text_input("Search", placeholder="Merchant, note or bank text")
hide_transfers = st.toggle("Hide transfers between my accounts", value=False)

txns = ts.list_transactions(
    user_id,
    start=start,
    end=end,
    account_id=account_filter,
    category=category_filter,
    search=search or None,
    include_transfers=not hide_transfers,
)

if not txns:
    st.info("No transactions match these filters.")
    st.stop()

debits = sum(float(t.amount) for t in txns if t.txn_type == "debit" and not t.is_transfer)
credits = sum(float(t.amount) for t in txns if t.txn_type == "credit" and not t.is_transfer)
m1, m2, m3 = st.columns(3)
m1.metric("Transactions", len(txns), border=True)
m2.metric("Money out", fmt_inr(debits), border=True)
m3.metric("Money in", fmt_inr(credits), border=True)

# ---------------------------------------------------------------------------
# Table (edit category, delete)
# ---------------------------------------------------------------------------
table = pd.DataFrame(
    [
        {
            "id": t.id,
            "Delete": False,
            "Date": t.txn_date,
            "Details": t.description or t.narration,
            "Merchant": t.merchant or "",
            "Category": t.category,
            "Amount": float(t.amount) if t.txn_type == "credit" else -float(t.amount),
            "Account": account_names.get(t.account_id, ""),
            "Mode": t.mode or "",
        }
        for t in txns
    ]
).set_index("id")

st.caption("Change a category to teach FinanceOS: other payments to the same merchant will follow.")
edited = st.data_editor(
    table,
    width="stretch",
    height=520,
    hide_index=True,
    disabled=["Date", "Details", "Merchant", "Amount", "Account", "Mode"],
    column_config={
        "Delete": st.column_config.CheckboxColumn(width="small"),
        "Category": st.column_config.SelectboxColumn(options=cat.ALL_CATEGORIES, required=True),
        "Amount": st.column_config.NumberColumn(format="₹%.2f", help="Negative = money out"),
        "Date": st.column_config.DateColumn(format="DD MMM YYYY"),
    },
    key="txn_editor",
)

changed = edited[edited["Category"] != table["Category"]]
to_delete = edited.index[edited["Delete"]].tolist()

if len(changed) or to_delete:
    label = []
    if len(changed):
        label.append(f"update {len(changed)} categor{'ies' if len(changed) != 1 else 'y'}")
    if to_delete:
        label.append(f"delete {len(to_delete)} transaction{'s' if len(to_delete) != 1 else ''}")
    if st.button("Save: " + " and ".join(label), type="primary"):
        for txn_id, row in changed.iterrows():
            if txn_id not in to_delete:
                ts.update_transaction(user_id, int(txn_id), category=row["Category"])
        deleted = ts.delete_transactions(user_id, [int(i) for i in to_delete])
        st.session_state.pop("txn_editor", None)
        st.toast(f"Saved. {deleted} deleted." if deleted else "Saved.")
        st.rerun()
