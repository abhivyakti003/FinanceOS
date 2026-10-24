"""Registration with email OTP, login, and password reset.

How registration works:
1. start_registration(): validates the email (format + the domain really
   accepts mail + not a throwaway domain), validates the password, and emails
   a 6-digit code. No user row is created yet.
2. verify_registration(): if the code is right, the account is created with
   email_verified_at set. Only verified users can ever exist.

Checking the domain rules out made-up addresses like "abc@xyz.com". The OTP
then proves the person actually owns the inbox, which is the only reliable
way to know an email is "real".
"""

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

import bcrypt
from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select

from app import config
from app.database.db import get_session
from app.database.models import EmailOTP, LoginAttempt, User, utcnow
from app.services import audit_service, email_service


class AuthError(ValueError):
    """An error whose message is safe to show to the user."""


# Throwaway inbox providers. Extend this list as you find more.
DISPOSABLE_DOMAINS = {
    "mailinator.com",
    "guerrillamail.com",
    "guerrillamail.info",
    "sharklasers.com",
    "10minutemail.com",
    "10minutemail.net",
    "tempmail.com",
    "temp-mail.org",
    "temp-mail.io",
    "yopmail.com",
    "yopmail.net",
    "trashmail.com",
    "getnada.com",
    "dispostable.com",
    "maildrop.cc",
    "mintemail.com",
    "throwawaymail.com",
    "fakeinbox.com",
    "mailnesia.com",
    "mohmal.com",
    "emailondeck.com",
    "tempail.com",
    "tempr.email",
    "discard.email",
    "spamgourmet.com",
    "mailcatch.com",
    "moakt.com",
    "burnermail.io",
    "inboxkitten.com",
    "mail.tm",
    "mailpoof.com",
    "tmail.ws",
    "tempinbox.com",
    "example.com",
    "example.org",
    "example.net",
    "test.com",
}

_PURPOSES = {"register", "reset"}


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email_address(email: str) -> str:
    """Return the normalised email, or raise AuthError explaining the problem."""
    email = normalize_email(email)
    if not email:
        raise AuthError("Enter your email address.")
    try:
        result = validate_email(
            email,
            check_deliverability=config.EMAIL_CHECK_DELIVERABILITY,
        )
    except EmailNotValidError as exc:
        raise AuthError(f"This email address isn't valid: {exc}") from exc

    normalized = result.normalized.lower()
    domain = normalized.rsplit("@", 1)[1]
    if domain in DISPOSABLE_DOMAINS or any(domain.endswith("." + d) for d in DISPOSABLE_DOMAINS):
        raise AuthError("Temporary or disposable email addresses aren't allowed. Use your personal or work email.")
    return normalized


def validate_password(password: str) -> None:
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    if len(password.encode()) > 72:
        raise AuthError("Password must be at most 72 characters.")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise AuthError("Password must contain at least one letter and one number.")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password1")


def _hash_code(email: str, purpose: str, code: str) -> str:
    message = f"{purpose}:{email}:{code}".encode()
    return hmac.new(config.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def _generate_code() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(config.OTP_LENGTH))


# ---------------------------------------------------------------------------
# OTP issuing and checking
# ---------------------------------------------------------------------------


