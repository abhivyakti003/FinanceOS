from datetime import timedelta

import pytest
from sqlalchemy import select

from app import config
from app.database.db import get_session
from app.database.models import EmailOTP, User
from app.services import auth_service
from app.services.auth_service import AuthError

# ---- Email validation -----------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "plainaddress",
        "abc@",
        "@gmail.com",
        "abc@gmail",
        "abc@@gmail.com",
        "abc@gmail..com",
        "a b@gmail.com",
        "abc@.com",
    ],
)
def test_rejects_malformed_emails(bad):
    with pytest.raises(AuthError):
        auth_service.validate_email_address(bad)


@pytest.mark.parametrize(
    "disposable",
    [
        "someone@mailinator.com",
        "x@yopmail.com",
        "x@10minutemail.com",
        "x@example.com",
        "x@test.com",
    ],
)
def test_rejects_disposable_and_fake_domains(disposable):
    with pytest.raises(AuthError):
        auth_service.validate_email_address(disposable)


def test_normalises_email():
    assert auth_service.validate_email_address("  Priya.S@Gmail.COM ") == "priya.s@gmail.com"


def test_deliverability_check_rejects_domain_without_mail(monkeypatch):
    """With the DNS check on, a domain that can't receive mail is refused."""
    from email_validator import EmailUndeliverableError

    def fake_validate(email, check_deliverability):
        assert check_deliverability is True
        raise EmailUndeliverableError("The domain name xyzabc-not-real.com does not exist.")

    monkeypatch.setattr(config, "EMAIL_CHECK_DELIVERABILITY", True)
    monkeypatch.setattr(auth_service, "validate_email", fake_validate)
    with pytest.raises(AuthError, match="does not exist"):
        auth_service.validate_email_address("someone@xyzabc-not-real.com")


@pytest.mark.parametrize("pw", ["short1", "allletters", "12345678", ""])
def test_rejects_weak_passwords(pw):
    with pytest.raises(AuthError):
        auth_service.validate_password(pw)


# ---- Registration with OTP ----------------------------------------------


def _user_count():
    with get_session() as s:
        return len(list(s.scalars(select(User))))


def test_account_is_only_created_after_otp(outbox):
    email = auth_service.start_registration("Priya", "priya@gmail.com", "Secret123", accepted_terms=True)
    assert email == "priya@gmail.com"
    assert _user_count() == 0, "user must not exist before verification"
    assert outbox[-1]["to"] == "priya@gmail.com"

    user = auth_service.verify_registration(email, outbox[-1]["code"])
    assert user.email_verified_at is not None
    assert _user_count() == 1
    # The pending password hash is cleared once used.
    with get_session() as s:
        assert s.scalars(select(EmailOTP)).one().pending_password_hash is None


def test_otp_is_not_stored_in_plain_text(outbox):
    auth_service.start_registration("Priya", "priya@gmail.com", "Secret123", accepted_terms=True)
    code = outbox[-1]["code"]
    with get_session() as s:
        row = s.scalars(select(EmailOTP)).one()
    assert code not in row.code_hash


def test_wrong_code_counts_attempts_and_locks(outbox):
    auth_service.start_registration("Priya", "priya@gmail.com", "Secret123", accepted_terms=True)
    for _i in range(config.OTP_MAX_ATTEMPTS - 1):
        with pytest.raises(AuthError, match="incorrect"):
            auth_service.verify_registration(
                "priya@gmail.com", "000000" if outbox[-1]["code"] != "000000" else "111111"
            )
    with pytest.raises(AuthError, match="Too many"):
        auth_service.verify_registration("priya@gmail.com", "999999" if outbox[-1]["code"] != "999999" else "888888")
    # Even the right code no longer works.
    with pytest.raises(AuthError):
        auth_service.verify_registration("priya@gmail.com", outbox[-1]["code"])
    assert _user_count() == 0


def test_expired_code_rejected(outbox):
    auth_service.start_registration("Priya", "priya@gmail.com", "Secret123", accepted_terms=True)
    with get_session() as s:
        otp = s.scalars(select(EmailOTP)).one()
        otp.expires_at = otp.expires_at - timedelta(minutes=config.OTP_EXPIRY_MINUTES + 1)
    with pytest.raises(AuthError, match="expired"):
        auth_service.verify_registration("priya@gmail.com", outbox[-1]["code"])


