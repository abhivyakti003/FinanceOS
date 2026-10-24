import streamlit as st

from app.services import account_service, import_service
from app.services.import_service import StatementError
from app.ui.theme import page_header
from app.ui.common import current_user_id, fmt_inr

user_id = current_user_id()
page_header(
    "Import statement", "Upload the CSV, Excel or PDF you download from net banking. Already-imported rows are skipped."
)

accounts = [a for a in account_service.list_accounts(user_id) if a.account_type != "Cash"]
NEW = -1
options = [a.id for a in accounts] + [NEW]
names = {a.id: f"{a.name} ({a.account_type})" for a in accounts}
names[NEW] = "Add a new account"

account_id = st.selectbox("Which account is this statement for?", options, format_func=names.get)
if account_id == NEW:
    with st.form("new_account"):
        c1, c2, c3 = st.columns(3)
        name = c1.text_input("Account name", placeholder="HDFC Savings")
        kind = c2.selectbox("Type", [t for t in account_service.ACCOUNT_TYPES if t != "Cash"])
        bank = c3.text_input("Bank", placeholder="HDFC Bank")
        if st.form_submit_button("Add account"):
            try:
                account_service.create_account(user_id, name, kind, 0, institution=bank)
                st.rerun()
            except account_service.AccountError as exc:
                st.error(str(exc))
    st.stop()

upload = st.file_uploader("Statement file", type=["csv", "xlsx", "xls", "pdf"])
password = None
if upload and upload.name.lower().endswith(".pdf"):
    password = st.text_input(
        "PDF password (if the statement has one)",
        type="password",
        help="Often your date of birth, or part of your name plus account number.",
    )

if not upload:
    st.stop()

try:
    parsed = import_service.parse_statement(upload.getvalue(), upload.name, password)
except StatementError as exc:
    st.error(str(exc))
    st.stop()

debits = sum(r["amount"] for r in parsed.rows if r["txn_type"] == "debit")
credits = sum(r["amount"] for r in parsed.rows if r["txn_type"] == "credit")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Transactions found", len(parsed.rows), border=True)
c2.metric("Period", f"{parsed.start_date:%d %b} – {parsed.end_date:%d %b %Y}", border=True)
c3.metric("Money out", fmt_inr(debits), border=True)
c4.metric("Money in", fmt_inr(credits), border=True)
if parsed.skipped_lines:
    st.caption(f"{parsed.skipped_lines} lines that weren't transactions (totals, notes) were ignored.")

st.dataframe(
    parsed.preview(),
    width="stretch",
    height=320,
    hide_index=True,
    column_config={
        "Debit": st.column_config.NumberColumn(format="₹%.2f"),
        "Credit": st.column_config.NumberColumn(format="₹%.2f"),
        "Balance": st.column_config.NumberColumn(format="₹%.2f"),
    },
)

update_balance = False
if parsed.closing_balance is not None:
    update_balance = st.checkbox(
        f"Set this account's balance to the statement's closing balance ({fmt_inr(parsed.closing_balance, 2)})",
        value=True,
    )

if st.button(f"Import {len(parsed.rows)} transactions", type="primary"):
    result = import_service.import_statement(user_id, account_id, parsed, update_balance)
    msg = f"Imported {result['inserted']} new transactions."
    if result["skipped"]:
        msg += f" Skipped {result['skipped']} already imported."
    if update_balance and not result["balance_updated"]:
        msg += " Balance not changed because this account already has newer transactions."
    st.success(msg)
    st.page_link("pages/transactions.py", label="Review transactions and categories", icon="💳")
