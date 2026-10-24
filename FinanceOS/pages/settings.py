from datetime import date

import streamlit as st

from app.services import account_admin_service, audit_service, auth_service, email_service
from app.ui import legal
from app.services.auth_service import AuthError
from app.ui.common import current_user_id
from app.ui.theme import page_header, rows

user_id = current_user_id()
user = auth_service.get_user(user_id)
page_header("Settings")

left, right = st.columns(2, gap="large")

with left:
    st.subheader("Profile")
    rows(
        [
            ("Name", user.name),
            ("Email", f"{user.email} (verified)"),
            ("Member since", f"{user.created_at:%d %b %Y}"),
        ]
    )

    st.subheader("Emails")
    with st.form("prefs"):
        reminders = st.toggle(
            "Bill reminders", value=user.email_reminders, help="An email a few days before each bill is due."
        )
        weekly = st.toggle("Weekly summary every Monday", value=user.weekly_summary)
        if st.form_submit_button("Save"):
            account_admin_service.set_preferences(user_id, reminders, weekly)
            st.toast("Saved")
    st.caption("Reminder emails are sent by the daily task (notify.bat). See README to schedule it.")
    if st.button("Send me a test email"):
        try:
            email_service.send_email(
                user.email,
                "FinanceOS test email",
                "Your FinanceOS email is working. Reminders and codes will arrive like this.",
            )
            st.success(f"Sent to {user.email}. Check your inbox and spam folder.")
        except (email_service.EmailNotConfigured, email_service.EmailSendError) as exc:
            st.error(str(exc))

    st.subheader("Appearance")
    st.caption("Switch between light and dark from the ⋮ menu at the top right → Settings → Theme.")

    st.subheader("Recent account activity")
    labels = {
        "login_success": "Logged in",
        "login_failed": "Failed login attempt",
        "login_locked": "Login locked after failed attempts",
        "password_changed": "Password changed",
        "password_reset": "Password reset",
        "data_export": "Data downloaded",
        "register": "Account created",
        "family_invite": "Family invite sent",
        "family_revoke": "Stopped sharing",
    }
    events = audit_service.for_user(user_id, 8)
    if events:
        rows(
            [
                (labels.get(e.event, e.event.replace("_", " ").capitalize()), f"{e.created_at:%d %b %Y, %H:%M} UTC")
                for e in events
            ]
        )
        st.caption("Don't recognise something? Change your password now.")
    else:
        st.caption("No activity recorded yet.")

    st.subheader("Legal")
    c1, c2 = st.columns(2)
    if c1.button("Terms of Service", width="stretch"):
        legal.show_terms()
    if c2.button("Privacy Policy", width="stretch"):
        legal.show_privacy()

with right:
    st.subheader("Change password")
    with st.form("change_password", clear_on_submit=True):
        current = st.text_input("Current password", type="password", autocomplete="current-password")
        new = st.text_input("New password", type="password", autocomplete="new-password")
        confirm = st.text_input("Confirm new password", type="password", autocomplete="new-password")
        if st.form_submit_button("Change password", type="primary"):
            if new != confirm:
                st.error("The new passwords don't match.")
            else:
                try:
                    auth_service.change_password(user_id, current, new)
                    st.success("Password changed.")
                except AuthError as exc:
                    st.error(str(exc))

    st.subheader("Your data")
    st.caption("Download everything FinanceOS stores about you as an Excel file.")
    if st.button("Prepare my data"):
        st.session_state.export_bytes = account_admin_service.export_excel(user_id)
    if st.session_state.get("export_bytes"):
        st.download_button(
            "Download Excel file",
            st.session_state.export_bytes,
            file_name=f"FinanceOS_data_{date.today():%Y%m%d}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @st.dialog("Delete your account")
    def delete_dialog():
        st.write(
            "This permanently deletes your account, accounts, transactions, goals, investments, "
            "bills and family sharing. It can't be undone."
        )
        password = st.text_input("Enter your password to confirm", type="password")
        if st.button("Delete everything", type="primary", width="stretch"):
            try:
                account_admin_service.delete_account(user_id, password)
                st.session_state.clear()
                st.rerun()
            except AuthError as exc:
                st.error(str(exc))

    st.write("")
    if st.button("Delete my account"):
        delete_dialog()
