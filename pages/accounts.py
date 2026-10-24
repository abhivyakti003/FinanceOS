import pandas as pd
import streamlit as st

from app.services import aa_service, account_service
from app.services.account_service import AccountError
from app.ui.theme import page_header
from app.ui.common import current_user_id, fmt_inr

user_id = current_user_id()
page_header("Accounts", "Banks, cards, wallets and cash.")

rows = account_service.accounts_with_balances(user_id)
c1, c2 = st.columns(2)
c1.metric("Bank and cash balance", fmt_inr(account_service.total_balance(user_id)), border=True)
c2.metric(
    "Available to spend",
    fmt_inr(account_service.liquid_balance(user_id)),
    help="Savings, current, salary accounts, cash and wallets. Excludes investments and card dues.",
    border=True,
)

if rows:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Account": r["name"],
                    "Type": r["type"],
                    "Bank": r["institution"] or "",
                    "Number": r["masked_number"] or "",
                    "Balance": float(r["balance"]),
                    "Linked via": "Account Aggregator" if r["source"] == "aa" else "Manual / statement",
                }
                for r in rows
            ]
        ),
        width="stretch",
        hide_index=True,
        column_config={"Balance": st.column_config.NumberColumn(format="₹%.2f")},
    )
else:
    st.info("No accounts yet. Add one below or link your bank.")

# ---------------------------------------------------------------------------
tab_add, tab_edit, tab_link = st.tabs(["Add account", "Edit account", "Link bank automatically"])

with tab_add:
    with st.form("add_account", clear_on_submit=True):
        c1, c2 = st.columns(2)
        name = c1.text_input("Account name", placeholder="HDFC Savings")
        kind = c2.selectbox("Type", account_service.ACCOUNT_TYPES)
        c1, c2, c3 = st.columns(3)
        bank = c1.text_input("Bank or provider", placeholder="HDFC Bank")
        number = c2.text_input("Last 4 digits (optional)", max_chars=4)
        balance = c3.number_input(
            "Current balance (₹)",
            min_value=0.0,
            step=100.0,
            help="For a credit card, enter the amount you currently owe.",
        )
        if st.form_submit_button("Add account", type="primary"):
            try:
                account_service.create_account(user_id, name, kind, balance, bank, f"XXXX{number}" if number else None)
                st.rerun()
            except AccountError as exc:
                st.error(str(exc))

with tab_edit:
    if not rows:
        st.caption("Add an account first.")
    else:
        names = {r["id"]: r["name"] for r in rows}
        selected = st.selectbox("Account", list(names), format_func=names.get, key="edit_account")
        current = next(r for r in rows if r["id"] == selected)
        with st.form("update_balance"):
            new_balance = st.number_input(
                "Balance shown by your bank today (₹)",
                value=abs(float(current["balance"])),
                step=100.0,
                help="Use this when the balance here doesn't match your bank. For cards, enter the amount owed.",
            )
            if st.form_submit_button("Update balance"):
                account_service.set_current_balance(user_id, selected, new_balance)
                st.rerun()
        with st.form("rename"):
            new_name = st.text_input("New name", value=current["name"])
            if st.form_submit_button("Rename"):
                try:
                    account_service.rename_account(user_id, selected, new_name)
                    st.rerun()
                except AccountError as exc:
                    st.error(str(exc))
        st.markdown("**Delete account**")
        confirm = st.checkbox(f"I understand this deletes {current['name']} and all its transactions")
        if st.button("Delete account", disabled=not confirm):
            account_service.delete_account(user_id, selected)
            st.rerun()

with tab_link:
    st.write(
        "Link bank accounts through India's Account Aggregator network. You approve access with an OTP "
        "in your AA app. FinanceOS never sees your net banking password."
    )
    if aa_service.is_mock():
        st.warning(
            "Sample mode: linking creates a demo HDFC account with sample transactions. "
            "Set AA_PROVIDER and your partner's keys in .env to connect real banks."
        )
    with st.form("aa_link"):
        mobile = st.text_input("Mobile number linked to your bank", max_chars=10)
        if st.form_submit_button("Link accounts", type="primary"):
            try:
                consent = aa_service.start_link(user_id, mobile)
                redirect = getattr(consent, "redirect_url", None)
                if redirect:
                    st.link_button("Approve in your AA app", redirect)
                else:
                    result = aa_service.sync_consent(user_id, consent.id)
                    st.success(f"Linked {result['accounts']} account(s), imported {result['inserted']} transactions.")
            except (aa_service.AAError, NotImplementedError) as exc:
                st.error(str(exc))

    consents = aa_service.list_consents(user_id)
    for consent in consents:
        c1, c2, c3 = st.columns([3, 1, 1])
        last = f"{consent.last_fetched_at:%d %b %Y %H:%M}" if consent.last_fetched_at else "never"
        c1.write(f"Consent {consent.id}: **{consent.status}**, last synced {last}")
        if consent.status != "REVOKED":
            if c2.button("Sync now", key=f"sync_{consent.id}"):
                result = aa_service.sync_consent(user_id, consent.id)
                st.toast(f"{result['inserted']} new transactions")
                st.rerun()
            if c3.button("Revoke", key=f"revoke_{consent.id}"):
                aa_service.revoke_consent(user_id, consent.id)
                st.rerun()
