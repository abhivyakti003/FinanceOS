"""Investments: mutual funds, stocks, EPF, PPF, NPS, FDs and more.

Holdings can be added by hand or imported from a Consolidated Account
Statement (CAS):
- CAMS / KFintech CAS: all your mutual funds (from camsonline.com or kfintech.com)
- NSDL / CDSL CAS: demat stocks, ETFs, bonds, mutual funds, plus NPS

CAS PDFs are password protected, usually with your PAN in capitals.
Re-importing a newer CAS updates the same holdings instead of duplicating.
"""

import io
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.database.db import get_session
from app.database.models import Holding, utcnow

HOLDING_TYPES = [
    "Mutual Fund",
    "Stock",
    "ETF",
    "Bond",
    "Fixed Deposit",
    "Recurring Deposit",
    "EPF",
    "PPF",
    "NPS",
    "Gold (SGB / ETF / digital)",
    "Crypto",
    "Other",
]


class InvestmentError(ValueError):
    pass


def _money(value, allow_zero=True) -> Decimal:
    try:
        amount = Decimal(str(value if value is not None else 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise InvestmentError("Enter a valid amount.") from exc
    if amount < 0 or (amount == 0 and not allow_zero):
        raise InvestmentError("Amount can't be negative.")
    return amount


def add_holding(user_id: int, name: str, holding_type: str, invested, current_value, units=None) -> Holding:
    name = (name or "").strip()
    if not name:
        raise InvestmentError("Enter a name.")
    if holding_type not in HOLDING_TYPES:
        raise InvestmentError("Choose a valid type.")
    invested_d = _money(invested)
    current_d = _money(current_value)
    if invested_d == 0 and current_d == 0:
        raise InvestmentError("Enter the amount invested or the current value.")
    units_d = None
    if units not in (None, "", 0):
        try:
            units_d = Decimal(str(units)).quantize(Decimal("0.0001"))
        except InvalidOperation as exc:
            raise InvestmentError("Enter valid units.") from exc
    with get_session() as session:
        holding = Holding(
            user_id=user_id,
            name=name,
            holding_type=holding_type,
            invested=invested_d,
            current_value=current_d or invested_d,
            units=units_d,
        )
        session.add(holding)
        session.flush()
        return holding


def update_holding(user_id: int, holding_id: int, current_value=None, invested=None) -> Holding:
    with get_session() as session:
        holding = session.scalar(select(Holding).where(Holding.id == holding_id, Holding.user_id == user_id))
        if holding is None:
            raise InvestmentError("Holding not found.")
        if current_value is not None:
            holding.current_value = _money(current_value)
        if invested is not None:
            holding.invested = _money(invested)
        holding.updated_at = utcnow()
        return holding


def delete_holding(user_id: int, holding_id: int) -> bool:
    with get_session() as session:
        holding = session.scalar(select(Holding).where(Holding.id == holding_id, Holding.user_id == user_id))
        if holding is None:
            return False
        session.delete(holding)
        return True


def list_holdings(user_id: int) -> list[Holding]:
    with get_session() as session:
        return list(
            session.scalars(select(Holding).where(Holding.user_id == user_id).order_by(Holding.current_value.desc()))
        )


def portfolio_summary(user_id: int) -> dict:
    holdings = list_holdings(user_id)
    invested = sum((h.invested for h in holdings), Decimal("0"))
    current = sum((h.current_value for h in holdings), Decimal("0"))
    gain = current - invested
    gain_pct = float(gain / invested * 100) if invested > 0 else None
    return {
        "count": len(holdings),
        "invested": invested,
        "current": current,
        "gain": gain,
        "gain_percent": round(gain_pct, 2) if gain_pct is not None else None,
    }


def allocation(user_id: int) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for h in list_holdings(user_id):
        result[h.holding_type] = result.get(h.holding_type, Decimal("0")) + h.current_value
    return dict(sorted(result.items(), key=lambda kv: kv[1], reverse=True))


def total_value(user_id: int) -> Decimal:
    return sum((h.current_value for h in list_holdings(user_id)), Decimal("0"))


# ---------------------------------------------------------------------------
# CAS import
# ---------------------------------------------------------------------------


def _d(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except InvalidOperation:
        return Decimal("0")


def holdings_from_cas(data) -> list[dict]:
    """Turn a casparser result into a list of holding dicts."""
    rows: list[dict] = []

    # CAMS / KFintech
    for folio in getattr(data, "folios", None) or []:
        for scheme in folio.schemes or []:
            valuation = scheme.valuation
            value = _d(getattr(valuation, "value", 0))
            units = scheme.close or 0
            if value <= 0 and not units:
                continue
            rows.append(
                {
                    "identifier": f"{scheme.isin or scheme.amfi or scheme.scheme}|{folio.folio}"[:80],
                    "name": scheme.scheme,
                    "holding_type": "Mutual Fund",
                    "units": Decimal(str(units)).quantize(Decimal("0.0001")) if units else None,
                    "invested": _d(getattr(valuation, "cost", None) or value),
                    "current_value": value,
                }
            )

    # NSDL / CDSL
    for account in getattr(data, "accounts", None) or []:
        for eq in account.equities or []:
            value = _d(eq.value)
            if value <= 0:
                continue
            is_etf = "etf" in (eq.name or "").lower() or "bees" in (eq.name or "").lower()
            rows.append(
                {
                    "identifier": f"{eq.isin}|{account.client_id or account.dp_id}"[:80],
                    "name": eq.name or eq.isin,
                    "holding_type": "ETF" if is_etf else "Stock",
                    "units": Decimal(str(eq.num_shares or 0)).quantize(Decimal("0.0001")),
                    "invested": value,  # NSDL CAS doesn't include cost for stocks
                    "current_value": value,
                }
            )
        for mf in account.mutual_funds or []:
            value = _d(mf.value)
            if value <= 0:
                continue
            rows.append(
                {
                    "identifier": f"{mf.isin}|{mf.folio or account.client_id}"[:80],
                    "name": mf.name or mf.isin,
                    "holding_type": "Mutual Fund",
                    "units": Decimal(str(mf.balance or 0)).quantize(Decimal("0.0001")),
                    "invested": _d(mf.total_cost) if mf.total_cost else value,
                    "current_value": value,
                }
            )
        for bond in account.bonds or []:
            value = _d(bond.value)
            if value <= 0:
                continue
            rows.append(
                {
                    "identifier": f"{bond.isin}|{account.client_id or account.dp_id}"[:80],
                    "name": bond.name or bond.isin,
                    "holding_type": "Bond",
                    "units": Decimal(str(bond.num_bonds or 0)).quantize(Decimal("0.0001")),
                    "invested": value,
                    "current_value": value,
                }
            )

    nps = getattr(data, "nps", None) or []
    for nps_account in nps:
        value = _d(nps_account.value)
        if value > 0:
            rows.append(
                {
                    "identifier": f"NPS|{nps_account.pran}"[:80],
                    "name": f"NPS ({nps_account.pran})",
                    "holding_type": "NPS",
                    "units": None,
                    "invested": value,
                    "current_value": value,
                }
            )
    return rows


def save_imported_holdings(user_id: int, rows: list[dict]) -> dict:
    added = updated = 0
    with get_session() as session:
        for row in rows:
            existing = session.scalar(
                select(Holding).where(Holding.user_id == user_id, Holding.identifier == row["identifier"])
            )
            if existing:
                existing.current_value = row["current_value"]
                existing.units = row["units"]
                existing.name = row["name"][:200]
                if row["invested"] > 0:
                    existing.invested = row["invested"]
                existing.updated_at = utcnow()
                updated += 1
            else:
                session.add(Holding(user_id=user_id, source="cas", **{**row, "name": row["name"][:200]}))
                added += 1
    return {"added": added, "updated": updated}


def import_cas(user_id: int, data: bytes, password: str) -> dict:
    """Parse a CAS PDF and save its holdings. Returns {"added", "updated"}."""
    if not data:
        raise InvestmentError("The file is empty.")
    if not password:
        raise InvestmentError("Enter the CAS password (usually your PAN in capitals).")
    try:
        import casparser
    except ImportError as exc:
        raise InvestmentError("CAS import needs the 'casparser' package. Run: pip install casparser") from exc
    try:
        parsed = casparser.read_cas_pdf(io.BytesIO(data), password.strip())
    except Exception as exc:  # casparser raises several error types
        text = str(exc).lower()
        if "password" in text or "incorrect" in text:
            raise InvestmentError("Wrong password. CAS files usually use your PAN in capital letters.") from exc
        raise InvestmentError(
            "Couldn't read this file as a CAS. Download a 'Detailed' or 'Summary' CAS PDF "
            "from CAMS, KFintech, NSDL or CDSL."
        ) from exc
    rows = holdings_from_cas(parsed)
    if not rows:
        raise InvestmentError("No holdings with a value were found in this statement.")
    return save_imported_holdings(user_id, rows)
