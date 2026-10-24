# Security

## Reporting a vulnerability

Email the address in `SUPPORT_EMAIL` with details and steps to reproduce. Please don't
open a public issue. We aim to reply within 3 working days.

## Controls in place

**Accounts**
- Sign-up requires a verified email: format check, DNS deliverability check, disposable
  domains blocked, then a 6-digit code.
- Codes are random (`secrets`), HMAC-SHA256 hashed with `SECRET_KEY`, expire after 10
  minutes, allow 5 wrong tries, 60-second resend cooldown, 5 per hour.
- Passwords: at least 8 characters with a letter and a number, bcrypt hashed.
- Login: 5 failures lock the email for 15 minutes, tracked for unknown emails too, with
  constant-time comparison against a dummy hash.
- No account enumeration: sign-up, password reset and lockouts look the same whether or
  not an email is registered.
- Idle sessions end after 30 minutes; disabled accounts are logged out immediately.

**Data**
- Every query filters by the logged-in user; ownership is checked on every write.
- Family sharing is read-only, opt-in by the owner and revocable.
- Admins see counts, never financial details.
- Money is exact decimal; database transactions are atomic (all-or-nothing).
- Reports and exports are built in memory, never on shared disk paths.
- Users can export and delete all their data.

**Operations**
- Production mode refuses to start with unsafe settings.
- HTTPS with HSTS and security headers (Caddy); app and database not exposed directly.
- Docker image runs as a non-root user.
- Audit log of logins, failures, lockouts, password changes, exports, deletions and
  admin actions.
- Error details hidden from users in production.
- Dependencies pinned to minimum safe versions; CI runs lint and tests on every change.

## Known limitations and roadmap

| Area | Status | Plan |
| --- | --- | --- |
| Encryption at rest | Relies on disk / managed-database encryption | Add field-level encryption for narrations if required |
| Database-level isolation | Enforced in the service layer and tests | PostgreSQL row-level security as a second layer |
| Two-factor login | Email OTP at sign-up and reset only | Optional TOTP (authenticator app) at login |
| Rate limiting by IP | Per-email limits only | Add at the proxy (Caddy rate-limit module / Cloudflare) |
| Bank linking | Mock provider | Live AA partner after regulatory onboarding |
| Penetration test | Not yet done | Before public launch |

## Secrets

- `.env` holds all secrets. Never commit it (it's in `.gitignore`); restrict file permissions.
- Rotate `SECRET_KEY` if leaked (pending codes stop working; nothing else breaks).
- Use a dedicated sender account or API key, never a personal mailbox password.