def _issue_otp(
    session,
    email: str,
    purpose: str,
    pending_name=None,
    pending_password_hash=None,
    account_exists_notice: bool = False,
) -> None:
    now = utcnow()

    latest = session.scalar(
        select(EmailOTP)
        .where(EmailOTP.email == email, EmailOTP.purpose == purpose)
        .order_by(EmailOTP.created_at.desc(), EmailOTP.id.desc())
        .limit(1)
    )
    if latest:
        wait = config.OTP_RESEND_COOLDOWN_SECONDS - (now - latest.created_at).total_seconds()
        if wait > 0:
            raise AuthError(f"Please wait {int(wait) + 1} seconds before requesting another code.")

    sent_last_hour = session.scalar(
        select(func.count(EmailOTP.id)).where(
            EmailOTP.email == email,
            EmailOTP.purpose == purpose,
            EmailOTP.created_at >= now - timedelta(hours=1),
        )
    )
    if sent_last_hour >= config.OTP_MAX_PER_HOUR:
        raise AuthError("Too many codes requested for this email. Try again in an hour.")

    # Only the newest code should work.
    for old in session.scalars(
        select(EmailOTP).where(
            EmailOTP.email == email,
            EmailOTP.purpose == purpose,
            EmailOTP.consumed_at.is_(None),
        )
    ):
        old.consumed_at = now

    code = _generate_code()
    session.add(
        EmailOTP(
            email=email,
            purpose=purpose,
            code_hash=_hash_code(email, purpose, code),
            pending_name=pending_name,
            pending_password_hash=pending_password_hash,
            expires_at=now + timedelta(minutes=config.OTP_EXPIRY_MINUTES),
            created_at=now,
        )
    )
    session.flush()

    # If sending fails, the exception rolls back the new code as well.
    try:
        if account_exists_notice:
            # Someone tried to sign up with a registered email. Tell the owner
            # instead of revealing on screen that the account exists.
            email_service.send_account_exists_email(email)
        else:
            email_service.send_otp_email(email, code, purpose)
    except (email_service.EmailNotConfigured, email_service.EmailSendError) as exc:
        raise AuthError(str(exc)) from exc


def _check_otp(email: str, purpose: str, code: str) -> EmailOTP:
    """Validate a code. Returns the OTP row (already marked used) or raises AuthError.

    Wrong attempts are saved before the error is raised, so the attempt
    limit can't be bypassed.
    """
    code = (code or "").strip()
    error = None
    otp_row = None

    with get_session() as session:
        otp = session.scalar(
            select(EmailOTP)
            .where(
                EmailOTP.email == email,
                EmailOTP.purpose == purpose,
                EmailOTP.consumed_at.is_(None),
            )
            .order_by(EmailOTP.created_at.desc(), EmailOTP.id.desc())
            .limit(1)
        )
        now = utcnow()
        if otp is None:
            error = "No active code for this email. Request a new code."
        elif otp.expires_at < now:
            otp.consumed_at = now
            error = "This code has expired. Request a new code."
        elif otp.attempts >= config.OTP_MAX_ATTEMPTS:
            otp.consumed_at = now
            error = "Too many wrong attempts. Request a new code."
        elif not hmac.compare_digest(otp.code_hash, _hash_code(email, purpose, code)):
            otp.attempts += 1
            left = config.OTP_MAX_ATTEMPTS - otp.attempts
            if left <= 0:
                otp.consumed_at = now
                error = "Too many wrong attempts. Request a new code."
            else:
                error = f"That code is incorrect. {left} attempt{'s' if left != 1 else ''} left."
        else:
            otp.consumed_at = now
            otp_row = otp

    if error:
        raise AuthError(error)
    return otp_row


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def start_registration(name: str, email: str, password: str, accepted_terms: bool = False) -> str:
    """Validate details and email a code. Returns the normalised email.

    If the email is already registered, the screen looks exactly the same
    (so nobody can find out who uses FinanceOS), and the owner gets an email
    saying someone tried to sign up with their address.
    """
    name = (name or "").strip()
    if not name:
        raise AuthError("Enter your name.")
    if len(name) > 100:
        raise AuthError("Name must be at most 100 characters.")
    if not accepted_terms:
        raise AuthError("Please accept the Terms and Privacy Policy to continue.")

    email = validate_email_address(email)
    validate_password(password)

    with get_session() as session:
        exists = session.scalar(select(User.id).where(User.email == email)) is not None
        _issue_otp(
            session,
            email,
            "register",
            pending_name=None if exists else name,
            pending_password_hash=None if exists else hash_password(password),
            account_exists_notice=exists,
        )
    return email


def resend_registration_code(email: str) -> None:
    email = normalize_email(email)
    with get_session() as session:
        latest = session.scalar(
            select(EmailOTP)
            .where(EmailOTP.email == email, EmailOTP.purpose == "register")
            .order_by(EmailOTP.created_at.desc(), EmailOTP.id.desc())
            .limit(1)
        )
        if latest is None:
            raise AuthError("Start registration again.")
        exists = session.scalar(select(User.id).where(User.email == email)) is not None
        if not exists and not latest.pending_password_hash:
            raise AuthError("Start registration again.")
        _issue_otp(
            session, email, "register", latest.pending_name, latest.pending_password_hash, account_exists_notice=exists
        )


