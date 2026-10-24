# FinanceOS

Personal finance for India: every bank account, card, investment, bill and goal in one
calm place, with verified sign-up, family sharing and a full admin and security toolkit.

![CI](https://github.com/<your-user>/financeos/actions/workflows/ci.yml/badge.svg)

## Features

- **Money in one place:** bank statement import (CSV, Excel, PDF from HDFC, SBI, ICICI,
  Axis, Kotak and more), Account Aggregator bank linking (sample mode until live), manual entries.
- **Smart categorisation** of UPI and card narrations that learns from your corrections;
  transfers and card bill payments recognised automatically.
- **Insights:** monthly summary, category and merchant breakdowns, unusual spends,
  recurring payments, forecasts and a financial health score.
- **Planning:** budgets, goals, bills with email reminders, net worth, investments with
  CAS import, credit score tracking.
- **Family sharing:** read-only, owner-controlled.
- **Reports:** PDF summaries; full data export to Excel.
- **Security:** email OTP sign-up, no account enumeration, login lockout, idle logout,
  audit log, consent recording, admin tools, backups.
- **Runs anywhere:** SQLite on a laptop, PostgreSQL + Docker + HTTPS in production.

## Quick start (Windows laptop)

1. Install **Python 3.12** from https://www.python.org/downloads/ and tick
   **"Add python.exe to PATH"**.
2. Unzip this folder, for example to your Desktop.
3. Get a sender for sign-up codes, either:
   - a Gmail **App Password** (https://myaccount.google.com/apppasswords, needs
     2-Step Verification on), or
   - a free **Brevo** API key (brevo.com), which works on networks that block email ports.
4. Double-click **`setup.bat`** and answer the questions (sender, your admin email,
   test email).
5. Double-click **`run.bat`**. FinanceOS opens at http://localhost:8501.

macOS / Linux: `./setup.sh`, then `./run.sh`.

Try it: **Accounts → Link bank automatically** (any 10-digit mobile number) loads sample
data, or import `samples/hdfc_style_statement.csv`.

## Production

```bash
cp .env.example .env    # set APP_ENV=production, secrets, domain, email, legal details
docker compose --profile https up -d --build
```

PostgreSQL, the app, a daily-jobs worker and automatic HTTPS. Full guide and checklist:
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Documentation

| Document | For |
| --- | --- |
| [User guide](docs/USER_GUIDE.md) | People using the app |
| [Deployment](docs/DEPLOYMENT.md) | Putting it online, environment variables, production checklist |
| [Operations](docs/OPERATIONS.md) | Backups, restore, logs, monitoring, incidents |
| [Security](docs/SECURITY.md) | Controls, known limitations, reporting issues |
| [Architecture](docs/ARCHITECTURE.md) | How the code is organised |
| [Data model](docs/DATA_MODEL.md) | Tables and relationships |
| [Development](docs/DEVELOPMENT.md) | Setup, tests, conventions, migrations |
| [Privacy Policy](docs/legal/PRIVACY_POLICY.md), [Terms](docs/legal/TERMS_OF_SERVICE.md) | Templates to review with a lawyer |
| [Changelog](CHANGELOG.md) | What changed in each version |

## How data is stored

One database holds all users. Every row carries its owner's `user_id`, and every query
filters by it, so people only see their own data (family sharing is opt-in and
read-only). Passwords and codes are stored as one-way hashes. Writes are atomic
transactions. Details in [Architecture](docs/ARCHITECTURE.md) and [Security](docs/SECURITY.md).

## Tests

```
pytest            # 110 tests, temporary database
ruff check .      # lint
```

## What still needs outside partners

- **Live bank linking:** an Account Aggregator partner (Setu, Finvu, OneMoney) and
  regulatory onboarding. The integration point is ready in `app/services/aa_service.py`.
- **Live credit scores:** a credit bureau partnership.
- **Legal review** of the Privacy Policy and Terms, and a security test before public launch.
