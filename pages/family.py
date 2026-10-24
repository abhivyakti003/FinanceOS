from datetime import date

import plotly.express as px
import streamlit as st

from app.services import account_service, family_service
from app.services.analytics_service import category_breakdown, month_start, monthly_summary, period_summary
from app.services.family_service import FamilyError
from app.services.goal_service import goal_progress
from app.services.investment_service import portfolio_summary
from app.services.wealth_service import net_worth
from app.ui.common import current_user_id, fmt_inr
from app.ui.theme import chart_layout, page_header, rows

user_id = current_user_id()
page_header("Family", "Share your finances with family, read-only. They can see, never change.")

pending = family_service.incoming(user_id, "pending")
for invite in pending:
    with st.container(border=True):
        c1, c2, c3 = st.columns([4, 1, 1], vertical_alignment="center")
        c1.markdown(f"**{invite['owner_name']}** ({invite['owner_email']}) wants to share their finances with you.")
        if c2.button("Accept", key=f"acc_{invite['id']}", type="primary", width="stretch"):
            family_service.accept(user_id, invite["id"])
            st.rerun()
        if c3.button("Decline", key=f"dec_{invite['id']}", width="stretch"):
            family_service.decline_or_leave(user_id, invite["id"])
            st.rerun()

tab_view, tab_share = st.tabs(["Shared with me", "People I share with"])

with tab_view:
    shared = family_service.shared_with_me(user_id)
    if not shared:
        st.caption("Nobody has shared their finances with you yet. When someone invites you, it appears above.")
    else:
        people = {s["owner_id"]: s for s in shared}
        owner_id = (
            st.segmented_control(
                "Person",
                list(people),
                format_func=lambda i: people[i]["owner_name"],
                default=list(people)[0],
                label_visibility="collapsed",
                key="family_person",
            )
            or list(people)[0]
        )

        # Access is re-checked on every view, so revoking takes effect immediately.
        if not family_service.can_view(user_id, owner_id):
            st.error("You no longer have access.")
            st.stop()

        person = people[owner_id]
        today = date.today()
        s = period_summary(owner_id, month_start(today), today)
        worth = net_worth(owner_id)
        portfolio = portfolio_summary(owner_id)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Bank and cash", fmt_inr(account_service.total_balance(owner_id)), border=True)
        c2.metric("Net worth", fmt_inr(worth["net_worth"]), border=True)
        c3.metric("Spent this month", fmt_inr(s["spending"]), border=True)
        c4.metric("Investments", fmt_inr(portfolio["current"]), border=True)

        left, right = st.columns(2, gap="large")
        with left:
            st.subheader("This month by category")
            cats = category_breakdown(owner_id, month_start(today), today)
            if cats.empty:
                st.caption("No spending yet this month.")
            else:
                fig = px.bar(cats, x="amount", y="category", orientation="h")
                fig.update_traces(hovertemplate="%{y}<br>₹%{x:,.0f}<extra></extra>")
                fig.update_layout(yaxis=dict(autorange="reversed", title=None), xaxis_title=None)
                st.plotly_chart(chart_layout(fig, 320, "x"), width="stretch")
        with right:
            st.subheader("Accounts")
            accounts = account_service.accounts_with_balances(owner_id)
            if accounts:
                rows([(a["name"], fmt_inr(a["balance"])) for a in accounts])
            else:
                st.caption("No accounts.")
            goals = goal_progress(owner_id)
            if goals:
                st.subheader("Goals")
                for g in goals:
                    st.write(f"{g['name']}: {g['percent']:.0f}%")
                    st.progress(g["percent"] / 100)

        months = monthly_summary(owner_id, 6)
        fig = px.bar(months, x="label", y=["income", "spending"], barmode="group")
        fig.update_layout(xaxis_title=None, yaxis_title=None, legend_title=None)
        st.subheader("Last 6 months")
        st.plotly_chart(chart_layout(fig, 280), width="stretch")

        if st.button(f"Stop viewing {person['owner_name']}'s finances"):
            family_service.decline_or_leave(user_id, person["id"])
            st.rerun()

with tab_share:
    with st.form("invite", clear_on_submit=True):
        c1, c2 = st.columns([3, 2])
        email = c1.text_input("Their email", placeholder="name@gmail.com")
        relation = c2.selectbox("Relation", family_service.RELATIONS)
        st.caption(
            "They'll see your balances, spending, goals and investments. They can't change anything. "
            "If they don't have an account yet, they can sign up with this email."
        )
        if st.form_submit_button("Send invite", type="primary"):
            try:
                family_service.invite(user_id, email, relation)
                st.toast("Invite sent")
                st.rerun()
            except FamilyError as exc:
                st.error(str(exc))

    for share in family_service.outgoing(user_id):
        with st.container(border=True):
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            status = "can view your finances" if share.status == "accepted" else "invite pending"
            c1.markdown(f"**{share.member_email}** · {share.relation or 'Family'} · {status}")
            if c2.button("Stop sharing", key=f"rev_{share.id}", width="stretch"):
                family_service.revoke(user_id, share.id)
                st.rerun()
