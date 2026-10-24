"""Credit score history.

Live credit scores need a partnership with a credit bureau (CIBIL, Experian,
Equifax, CRIF High Mark). Until then, users record the score they see on the
bureau's site or in their bank app, and FinanceOS tracks the trend.
Free checks: cibil.com, experian.in, equifax.co.in, crifhighmark.com
"""

from datetime import date

from sqlalchemy import select

from app.database.db import get_session
from app.database.models import CreditScore

BUREAUS = ["CIBIL", "Experian", "Equifax", "CRIF High Mark"]


class CreditScoreError(ValueError):
    pass


def add_score(user_id: int, score: int, bureau: str, recorded_on: date | None = None) -> CreditScore:
    try:
        score = int(score)
    except (TypeError, ValueError) as exc:
        raise CreditScoreError("Enter your score as a number.") from exc
    if not 300 <= score <= 900:
        raise CreditScoreError("Indian credit scores are between 300 and 900.")
    if bureau not in BUREAUS:
        raise CreditScoreError("Choose the bureau.")
    recorded_on = recorded_on or date.today()
    if recorded_on > date.today():
        raise CreditScoreError("Date can't be in the future.")
    with get_session() as session:
        entry = CreditScore(user_id=user_id, score=score, bureau=bureau, recorded_on=recorded_on)
        session.add(entry)
        session.flush()
        return entry


def history(user_id: int) -> list[CreditScore]:
    with get_session() as session:
        return list(
            session.scalars(
                select(CreditScore)
                .where(CreditScore.user_id == user_id)
                .order_by(CreditScore.recorded_on, CreditScore.id)
            )
        )


def delete_score(user_id: int, score_id: int) -> bool:
    with get_session() as session:
        entry = session.scalar(select(CreditScore).where(CreditScore.id == score_id, CreditScore.user_id == user_id))
        if entry is None:
            return False
        session.delete(entry)
        return True


def band(score: int) -> str:
    if score >= 750:
        return "Excellent"
    if score >= 700:
        return "Good"
    if score >= 650:
        return "Fair"
    if score >= 550:
        return "Poor"
    return "Very poor"


def tips(score: int | None) -> list[str]:
    general = [
        "Pay every EMI and credit card bill in full and on time. Payment history matters most.",
        "Keep credit card usage under 30% of your limit.",
        "Avoid applying for several loans or cards in a short time.",
        "Keep old cards open; a longer credit history helps.",
        "Check your report once a year and dispute any errors with the bureau.",
    ]
    if score is None:
        return general
    if score >= 750:
        return ["Your score is excellent. Keep paying on time and keep card usage low."]
    return general
