"""Visual style shared by every page.

Colours, font and corner radius come from .streamlit/config.toml (light and
dark). This file adds the small finishing touches Streamlit can't configure,
plus helpers so every page looks the same.
"""

from html import escape

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

GREEN = "#1F9D73"
RED = "#D0553F"
AMBER = "#E0A33A"
BLUE = "#5B8DEF"
MUTED = "rgba(128, 132, 140, 0.95)"

_CSS = """
<style>
.block-container { max-width: 1200px; padding-top: 2rem; padding-bottom: 4rem; }
h1 { letter-spacing: -0.025em; }
h2, h3 { letter-spacing: -0.015em; }
[data-testid="stMetricValue"], .fos-num { font-variant-numeric: tabular-nums; letter-spacing: -0.01em; }
[data-testid="stMetricLabel"] p { opacity: 0.7; }
[data-testid="stSidebarNav"] a span { font-weight: 500; }
.fos-sub { opacity: 0.62; margin: -0.6rem 0 1.4rem 0; font-size: 0.98rem; }
.fos-hero { font-size: clamp(1.45rem, 2.6vw, 2.15rem); line-height: 1.3; font-weight: 600;
            letter-spacing: -0.02em; margin: 0.2rem 0 1.6rem 0; max-width: 30em; }
.fos-hero .pos { color: #1F9D73; }
.fos-hero .neg { color: #D0553F; }
.fos-hero .soft { opacity: 0.55; font-weight: 500; }
.fos-alerts { list-style: none; padding: 0; margin: 0; }
.fos-alerts li { display: flex; gap: 0.7rem; align-items: baseline; padding: 0.55rem 0;
                 border-bottom: 1px solid rgba(128, 132, 140, 0.18); }
.fos-alerts li:last-child { border-bottom: none; }
.fos-dot { width: 0.55rem; height: 0.55rem; border-radius: 50%; flex: none; transform: translateY(-0.05rem); }
.fos-row { display: flex; justify-content: space-between; gap: 1rem; padding: 0.5rem 0;
           border-bottom: 1px solid rgba(128, 132, 140, 0.18); }
.fos-row:last-child { border-bottom: none; }
.fos-row .fos-num { font-weight: 600; }
.fos-muted { opacity: 0.62; }
.fos-brand { font-weight: 700; font-size: 1.15rem; letter-spacing: -0.02em; }
.fos-brand span { color: #1F9D73; }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
"""


def _register_plotly_template() -> None:
    template = go.layout.Template()
    template.layout = go.Layout(
        font=dict(family="Manrope, sans-serif", size=13),
        margin=dict(l=8, r=8, t=24, b=8),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(showgrid=False, zeroline=False, linecolor="rgba(128,132,140,0.3)"),
        yaxis=dict(gridcolor="rgba(128,132,140,0.15)", zeroline=False),
        legend=dict(orientation="h", y=1.08, x=0, title=None),
        hoverlabel=dict(font_family="Manrope, sans-serif"),
        colorway=["#1F9D73", "#5B8DEF", "#E0A33A", "#D0553F", "#8B7BD8", "#3BA7A0", "#8A8F98", "#D46FA0"],
    )
    pio.templates["financeos"] = template
    pio.templates.default = "plotly+financeos"


def apply_theme() -> None:
    _register_plotly_template()
    st.markdown(_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str | None = None) -> None:
    st.title(title)
    if subtitle:
        st.markdown(f'<p class="fos-sub">{escape(subtitle)}</p>', unsafe_allow_html=True)


def hero(html: str) -> None:
    """A large sentence at the top of a page. Pass already-escaped HTML."""
    st.markdown(f'<p class="fos-hero">{html}</p>', unsafe_allow_html=True)


_LEVEL_COLOURS = {"error": RED, "warning": AMBER, "info": BLUE, "ok": GREEN}


def alert_list(alerts: list[dict], empty: str = "Nothing needs your attention.") -> None:
    if not alerts:
        st.markdown(f'<p class="fos-muted">{escape(empty)}</p>', unsafe_allow_html=True)
        return
    items = "".join(
        f'<li><span class="fos-dot" style="background:{_LEVEL_COLOURS.get(a["level"], BLUE)}"></span>'
        f"<span>{escape(a['text'])}</span></li>"
        for a in alerts
    )
    st.markdown(f'<ul class="fos-alerts">{items}</ul>', unsafe_allow_html=True)


def rows(pairs: list[tuple[str, str]]) -> None:
    """Simple label / value rows."""
    html = "".join(
        f'<div class="fos-row"><span>{escape(label)}</span><span class="fos-num">{escape(value)}</span></div>'
        for label, value in pairs
    )
    st.markdown(html, unsafe_allow_html=True)


def chart_layout(fig, height: int = 320, money_axis: str | None = "y"):
    fig.update_layout(height=height)
    if money_axis == "y":
        fig.update_yaxes(tickprefix="₹", separatethousands=True)
    elif money_axis == "x":
        fig.update_xaxes(tickprefix="₹", separatethousands=True)
    return fig
