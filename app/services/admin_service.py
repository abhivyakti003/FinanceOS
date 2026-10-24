"""Admin tools: see who uses the app and manage accounts.

Admins are listed in ADMIN_EMAILS in .env. Admins see counts only, never
anyone's transactions, balances or other financial details.
"""

from datetime import timedelta

from sqlalchemy import func, select

from app import config
from app.database.db import describe, get_session
from app.database.models import Account, Transaction, User, utcnow
from app.services import audit_service
from app.services.account_admin_service import delete_user_data


class AdminError(ValueError):
    pass


def is_admin(user: User | None) -> bool:
    return bool(user and user.email.lower() in config.ADMIN_EMAILS)


def _require_admin(session, admin_id: int) -> User:
    admin = session.get(User, admin_id)
    if not is_admin(admin):
        raise AdminError("Only admins can do this.")
    return admin


def platform_stats(admin_id: int) -> dict:
    with get_session() as session:
        _require_admin(session, admin_id)
        now = utcnow()
        return {
            "users": session.scalar(select(func.count(User.id))),
            "active_30_days": session.scalar(
                select(func.count(User.id)).where(User.last_login_at >= now - timedelta(days=30))
            ),
            "new_7_days": session.scalar(select(func.count(User.id)).where(User.created_at >= now - timedelta(days=7))),
            "disabled": session.scalar(select(func.count(User.id)).where(User.is_active.is_(False))),
            "accounts": session.scalar(select(func.count(Account.id))),
            "transactions": session.scalar(select(func.count(Transaction.id))),
            "database": describe(),
        }


def list_users(admin_id: int) -> list[dict]:
    with get_session() as session:
        _require_admin(session, admin_id)
        txn_counts = dict(
            session.execute(select(Transaction.user_id, func.count(Transaction.id)).group_by(Transaction.user_id)).all()
        )
        acct_counts = dict(
            session.execute(select(Account.user_id, func.count(Account.id)).group_by(Account.user_id)).all()
        )
        users = session.scalars(select(User).order_by(User.created_at.desc()))
        return [
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "joined": u.created_at,
                "last_login": u.last_login_at,
                "active": bool(u.is_active),
                "admin": is_admin(u),
                "accounts": acct_counts.get(u.id, 0),
                "transactions": txn_counts.get(u.id, 0),
            }
            for u in users
        ]


def set_active(admin_id: int, user_id: int, active: bool) -> None:
    with get_session() as session:
        _require_admin(session, admin_id)
        if admin_id == user_id:
            raise AdminError("You can't disable your own account.")
        user = session.get(User, user_id)
        if user is None:
            raise AdminError("User not found.")
        user.is_active = bool(active)
        audit_service.record(
            "admin_user_enabled" if active else "admin_user_disabled",
            user.id,
            user.email,
            f"by admin {admin_id}",
            session=session,
        )


def delete_user(admin_id: int, user_id: int) -> None:
    with get_session() as session:
        _require_admin(session, admin_id)
        if admin_id == user_id:
            raise AdminError("Delete your own account from Settings instead.")
        user = session.get(User, user_id)
        if user is None:
            raise AdminError("User not found.")
        audit_service.record("account_deleted", user.id, user.email, f"by admin {admin_id}", session=session)
        delete_user_data(session, user)