def test_resend_cooldown_and_old_code_invalidated(outbox):
    auth_service.start_registration("Priya", "priya@gmail.com", "Secret123", accepted_terms=True)
    with pytest.raises(AuthError, match="wait"):
        auth_service.resend_registration_code("priya@gmail.com")

    # Pretend the cooldown passed
    with get_session() as s:
        otp = s.scalars(select(EmailOTP)).one()
        otp.created_at = otp.created_at - timedelta(seconds=config.OTP_RESEND_COOLDOWN_SECONDS + 1)
    first_code = outbox[-1]["code"]
    auth_service.resend_registration_code("priya@gmail.com")
    second_code = outbox[-1]["code"]
    if first_code != second_code:
        with pytest.raises(AuthError):
            auth_service.verify_registration("priya@gmail.com", first_code)
    assert auth_service.verify_registration("priya@gmail.com", second_code).email == "priya@gmail.com"


def test_duplicate_email_does_not_reveal_account(make_user, monkeypatch):
    from app.services import email_service

    notices = []
    monkeypatch.setattr(email_service, "send_account_exists_email", lambda to: notices.append(to))
    make_user("priya@gmail.com")
    monkeypatch.setattr(config, "OTP_RESEND_COOLDOWN_SECONDS", 0)
    # Same response as a new sign-up, so the screen reveals nothing...
    assert (
        auth_service.start_registration("Other", "PRIYA@gmail.com", "Secret123", accepted_terms=True)
        == "priya@gmail.com"
    )
    # ...but the real owner is told by email.
    assert notices == ["priya@gmail.com"]
    with pytest.raises(AuthError):
        auth_service.verify_registration("priya@gmail.com", "123456")


def test_terms_must_be_accepted():
    with pytest.raises(AuthError, match="Terms"):
        auth_service.start_registration("Priya", "priya@gmail.com", "Secret123")


def test_lockout_also_applies_to_unknown_emails():
    for _ in range(config.MAX_FAILED_LOGINS):
        with pytest.raises(AuthError):
            auth_service.authenticate("nobody@gmail.com", "Wrong1234")
    with pytest.raises(AuthError, match="Too many failed attempts"):
        auth_service.authenticate("nobody@gmail.com", "Wrong1234")


def test_email_send_failure_creates_nothing(monkeypatch):
    from app.services import email_service

    def boom(*a, **k):
        raise email_service.EmailSendError("SMTP down")

    monkeypatch.setattr(email_service, "send_otp_email", boom)
    with pytest.raises(AuthError, match="SMTP down"):
        auth_service.start_registration("Priya", "priya@gmail.com", "Secret123", accepted_terms=True)
    with get_session() as s:
        assert s.scalars(select(EmailOTP)).first() is None


# ---- Login ----------------------------------------------------------------


def test_login_success_and_generic_errors(make_user):
    make_user("priya@gmail.com", "Secret123")
    assert auth_service.authenticate("Priya@Gmail.com", "Secret123").email == "priya@gmail.com"
    with pytest.raises(AuthError, match="Incorrect email or password"):
        auth_service.authenticate("priya@gmail.com", "Wrong1234")
    with pytest.raises(AuthError, match="Incorrect email or password"):
        auth_service.authenticate("nobody@gmail.com", "Secret123")


def test_login_lockout(make_user):
    make_user("priya@gmail.com", "Secret123")
    for _ in range(config.MAX_FAILED_LOGINS - 1):
        with pytest.raises(AuthError, match="Incorrect"):
            auth_service.authenticate("priya@gmail.com", "Wrong1234")
    with pytest.raises(AuthError, match="locked"):
        auth_service.authenticate("priya@gmail.com", "Wrong1234")
    with pytest.raises(AuthError, match="Too many failed attempts"):
        auth_service.authenticate("priya@gmail.com", "Secret123")


# ---- Password reset --------------------------------------------------------


def test_password_reset(make_user, outbox):
    make_user("priya@gmail.com", "Secret123")
    auth_service.start_password_reset("priya@gmail.com")
    assert outbox[-1]["purpose"] == "reset"
    auth_service.complete_password_reset("priya@gmail.com", outbox[-1]["code"], "NewSecret9")
    assert auth_service.authenticate("priya@gmail.com", "NewSecret9")


def test_password_reset_does_not_reveal_unknown_emails(outbox):
    auth_service.start_password_reset("ghost@gmail.com")  # no error
    assert outbox == []
