"""Small helpers shared by all Streamlit pages."""

from datetime import date, timedelta
from decimal import Decimal

import streamlit as st

from app.services.analytics_service import add_months, month_end, month_start


def fmt_inr(value, decimals: int = 0) -> str:
    """Indian digit grouping: 1234567.5 -> ₹12,34,568"""
    if value is None:
        return "-"
    number = float(value) if isinstance(value, Decimal) else float(value)
    sign = "-" if number < 0 else ""
    number = abs(number)
    whole, _, frac = f"{number:.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}₹{whole}" + (f".{frac}" if decimals else "")


def current_user_id() -> int:
    """Stop the page if nobody is logged in (pages can't be opened directly)."""
    user_id = st.session_state.get("user_id")
    if not user_id:
        st.warning("Please log in.")
        st.stop()
    return user_id


def month_picker(key: str, label: str = "Month", months_back: int = 24) -> tuple[date, date]:
    today = date.today()
    options = [add_months(month_start(today), -i) for i in range(months_back)]
    chosen = st.selectbox(label, options, format_func=lambda d: d.strftime("%B %Y"), key=key)
    return chosen, min(month_end(chosen), today)


def period_picker(key: str) -> tuple[date, date]:
    today = date.today()
    presets = {
        "This month": (month_start(today), today),
        "Last month": (add_months(month_start(today), -1), month_start(today) - timedelta(days=1)),
        "Last 3 months": (add_months(month_start(today), -3), month_start(today) - timedelta(days=1)),
        "Last 6 months": (add_months(month_start(today), -6), month_start(today) - timedelta(days=1)),
        "This year": (date(today.year, 1, 1), today),
        "Custom": None,
    }
    choice = (
        st.segmented_control(
            "Period", list(presets), default="This month", key=f"{key}_preset", label_visibility="collapsed"
        )
        or "This month"
    )
    if choice == "Custom":
        c1, c2 = st.columns(2)
        start = c1.date_input("From", today - timedelta(days=30), key=f"{key}_from", max_value=today)
        end = c2.date_input("To", today, key=f"{key}_to", max_value=today)
        if start > end:
            st.error("'From' must be before 'To'.")
            st.stop()
        return start, end
    return presets[choice]


def empty_state(message: str) -> None:
    st.markdown(f'<p class="fos-muted">{message}</p>', unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1.container(border=True):
        st.markdown("**Link your bank**")
        st.caption("Pull accounts and transactions automatically (sample data in demo mode).")
        st.page_link("pages/accounts.py", label="Go to Accounts", icon="🏦")
    with c2.container(border=True):
        st.markdown("**Import a statement**")
        st.caption("Upload the CSV, Excel or PDF you download from net banking.")
        st.page_link("pages/import_statement.py", label="Import statement", icon="📥")
    with c3.container(border=True):
        st.markdown("**Add by hand**")
        st.caption("Record cash spends or anything not in your bank.")
        st.page_link("pages/transactions.py", label="Add a transaction", icon="✍️")
