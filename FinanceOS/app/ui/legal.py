"""Shows the Privacy Policy and Terms, filled in from .env settings."""

import os

import streamlit as st

from app import config

LEGAL_DIR = config.PROJECT_ROOT / "docs" / "legal"


def _fill(text: str) -> str:
    values = {
        "OPERATOR": os.getenv("LEGAL_OPERATOR_NAME", "The operator of this FinanceOS installation"),
        "SUPPORT_EMAIL": config.SUPPORT_EMAIL or "the support email shown in the app",
        "GRIEVANCE_OFFICER": os.getenv("LEGAL_GRIEVANCE_OFFICER", "to be appointed"),
        "DATA_LOCATION": os.getenv("LEGAL_DATA_LOCATION", "India"),
        "BACKUP_DAYS": str(config.BACKUP_KEEP),
        "JURISDICTION": os.getenv("LEGAL_JURISDICTION", "your city"),
        "LAST_UPDATED": os.getenv("LEGAL_LAST_UPDATED", "2026"),
    }
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


def document(name: str) -> str:
    path = LEGAL_DIR / name
    return _fill(path.read_text(encoding="utf-8")) if path.exists() else "Document not found."


@st.dialog("Privacy Policy", width="large")
def show_privacy():
    st.markdown(document("PRIVACY_POLICY.md"))


@st.dialog("Terms of Service", width="large")
def show_terms():
    st.markdown(document("TERMS_OF_SERVICE.md"))
