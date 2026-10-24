"""FinanceOS entry point.

Run with:
    streamlit run streamlit_app.py
(or double-click run.bat on Windows)
"""

import time

import streamlit as st

from app import config
from app.database.init_db import upgrade_database
from app.logging_config import setup_logging
from app.services import admin_service, auth_service, bill_service, family_service
from app.services.auth_service import AuthError
from app.ui import legal
from app.ui.theme import apply_theme

st.set_page_config(page_title="FinanceOS", page_icon="💰", layout="wide")
setup_logging()
apply_theme()

# Refuse to run in production with unsafe settings.
_errors, _warnings = config.validate_settings()
if _errors:
    st.error("FinanceOS can't start because of these settings problems:")
    for problem in _errors:
        st.markdown(f"- {problem}")
    st.caption("Fix them in .env and restart. See docs/DEPLOYMENT.md.")
    st.stop()


@st.cache_resource
def _prepare_database():
    upgrade_database()
    return True


_prepare_database()


def _log_in(user) -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]  # clear anything left from a previous user
    st.session_state.user_id = user.id
    st.session_state.last_seen = time.time()
    st.rerun()


# ---------------------------------------------------------------------------
# Logged-out screens
# ---------------------------------------------------------------------------


def login_tab():
    with st.form("login"):
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Log in", type="primary", width="stretch")
    if submitted:
        try:
            _log_in(auth_service.authenticate(email, password))
        except AuthError as exc:
            st.error(str(exc))

    with st.expander("Forgot your password?"):
        reset_flow()


def reset_flow():
    state = st.session_state
    if not state.get("reset_email"):
        with st.form("reset_start"):
            email = st.text_input("Email you registered with")
            if st.form_submit_button("Send reset code"):
                try:
                    auth_service.start_password_reset(email)
                    state.reset_email = auth_service.normalize_email(email)
                    st.rerun()
                except AuthError as exc:
                    st.error(str(exc))
        return

    st.caption(f"If {state.reset_email} has an account, we've emailed it a 6-digit code.")
    with st.form("reset_finish"):
        code = st.text_input("Code", max_chars=6)
        new_password = st.text_input("New password", type="password", autocomplete="new-password")
        confirm = st.text_input("Confirm new password", type="password", autocomplete="new-password")
        if st.form_submit_button("Reset password", type="primary"):
            if new_password != confirm:
                st.error("The passwords don't match.")
            else:
                try:
                    auth_service.complete_password_reset(state.reset_email, code, new_password)
                    state.pop("reset_email")
                    st.success("Password reset. You can log in now.")
                except AuthError as exc:
                    st.error(str(exc))
    if st.button("Use a different email", key="reset_change"):
        state.pop("reset_email")
        st.rerun()


def register_tab():
    state = st.session_state

    if not state.get("pending_email"):
        with st.form("register"):
            name = st.text_input("Full name", autocomplete="name")
            email = st.text_input("Email", autocomplete="email")
            password = st.text_input(
                "Password",
                type="password",
                autocomplete="new-password",
                help="At least 8 characters, with a letter and a number.",
            )
            confirm = st.text_input("Confirm password", type="password", autocomplete="new-password")
            accepted = st.checkbox("I'm 18 or older and I accept the Terms of Service and Privacy Policy")
            submitted = st.form_submit_button("Send verification code", type="primary", width="stretch")
        c1, c2 = st.columns(2)
        if c1.button("Read the Terms", width="stretch", key="terms_btn"):
            legal.show_terms()
        if c2.button("Read the Privacy Policy", width="stretch", key="privacy_btn"):
            legal.show_privacy()
        if submitted:
            if password != confirm:
                st.error("The passwords don't match.")
                return
            with st.spinner("Checking your email address..."):
                try:
                    state.pending_email = auth_service.start_registration(name, email, password, accepted)
                    st.rerun()
                except AuthError as exc:
                    st.error(str(exc))
        return

    st.success(
        f"We sent a 6-digit code to **{state.pending_email}**. It expires in {config.OTP_EXPIRY_MINUTES} minutes."
    )
    st.caption("Can't find it? Check your spam folder.")
    with st.form("verify"):
        code = st.text_input("Verification code", max_chars=6, autocomplete="one-time-code")
        verified = st.form_submit_button("Verify and create account", type="primary", width="stretch")
    if verified:
        try:
            _log_in(auth_service.verify_registration(state.pending_email, code))
        except AuthError as exc:
            st.error(str(exc))

    c1, c2 = st.columns(2)
    if c1.button("Send a new code", width="stretch"):
        try:
            auth_service.resend_registration_code(state.pending_email)
            st.toast("New code sent.")
        except AuthError as exc:
            st.error(str(exc))
    if c2.button("Use a different email", width="stretch"):
        state.pop("pending_email")
        st.rerun()


