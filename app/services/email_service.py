"""Sends email through SMTP (Gmail etc.) or the Brevo web API."""

import json
import logging
import smtplib
import socket
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import parseaddr

from app import config

log = logging.getLogger(__name__)


class EmailNotConfigured(RuntimeError):
    pass


class EmailSendError(RuntimeError):
    pass


def is_configured() -> bool:
    if config.EMAIL_PROVIDER == "brevo":
        return bool(config.BREVO_API_KEY and config.SMTP_FROM)
    return bool(config.SMTP_HOST and config.SMTP_USERNAME and config.SMTP_PASSWORD)


def _send_smtp(msg: EmailMessage) -> None:
    context = ssl.create_default_context()
    attempts = [(config.SMTP_PORT, config.SMTP_USE_SSL)]
    # If one Gmail port is blocked, try the other one.
    if config.SMTP_HOST == "smtp.gmail.com":
        attempts.append((465, True) if config.SMTP_PORT != 465 else (587, False))

    last_error = None
    for port, use_ssl in attempts:
        try:
            if use_ssl:
                with smtplib.SMTP_SSL(config.SMTP_HOST, port, context=context, timeout=config.SMTP_TIMEOUT) as s:
                    s.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(config.SMTP_HOST, port, timeout=config.SMTP_TIMEOUT) as s:
                    s.starttls(context=context)
                    s.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
                    s.send_message(msg)
            return
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailSendError(
                "Gmail rejected the login. Use an App Password (not your normal password), "
                "and make sure SMTP_USERNAME is the Gmail that created it."
            ) from exc
        except smtplib.SMTPRecipientsRefused as exc:
            raise EmailSendError("This email address rejected our message. Check it and try again.") from exc
        except (
            TimeoutError,
            ConnectionError,
            socket.gaierror,
            ssl.SSLError,
            smtplib.SMTPServerDisconnected,
            smtplib.SMTPConnectError,
        ) as exc:
            log.warning("SMTP port %s failed: %s", port, exc)
            last_error = exc
        except smtplib.SMTPException as exc:
            log.exception("SMTP error")
            raise EmailSendError(f"The email server returned an error: {exc}") from exc

    raise EmailSendError(
        f"Couldn't reach the email server ({config.SMTP_HOST}). Your network is probably "
        "blocking email ports 587 and 465, which is common on office and college Wi-Fi. "
        "Try a mobile hotspot, or switch to Brevo: python scripts\\configure.py"
    ) from last_error


def _send_brevo(to: str, subject: str, text: str, html: str | None) -> None:
    name, address = parseaddr(config.SMTP_FROM)
    payload = {
        "sender": {"name": name or "FinanceOS", "email": address},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": text,
    }
    if html:
        payload["htmlContent"] = html
    request = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload).encode(),
        headers={"api-key": config.BREVO_API_KEY, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=config.SMTP_TIMEOUT).read()  # noqa: S310  (fixed https URL)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="ignore")[:300]
        raise EmailSendError(f"Brevo refused the email ({exc.code}): {detail}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EmailSendError("Couldn't reach Brevo. Check your internet connection.") from exc


def send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    if config.EMAIL_DEV_MODE:
        # Development only. Never enable this on a public server.
        print(f"\n[EMAIL_DEV_MODE] To: {to}\nSubject: {subject}\n{text}\n", flush=True)
        return

    if not is_configured():
        raise EmailNotConfigured("Email sending is not set up. Run: python scripts\\configure.py")

    if config.EMAIL_PROVIDER == "brevo":
        _send_brevo(to, subject, text, html)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM or config.SMTP_USERNAME
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    _send_smtp(msg)


def send_otp_email(to: str, code: str, purpose: str) -> None:
    action = "create your FinanceOS account" if purpose == "register" else "reset your FinanceOS password"
    minutes = config.OTP_EXPIRY_MINUTES
    text = (
        f"Your FinanceOS verification code is {code}\n\n"
        f"Use it to {action}. It expires in {minutes} minutes.\n\n"
        "If you didn't request this, you can ignore this email. "
        "Never share this code with anyone, including FinanceOS staff."
    )
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px">
      <p>Use this code to {action}:</p>
      <p style="font-size:32px;font-weight:bold;letter-spacing:6px;margin:16px 0">{code}</p>
      <p>It expires in {minutes} minutes.</p>
      <p style="color:#666;font-size:13px">If you didn't request this, ignore this email.
      Never share this code with anyone, including FinanceOS staff.</p>
    </div>
    """
    send_email(to, f"{code} is your FinanceOS code", text, html)


def send_account_exists_email(to: str) -> None:
    text = (
        "Someone (hopefully you) tried to create a FinanceOS account with this email address, "
        "but you already have one.\n\n"
        "If it was you, just log in. Forgot your password? Use 'Forgot your password?' on the "
        "login screen.\n\n"
        "If it wasn't you, you can ignore this email. Your account is safe."
    )
    send_email(to, "You already have a FinanceOS account", text)
