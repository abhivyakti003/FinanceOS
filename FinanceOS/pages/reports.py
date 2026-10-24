import streamlit as st

from app.services.report_service import generate_report
from app.ui.theme import page_header
from app.ui.common import current_user_id, period_picker

user_id = current_user_id()
page_header("Reports", "A PDF summary of your income, spending, budgets, goals and suggestions.")

start, end = period_picker("report")

if st.button("Create PDF report", type="primary"):
    with st.spinner("Building your report..."):
        st.session_state.report_pdf = generate_report(user_id, start, end)
        st.session_state.report_name = f"FinanceOS_report_{start:%Y%m%d}_{end:%Y%m%d}.pdf"

if st.session_state.get("report_pdf"):
    st.download_button(
        "Download report", st.session_state.report_pdf, file_name=st.session_state.report_name, mime="application/pdf"
    )
