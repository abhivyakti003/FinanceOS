"""Family sharing.

You invite a family member by email. Once they accept, they can see your
finances read-only (balances, spending, goals, investments). They can never
edit anything. Sharing is one-way: to see theirs, they invite you too.
Either side can stop sharing at any time.
"""

import logging

from sqlalchemy import or_, select

from app.database.db import get_session
from app.database.models import FamilyShare, User
from app.services import audit_service, email_service
from app.services.auth_service import AuthError, validate_email_address

log = logging.getLogger(__name__)

RELATIONS = ["Spouse / partner", "Parent", "Child", "Sibling", "Other"]
MAX_SHARES = 10


class FamilyError(ValueError):
    pass


def invite(owner_id: int, email: str, relation: str | None = None) -> FamilyShare:
    try:
        email = validate_email_address(email)
    except AuthError as exc:
        raise FamilyError(str(exc)) from exc

    with get_session() as session:
        owner = session.get(User, owner_id)
        if owner is None:
            raise FamilyError("Account not found.")
        if owner.email == email:
            raise FamilyError("You can't invite yourself.")
        existing = session.scalar(
            select(FamilyShare).where(FamilyShare.owner_id == owner_id, FamilyShare.member_email == email)
        )
        if existing:
            raise FamilyError("You've already invited this person.")
        count = len(list(session.scalars(select(FamilyShare.id).where(FamilyShare.owner_id == owner_id))))
        if count >= MAX_SHARES:
            raise FamilyError(f"You can share with up to {MAX_SHARES} people.")
        member = session.scalar(select(User).where(User.email == email))
        share = FamilyShare(
            owner_id=owner_id,
            member_email=email,
            member_id=member.id if member else None,
            relation=relation if relation in RELATIONS else None,
            status="pending",
        )
        session.add(share)
        session.flush()
        owner_name = owner.name
        audit_service.record("family_invite", owner_id, owner.email, f"invited {email}", session=session)

    # Let them know. Sharing still works if the email can't be sent.
    try:
        email_service.send_email(
            email,
            f"{owner_name} wants to share their finances with you on FinanceOS",
            f"{owner_name} has invited you to view their finances on FinanceOS (read-only).\n\n"
            "Log in to FinanceOS (or create an account with this email address), then open "
            "the Family page to accept.",
        )
    except Exception:
        log.warning("Couldn't send the family invite email to %s", email, exc_info=True)
    return share


def outgoing(owner_id: int) -> list[FamilyShare]:
    with get_session() as session:
        return list(
            session.scalars(
                select(FamilyShare).where(FamilyShare.owner_id == owner_id).order_by(FamilyShare.created_at)
            )
        )


def _me(session, user_id: int) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise FamilyError("Account not found.")
    return user


def incoming(user_id: int, status: str | None = None) -> list[dict]:
    """Invitations sent to this user, with the owner's name and email."""
    with get_session() as session:
        me = _me(session, user_id)
        query = (
            select(FamilyShare, User)
            .join(User, User.id == FamilyShare.owner_id)
            .where(or_(FamilyShare.member_id == user_id, FamilyShare.member_email == me.email))
        )
        if status:
            query = query.where(FamilyShare.status == status)
        return [
            {
                "id": share.id,
                "owner_id": owner.id,
                "owner_name": owner.name,
                "owner_email": owner.email,
                "relation": share.relation,
                "status": share.status,
            }
            for share, owner in session.execute(query)
        ]


def accept(user_id: int, share_id: int) -> None:
    with get_session() as session:
        me = _me(session, user_id)
        share = session.get(FamilyShare, share_id)
        if share is None or share.member_email != me.email:
            raise FamilyError("Invitation not found.")
        share.member_id = user_id
        share.status = "accepted"


def decline_or_leave(user_id: int, share_id: int) -> None:
    """The member removes themselves (declines an invite or stops viewing)."""
    with get_session() as session:
        me = _me(session, user_id)
        share = session.get(FamilyShare, share_id)
        if share is None or share.member_email != me.email:
            raise FamilyError("Invitation not found.")
        session.delete(share)


def revoke(owner_id: int, share_id: int) -> None:
    """The owner stops sharing."""
    with get_session() as session:
        share = session.scalar(select(FamilyShare).where(FamilyShare.id == share_id, FamilyShare.owner_id == owner_id))
        if share is None:
            raise FamilyError("Not found.")
        audit_service.record(
            "family_revoke", owner_id, None, f"stopped sharing with {share.member_email}", session=session
        )
        session.delete(share)


def can_view(viewer_id: int, owner_id: int) -> bool:
    if viewer_id == owner_id:
        return True
    with get_session() as session:
        return (
            session.scalar(
                select(FamilyShare.id).where(
                    FamilyShare.owner_id == owner_id,
                    FamilyShare.member_id == viewer_id,
                    FamilyShare.status == "accepted",
                )
            )
            is not None
        )


def shared_with_me(user_id: int) -> list[dict]:
    return [i for i in incoming(user_id) if i["status"] == "accepted"]
