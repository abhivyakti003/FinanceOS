from datetime import date, timedelta

import streamlit as st

from app.services import account_service, bill_service
from app.services.bill_service import BillError
from app.services.categorization_service import EXPENSE_CATEGORIES
from app.services.recurring_service import detect_recurring
from app.ui.common import current_user_id, fmt_inr
from app.ui.theme import page_header

user_id = current_user_id()
page_header("Bills", "Never miss a due date. We'll email you before each one.")

bills = bill_service.list_bills(user_id)
today = date.today()

c1, c2, c3 = st.columns(3)
overdue = [b for b in bills if b.next_due_date < today]
this_week = [b for b in bills if today <= b.next_due_date <= today + timedelta(days=7)]
c1.metric("Overdue", len(overdue), border=True)
c2.metric(
    "Due in 7 days",
    fmt_inr(sum(float(b.amount) for b in this_week)),
    f"{len(this_week)} bills",
    delta_color="off",
    border=True,
)
c3.metric("Per month, on average", fmt_inr(bill_service.monthly_bill_total(user_id)), border=True)

accounts = account_service.list_accounts(user_id)
account_names = {a.id: a.name for a in accounts}

with st.expander("Add a bill", expanded=not bills):
    with st.form("add_bill", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        name = c1.text_input("Bill", placeholder="Electricity, HDFC credit card, LIC premium")
        amount = c2.number_input("Amount (₹)", min_value=0.0, step=100.0)
        due = c3.date_input("Next due date", today + timedelta(days=7))
        c1, c2, c3, c4 = st.columns(4)
        frequency = c1.selectbox("Repeats", bill_service.FREQUENCIES)
        category = c2.selectbox(
            "Category", EXPENSE_CATEGORIES + ["Transfer"], index=EXPENSE_CATEGORIES.index("Bills & Utilities")
        )
        remind = c3.number_input("Remind me (days before)", min_value=0, max_value=30, value=3)
        account = c4.selectbox(
            "Paid from",
            [None] + list(account_names),
            format_func=lambda i: "Not set" if i is None else account_names[i],
        )
        if st.form_submit_button("Add bill", type="primary"):
            try:
                bill_service.add_bill(user_id, name, amount, due, frequency, category, remind, account)
                st.rerun()
            except BillError as exc:
                st.error(str(exc))

if not bills:
    suggestions = [r for r in detect_recurring(user_id) if r["active"]]
    if suggestions:
        st.subheader("Found in your transactions")
        st.caption("These look like regular payments. Add them as bills to get reminders.")
        for i, item in enumerate(suggestions[:6]):
            c1, c2 = st.columns([4, 1])
            c1.write(f"**{item['merchant']}**: {fmt_inr(item['average_amount'])}, {item['frequency'].lower()}")
            if c2.button("Add as bill", key=f"sugg_{i}"):
                bill_service.create_from_recurring(user_id, item)
                st.rerun()
    st.stop()


@st.dialog("Mark as paid")
def pay_dialog(bill):
    st.write(f"**{bill.name}**: {fmt_inr(bill.amount, 2)}")
    paid_on = st.date_input("Paid on", today, max_value=today)
    record = st.checkbox(
        "Also add it to my transactions",
        value=True,
        help="Leave this off if the payment will come in through a statement import or bank link.",
    )
    account = None
    if record and account_names:
        ids = list(account_names)
        default = ids.index(bill.account_id) if bill.account_id in ids else 0
        account = st.selectbox("From account", ids, index=default, format_func=account_names.get)
    if st.button("Confirm", type="primary", width="stretch"):
        bill_service.mark_paid(user_id, bill.id, paid_on, record, account)
        st.rerun()


groups = [
    ("Overdue", [b for b in bills if b.next_due_date < today]),
    ("Next 7 days", [b for b in bills if today <= b.next_due_date <= today + timedelta(days=7)]),
    ("Later", [b for b in bills if b.next_due_date > today + timedelta(days=7)]),
]
for title, items in groups:
    if not items:
        continue
    st.subheader(title)
    for bill in items:
        status = bill_service.bill_status(bill, today)
        with st.container(border=True):
            c1, c2, c3, c4, c5 = st.columns([3, 1.4, 1, 1, 0.8], vertical_alignment="center")
            colour = {"overdue": "red", "today": "orange", "soon": "orange"}.get(status["level"], "gray")
            c1.markdown(f"**{bill.name}**  \n:{colour}[{status['label']}] · {bill.frequency.lower()} · {bill.category}")
            c2.markdown(f"### {fmt_inr(bill.amount)}")
            if c3.button("Paid", key=f"pay_{bill.id}", type="primary", width="stretch"):
                pay_dialog(bill)
            if c4.button("Snooze", key=f"snooze_{bill.id}", width="stretch", help="Move the due date 3 days later"):
                bill_service.snooze(user_id, bill.id, 3)
                st.rerun()
            if c5.button("Remove", key=f"del_bill_{bill.id}", help="Delete this bill"):
                bill_service.delete_bill(user_id, bill.id)
                st.rerun()
