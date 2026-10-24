from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.services import credit_score_service as cs
from app.ui.common import current_user_id
from app.ui.theme import GREEN, chart_layout, page_header

user_id = current_user_id()
page_header("Credit score", "Track your score over time. Check it free on the bureau's website, then log it here.")

history = cs.history(user_id)
latest = history[-1] if history else None

left, right = st.columns([2, 3], gap="large")
with left:
    if latest:
        fig = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=latest.score,
                number=dict(font=dict(size=44)),
                gauge=dict(
                    axis=dict(range=[300, 900], tickvals=[300, 550, 650, 700, 750, 900]),
                    bar=dict(color=GREEN, thickness=0.28),
                    steps=[
                        dict(range=[300, 650], color="rgba(208,85,63,0.18)"),
                        dict(range=[650, 750], color="rgba(224,163,58,0.18)"),
                        dict(range=[750, 900], color="rgba(31,157,115,0.18)"),
                    ],
                ),
            )
        )
        st.plotly_chart(chart_layout(fig, 250, None), width="stretch")
        change = f"{latest.score - history[-2].score:+d} since last check" if len(history) > 1 else None
        st.metric(f"{cs.band(latest.score)} · {latest.bureau}", latest.score, change, border=True)
        st.caption(f"Recorded {latest.recorded_on:%d %b %Y}")
    else:
        st.caption("No scores yet. Add your latest score below.")

    with st.form("score", clear_on_submit=True):
        c1, c2 = st.columns(2)
        score = c1.number_input("Score", min_value=300, max_value=900, value=750)
        bureau = c2.selectbox("Bureau", cs.BUREAUS)
        when = st.date_input("Checked on", date.today(), max_value=date.today())
        if st.form_submit_button("Save score", type="primary"):
            try:
                cs.add_score(user_id, score, bureau, when)
                st.rerun()
            except cs.CreditScoreError as exc:
                st.error(str(exc))

with right:
    if len(history) > 1:
        df = pd.DataFrame([{"Date": h.recorded_on, "Score": h.score, "Bureau": h.bureau} for h in history])
        fig = go.Figure()
        for bureau, part in df.groupby("Bureau"):
            fig.add_scatter(x=part["Date"], y=part["Score"], mode="lines+markers", name=bureau)
        fig.update_yaxes(range=[300, 900])
        st.subheader("Trend")
        st.plotly_chart(chart_layout(fig, 280, None), width="stretch")
    st.subheader("How to improve it")
    for tip in cs.tips(latest.score if latest else None):
        st.markdown(f"- {tip}")
    if history:
        with st.expander("All entries"):
            for h in reversed(history):
                c1, c2 = st.columns([4, 1])
                c1.write(f"{h.recorded_on:%d %b %Y} · {h.bureau} · **{h.score}**")
                if c2.button("Remove", key=f"cs_{h.id}"):
                    cs.delete_score(user_id, h.id)
                    st.rerun()
