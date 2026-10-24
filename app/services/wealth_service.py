"""Other assets and loans, plus net worth.

Net worth = account balances + investments + other assets - loans.
Bank balances come from Accounts and investments from the Investments
page, so they aren't entered here (that would count them twice).
"""

from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.database.db import get_session
from app.database.models import Asset, Liability
from app.services.account_service import account_balances

ASSET_CATEGORIES = ["Property", "Vehicle", "Gold & jewellery", "Money lent to someone", "Business", "Other"]
LIABILITY_CATEGORIES = [
    "Home Loan",
    "Personal Loan",
    "Car Loan",
    "Education Loan",
    "Gold Loan",
    "Borrowed from someone",
    "Other",
]


class WealthError(ValueError):
    pass


def _positive(amount) -> Decimal:
    try:
        value = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise WealthError("Enter a valid amount.") from exc
    if value <= 0:
        raise WealthError("Amount must be more than zero.")
    return value


def _name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise WealthError("Enter a name.")
    return name


def add_asset(user_id: int, name: str, category: str, amount) -> Asset:
    if category not in ASSET_CATEGORIES:
        raise WealthError("Choose a valid category.")
    with get_session() as session:
        asset = Asset(user_id=user_id, name=_name(name), category=category, amount=_positive(amount))
        session.add(asset)
        session.flush()
        return asset


def add_liability(user_id: int, name: str, category: str, amount) -> Liability:
    if category not in LIABILITY_CATEGORIES:
        raise WealthError("Choose a valid category.")
    with get_session() as session:
        liability = Liability(user_id=user_id, name=_name(name), category=category, amount=_positive(amount))
        session.add(liability)
        session.flush()
        return liability


def update_asset_value(user_id: int, asset_id: int, amount) -> None:
    with get_session() as session:
        asset = session.scalar(select(Asset).where(Asset.id == asset_id, Asset.user_id == user_id))
        if asset is None:
            raise WealthError("Asset not found.")
        asset.amount = _positive(amount)


def update_liability_value(user_id: int, liability_id: int, amount) -> None:
    with get_session() as session:
        item = session.scalar(select(Liability).where(Liability.id == liability_id, Liability.user_id == user_id))
        if item is None:
            raise WealthError("Liability not found.")
        item.amount = _positive(amount)


def list_assets(user_id: int) -> list[Asset]:
    with get_session() as session:
        return list(session.scalars(select(Asset).where(Asset.user_id == user_id).order_by(Asset.id)))


def list_liabilities(user_id: int) -> list[Liability]:
    with get_session() as session:
        return list(session.scalars(select(Liability).where(Liability.user_id == user_id).order_by(Liability.id)))


def delete_asset(user_id: int, asset_id: int) -> bool:
    with get_session() as session:
        item = session.scalar(select(Asset).where(Asset.id == asset_id, Asset.user_id == user_id))
        if item is None:
            return False
        session.delete(item)
        return True


def delete_liability(user_id: int, liability_id: int) -> bool:
    with get_session() as session:
        item = session.scalar(select(Liability).where(Liability.id == liability_id, Liability.user_id == user_id))
        if item is None:
            return False
        session.delete(item)
        return True


def net_worth(user_id: int) -> dict:
    """Accounts (card dues count as negative) + investments + assets - liabilities."""
    from app.services.investment_service import total_value  # avoid circular import

    accounts_total = sum(account_balances(user_id).values(), Decimal("0"))
    investments_total = total_value(user_id)
    assets_total = sum((a.amount for a in list_assets(user_id)), Decimal("0"))
    liabilities_total = sum((item.amount for item in list_liabilities(user_id)), Decimal("0"))
    return {
        "accounts": accounts_total,
        "investments": investments_total,
        "assets": assets_total,
        "liabilities": liabilities_total,
        "net_worth": accounts_total + investments_total + assets_total - liabilities_total,
    }


def asset_breakdown(user_id: int) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for asset in list_assets(user_id):
        result[asset.category] = result.get(asset.category, Decimal("0")) + asset.amount
    return result
