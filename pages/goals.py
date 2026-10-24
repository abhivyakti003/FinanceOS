from datetime import date, timedelta

import streamlit as st

from app.services import goal_service
from app.services.goal_service import GoalError
from app.ui.theme import page_header
from app.ui.common import current_user_id, fmt_inr

user_id = current_user_id()
page_header("Goals", "Save toward the things that matter.")

with st.expander("Create a goal", expanded=not goal_service.list_goals(user_id)):
    with st.form("goal", clear_on_submit=True):
        name = st.text_input("Goal", placeholder="Emergency fund, Goa trip, new laptop")
        c1, c2, c3 = st.columns(3)
        target = c1.number_input("Target amount (₹)", min_value=0.0, step=1000.0)
        saved = c2.number_input("Already saved (₹)", min_value=0.0, step=1000.0)
        has_date = c3.checkbox("Set a target date")
        target_date = c3.date_input(
            "Target date", date.today() + timedelta(days=365), min_value=date.today() + timedelta(days=1)
        )
        if st.form_submit_button("Create goal", type="primary"):
            try:
                goal_service.add_goal(user_id, name, target, saved, target_date if has_date else None)
                st.rerun()
            except GoalError as exc:
                st.error(str(exc))

goals = goal_service.goal_progress(user_id)
if not goals:
    st.info("No goals yet.")
    st.stop()

for g in goals:
    with st.container(border=True):
        c1, c2 = st.columns([3, 2])
        with c1:
            st.subheader(g["name"])
            st.progress(g["percent"] / 100)
            st.write(f"{fmt_inr(g['current'])} of {fmt_inr(g['target'])} ({g['percent']:.0f}%)")
            if g["remaining"] == 0:
                st.success("Goal reached 🎉")
            else:
                if g["eta_months"]:
                    st.caption(f"At your current saving rate, you'll get there in about {g['eta_months']} months.")
                else:
                    st.caption("You're not saving anything each month yet, so there's no estimate.")
                if g["target_date"]:
                    text = f"Target {g['target_date']:%d %b %Y}: save {fmt_inr(g['required_monthly'])} a month."
                    (st.caption if g["on_track"] else st.warning)(text + ("" if g["on_track"] else " You're behind."))
        with c2:
            with st.form(f"contrib_{g['id']}"):
                amount = st.number_input(
                    "Add money (₹)", step=500.0, key=f"amt_{g['id']}", help="Use a negative number to take money out."
                )
                if st.form_submit_button("Update"):
                    goal_service.add_contribution(user_id, g["id"], amount)
                    st.rerun()
            if st.button("Delete goal", key=f"del_goal_{g['id']}"):
                goal_service.delete_goal(user_id, g["id"])
                st.rerun()
