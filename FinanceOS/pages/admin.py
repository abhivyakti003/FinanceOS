import pandas as pd
import streamlit as st

from app.services import admin_service, audit_service, auth_service, backup_service
from app.services.admin_service import AdminError
from app.ui.common import current_user_id
from app.ui.theme import page_header, rows

user_id = current_user_id()
if not admin_service.is_admin(auth_service.get_user(user_id)):
    st.error("Only admins can open this page.")
    st.stop()

page_header("Admin", "Who uses FinanceOS. You see counts only, never anyone's money.")

stats = admin_service.platform_stats(user_id)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Users", stats["users"], border=True)
c2.metric("Active in 30 days", stats["active_30_days"], border=True)
c3.metric("New this week", stats["new_7_days"], border=True)
c4.metric("Transactions stored", f"{stats['transactions']:,}", border=True)

users = admin_service.list_users(user_id)
table = pd.DataFrame(
    [
        {
            "id": u["id"],
            "Name": u["name"],
            "Email": u["email"],
            "Joined": u["joined"],
            "Last login": u["last_login"],
            "Accounts": u["accounts"],
            "Transactions": u["transactions"],
            "Active": u["active"],
            "Admin": u["admin"],
        }
        for u in users
    ]
).set_index("id")

st.subheader("Users")
edited = st.data_editor(
    table,
    width="stretch",
    hide_index=True,
    key="admin_users",
    disabled=["Name", "Email", "Joined", "Last login", "Accounts", "Transactions", "Admin"],
    column_config={
        "Joined": st.column_config.DatetimeColumn(format="DD MMM YYYY"),
        "Last login": st.column_config.DatetimeColumn(format="DD MMM YYYY, HH:mm"),
        "Active": st.column_config.CheckboxColumn(help="Untick to stop this person logging in."),
    },
)
changed = edited[edited["Active"] != table["Active"]]
if len(changed) and st.button(f"Save {len(changed)} change{'s' if len(changed) != 1 else ''}", type="primary"):
    try:
        for uid, row in changed.iterrows():
            admin_service.set_active(user_id, int(uid), bool(row["Active"]))
        st.session_state.pop("admin_users", None)
        st.rerun()
    except AdminError as exc:
        st.error(str(exc))

with st.expander("Delete a user"):
    others = {u["id"]: f"{u['name']} ({u['email']})" for u in users if u["id"] != user_id}
    if others:
        target = st.selectbox("User", list(others), format_func=others.get)
        confirm = st.text_input("Type DELETE to confirm")
        if st.button("Delete user and all their data", disabled=confirm != "DELETE"):
            admin_service.delete_user(user_id, target)
            st.rerun()
    else:
        st.caption("No other users.")

st.subheader("Database")
backups = backup_service.list_backups()
rows(
    [
        ("Stored in", stats["database"]),
        ("Accounts", f"{stats['accounts']:,}"),
        ("Latest backup", backups[0].name if backups else "None yet"),
    ]
)
st.write("")
if st.button("Back up now"):
    try:
        path = backup_service.create_backup()
        st.success(f"Saved {path.name} in the backups folder.")
    except backup_service.BackupError as exc:
        st.error(str(exc))

st.subheader("Security log")
event_filter = st.selectbox(
    "Show",
    [
        "All events",
        "login_failed",
        "login_locked",
        "login_blocked",
        "password_reset",
        "account_deleted",
        "admin_user_disabled",
        "data_export",
    ],
)
entries = audit_service.recent(200, None if event_filter == "All events" else event_filter)
if entries:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Time (UTC)": e.created_at,
                    "Event": e.event,
                    "User ID": e.user_id,
                    "Email": e.email or "",
                    "Detail": e.detail or "",
                }
                for e in entries
            ]
        ),
        width="stretch",
        hide_index=True,
        height=320,
        column_config={"Time (UTC)": st.column_config.DatetimeColumn(format="DD MMM YYYY, HH:mm:ss")},
    )
else:
    st.caption("No events yet.")
