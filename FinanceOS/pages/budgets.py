import streamlit as st

from app.services import budget_service
from app.services.analytics_service import budget_utilization
from app.services.budget_service import BudgetError
from app.services.categorization_service import EXPENSE_CATEGORIES
from app.ui.theme import page_header
from app.ui.common import current_user_id, fmt_inr, month_picker

user_id = current_user_id()
page_header("Budgets", "Monthly limits per category. Setting one again updates it.")

with st.form("budget", clear_on_submit=True):
    c1, c2, c3 = st.columns([2, 2, 1])
    category = c1.selectbox("Category", [c for c in EXPENSE_CATEGORIES if c != "Investments"])
    limit = c2.number_input("Monthly limit (₹)", min_value=0.0, step=500.0)
    c3.write("")
    if c3.form_submit_button("Save budget", type="primary"):
        try:
            budget_service.set_budget(user_id, category, limit)
            st.rerun()
        except BudgetError as exc:
            st.error(str(exc))

start, _ = month_picker("budget_month")
items = budget_utilization(user_id, start)
if not items:
    st.info("No budgets yet. Add one above.")
    st.stop()

total_limit = sum(i["limit"] for i in items)
total_spent = sum(i["spent"] for i in items)
st.metric("Spent against budgets", f"{fmt_inr(total_spent)} of {fmt_inr(total_limit)}", border=True)

for item in items:
    c1, c2 = st.columns([5, 1])
    with c1:
        pct = item["percent"]
        status = "🔴 Over budget" if pct > 100 else "🟠 Close to limit" if pct > 80 else "🟢 On track"
        st.write(f"**{item['category']}**: {fmt_inr(item['spent'])} of {fmt_inr(item['limit'])} ({pct:.0f}%) {status}")
        st.progress(min(pct / 100, 1.0))
    if c2.button("Remove", key=f"del_budget_{item['id']}"):
        budget_service.delete_budget(user_id, item["id"])
        st.rerun()