def auth_screen():
    _, middle, _ = st.columns([1, 1.25, 1])
    with middle:
        st.write("")
        st.markdown('<p class="fos-brand">Finance<span>OS</span></p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="fos-hero">Every account, every rupee,<br><span class="soft">in one calm place.</span></p>',
            unsafe_allow_html=True,
        )
        if not config.IS_PRODUCTION:
            for warning in _warnings:
                st.warning(warning)
        login, register = st.tabs(["Log in", "Create account"])
        with login:
            login_tab()
        with register:
            register_tab()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

user = auth_service.get_user(st.session_state.get("user_id"))

# Log out after a period without activity, or if an admin disabled the account.
if user is not None:
    idle = time.time() - st.session_state.get("last_seen", time.time())
    if idle > config.SESSION_TIMEOUT_MINUTES * 60:
        st.session_state.clear()
        st.session_state.logout_reason = "You were logged out after a period of inactivity."
        user = None
    elif not user.is_active:
        st.session_state.clear()
        st.session_state.logout_reason = "This account has been disabled."
        user = None
    else:
        st.session_state.last_seen = time.time()

if user is None:
    st.session_state.pop("user_id", None)
    if reason := st.session_state.pop("logout_reason", None):
        st.info(reason)
    auth_screen()
    st.stop()

due_count = len(bill_service.due_soon(user.id))
invite_count = len(family_service.incoming(user.id, "pending"))

with st.sidebar:
    st.markdown('<p class="fos-brand">Finance<span>OS</span></p>', unsafe_allow_html=True)
    st.caption(f"{user.name} · {user.email}")
    if st.button("Log out", width="stretch"):
        st.session_state.clear()
        st.rerun()
    st.caption(f"v{config.APP_VERSION}" + ("" if config.IS_PRODUCTION else " · development"))

pages = {
    "": [
        st.Page("pages/overview.py", title="Overview", icon=":material/space_dashboard:", default=True),
        st.Page("pages/transactions.py", title="Transactions", icon=":material/receipt_long:"),
        st.Page("pages/insights.py", title="Insights", icon=":material/insights:"),
    ],
    "Money": [
        st.Page("pages/accounts.py", title="Accounts", icon=":material/account_balance:"),
        st.Page("pages/import_statement.py", title="Import statement", icon=":material/upload_file:"),
        st.Page("pages/investments.py", title="Investments", icon=":material/trending_up:"),
        st.Page("pages/bills.py", title=f"Bills ({due_count} due)" if due_count else "Bills", icon=":material/event:"),
        st.Page("pages/recurring.py", title="Recurring payments", icon=":material/autorenew:"),
    ],
    "Plan": [
        st.Page("pages/budgets.py", title="Budgets", icon=":material/donut_small:"),
        st.Page("pages/goals.py", title="Goals", icon=":material/flag:"),
        st.Page("pages/net_worth.py", title="Net worth", icon=":material/account_balance_wallet:"),
        st.Page("pages/credit_score.py", title="Credit score", icon=":material/speed:"),
    ],
    "More": [
        st.Page(
            "pages/family.py",
            title=f"Family ({invite_count} new)" if invite_count else "Family",
            icon=":material/group:",
        ),
        st.Page("pages/reports.py", title="Reports", icon=":material/description:"),
        st.Page("pages/settings.py", title="Settings", icon=":material/settings:"),
    ],
}
if admin_service.is_admin(user):
    pages["More"].append(st.Page("pages/admin.py", title="Admin", icon=":material/admin_panel_settings:"))
st.navigation(pages).run()