def verify_registration(email: str, code: str) -> User:
    """Check the code and create the account. Returns the new user."""
    email = normalize_email(email)
    otp = _check_otp(email, "register", code)

    with get_session() as session:
        if session.scalar(select(User.id).where(User.email == email)) or not otp.pending_password_hash:
            raise AuthError("That code is incorrect. Request a new code.")
        now = utcnow()
        user = User(
            name=otp.pending_name or "",
            email=email,
            password_hash=otp.pending_password_hash,
            email_verified_at=now,
            consented_at=now,
            last_login_at=now,
            failed_logins=0,
            is_active=True,
        )
        session.add(user)
        session.flush()
        stored = session.get(EmailOTP, otp.id)
        if stored:
            stored.pending_password_hash = None  # the code has done its job
        audit_service.record("register", user.id, email, session=session)
    return user


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


def authenticate(email: str, password: str) -> User:
    """Check email and password.

    Failed attempts are counted per email whether or not the account exists,
    so the "locked" message can't reveal who is registered.
    """
    email = normalize_email(email)
    generic = "Incorrect email or password."
    error = None
    event = None
    authenticated = None

    with get_session() as session:
        now = utcnow()
        attempt = session.get(LoginAttempt, email)
        user = session.scalar(select(User).where(User.email == email))

        if attempt and attempt.locked_until and attempt.locked_until > now:
            minutes = int((attempt.locked_until - now).total_seconds() // 60) + 1
            error = f"Too many failed attempts. Try again in {minutes} minute{'s' if minutes != 1 else ''}."
            event = "login_blocked"
        else:
            ok = verify_password(password, user.password_hash if user else _DUMMY_HASH) and user is not None
            if ok and not user.is_active:
                error = "This account has been disabled. Contact the app administrator."
                event = "login_disabled"
            elif ok:
                if attempt:
                    session.delete(attempt)
                user.last_login_at = now
                authenticated = user
                event = "login_success"
            else:
                if attempt is None:
                    attempt = LoginAttempt(email=email, failed_count=0)
                    session.add(attempt)
                attempt.failed_count = (attempt.failed_count or 0) + 1
                attempt.updated_at = now
                if attempt.failed_count >= config.MAX_FAILED_LOGINS:
                    attempt.locked_until = now + timedelta(minutes=config.LOCKOUT_MINUTES)
                    attempt.failed_count = 0
                    error = (
                        f"Too many failed attempts. Login is locked for {config.LOCKOUT_MINUTES} "
                        "minutes for this email."
                    )
                    event = "login_locked"
                else:
                    error = generic
                    event = "login_failed"

    audit_service.record(event, authenticated.id if authenticated else (user.id if user else None), email)
    if error:
        raise AuthError(error)
    return authenticated


def get_user(user_id: int) -> User | None:
    if not user_id:
        return None
    with get_session() as session:
        return session.get(User, user_id)


# ---------------------------------------------------------------------------
# Password reset and change
# ---------------------------------------------------------------------------


def start_password_reset(email: str) -> None:
    """Email a reset code if the account exists.

    Says nothing about whether the email is registered, so this form can't be
    used to find out who has an account.
    """
    email = normalize_email(email)
    with get_session() as session:
        if session.scalar(select(User.id).where(User.email == email)):
            _issue_otp(session, email, "reset")


def complete_password_reset(email: str, code: str, new_password: str) -> None:
    email = normalize_email(email)
    validate_password(new_password)
    _check_otp(email, "reset", code)
    with get_session() as session:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            raise AuthError("Account not found.")
        user.password_hash = hash_password(new_password)
        attempt = session.get(LoginAttempt, email)
        if attempt:
            session.delete(attempt)
        audit_service.record("password_reset", user.id, email, session=session)


def change_password(user_id: int, current_password: str, new_password: str) -> None:
    validate_password(new_password)
    with get_session() as session:
        user = session.get(User, user_id)
        if user is None or not verify_password(current_password, user.password_hash):
            raise AuthError("Your current password is incorrect.")
        user.password_hash = hash_password(new_password)
        audit_service.record("password_changed", user.id, user.email, session=session)
