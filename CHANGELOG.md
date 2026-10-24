# Changelog

## 1.0.0 (production release)

### Security
- Sign-up no longer reveals whether an email is registered; the real owner gets an email instead.
- Login attempts are limited per email, including emails without an account.
- Audit log of security events (logins, failures, lockouts, password changes, exports,
  deletions, admin actions), with a Security log on the Admin page and recent activity in Settings.
- Terms and Privacy Policy consent at sign-up (recorded), with templates in docs/legal.
- Production mode (`APP_ENV=production`) refuses to start with unsafe settings.

### Reliability
- Paying a bill with its transaction, importing a statement with its balance update, and
  syncing a bank account are each a single atomic database transaction.
- SQLite set to full durability (every commit survives a power cut).
- Structured, rotating log files in `logs/`.

### Deployment
- Dockerfile (non-root, health check), docker-compose with PostgreSQL, the app, a daily-jobs
  worker and an optional Caddy HTTPS proxy.
- GitHub Actions CI: lint, tests on SQLite and PostgreSQL, migrations on a fresh database.
- Ruff lint and format configuration; code base formatted and lint-clean.

### Documentation
- docs/: architecture, data model, deployment, operations, security, development, user guide,
  legal templates.

### Tests
- 110 tests.

## 0.1.0


### Security fixes
- Every query now filters by `user_id`. Before, `delete_expense`,
  `update_expense_amount` and `search_by_category` let any user change or
  read anyone's data by ID. Tests cover this (`test_users_cannot_touch_each_others_data`).
- PDF reports and charts are built in memory. Before, every user wrote to the
  same `FinanceOS_Executive_Report.pdf` and `reports/charts/*.png`, so users
  could download each other's reports.
- Sign-up needs a verified email: format check, DNS check that the domain
  really receives mail, disposable-address blocklist, then a 6-digit OTP.
  The account is created only after the code is verified.
- OTP codes are stored hashed, expire in 10 minutes, allow 5 wrong tries,
  have a 60-second resend cooldown and a limit of 5 per hour.
- Login locks for 15 minutes after 5 wrong passwords, and the error doesn't
  reveal whether an email is registered. Forgot-password via OTP added.
- Passwords need 8+ characters with a letter and a number.
- `CURRENT_USER_ID = 1` removed. `.gitignore` keeps `.env`, databases and venv out of git.
- Stack traces are hidden from users (`.streamlit/config.toml`).

### Bug fixes
- Forecasts grouped by month number only, so Jan 2026 and Jan 2027 merged and
  December predicted "month 13". Now uses year + month and skips the
  unfinished current month.
- The Random Forest forecast was removed: tree models can't predict outside
  the range they were trained on, so it couldn't follow a trend.
- "Savings forecast" was actually all-time savings. It's now next month's
  expected income minus expected spending.
- Division by zero for goals with a 0 target and budgets of 0 (now rejected).
- Goal ETA divided all-time savings by 12; now uses your real average monthly savings.
- Health score was capped at 70 for users without budgets; they now get a
  neutral score. The duplicate "spending ratio" part was replaced with an
  emergency-fund check.
- Budgets compared all-time spending with a monthly limit; now compares the
  selected month. Budgets per category are unique (setting again updates).
- Category matching: "ola" matched "cola" and "granola". Now whole words only.
- Money uses exact decimals instead of floats.
- The rupee sign printed as a black box in the PDF; the report uses "Rs.".
- `requirements.txt` was UTF-16 and missing `bcrypt` and `reportlab`.
- Sessions always close (`with get_session()`), even on errors.
- Services no longer `print()`; they return values or raise errors the UI shows.

### New features
- One `Transaction` table (debit/credit) linked to accounts, replacing
  separate Expense and Income tables. Balances are calculated, never drift.
- Bank statement import: CSV, Excel and PDF (including password-protected
  PDFs), with automatic header detection for HDFC, SBI, ICICI, Axis and
  Kotak layouts. Re-importing the same statement adds nothing twice.
- UPI narration parsing (merchant, mode, reference number).
- Learning categories: change one Swiggy payment's category and all Swiggy
  payments follow, including future imports.
- Transfers between your own accounts and credit card bill payments are
  detected so they aren't counted as spending or income.
- Investments count as savings, not spending.
- Recurring payment detection (subscriptions, rent, SIPs, EMIs) with next due dates.
- Unusual spend alerts that explain themselves ("3.2x your usual").
- Account Aggregator flow with a mock provider and a Setu skeleton.
- Multi-page app: Overview, Transactions, Insights, Accounts, Import,
  Recurring, Budgets, Goals, Net worth, Reports, Settings.
- Alembic migrations.
- Real pytest suite (72 tests) on a temporary database.

### Removed
`report_service.py` (old), `app/services.zip`, empty folders, the old
`finance.db`, `main.py` and the scripts in `tests/` that wrote to your real database.

## 0.2.0

### Setup
- `setup.bat` and `run.bat` for one-click setup and start; `scripts/configure.py`
  writes `.env` interactively and can send a test email.
- `.env` and the database are always found in the project folder, whichever
  folder the app is started from.

### Design
- Minimal light and dark theme (Manrope font, soft neutral background,
  green accent, bordered cards), consistent page headers.
- Overview opens with a plain-language summary sentence, a "Needs attention"
  panel, and category drill-down.
- Menu shows live counts for due bills and family invites.

### New features
- Investments: holdings, gains, allocation, edit in place, CAS PDF import.
- Bills: due dates, mark paid (optionally records the transaction), snooze,
  overdue tracking, create from detected recurring payments.
- Email bill reminders and weekly Monday summaries (`notify.bat`), with
  on/off switches in Settings.
- Family sharing: read-only access by email invite, revocable any time.
- Credit score history with gauge, trend and tips.
- Settings: test email, export all data to Excel, delete account.
- Net worth and PDF reports include investments and bills.
- 19 new tests (91 total).

## 0.3.0

### Email
- Gmail falls back from port 587 to 465 automatically.
- Clear errors: blocked network, wrong App Password, rejected address.
- Brevo option that sends over HTTPS, for networks that block email ports.
- `scripts/configure.py` lets you choose Gmail or Brevo and sets the admin email.

### Database and multiple users
- PostgreSQL support (`DATABASE_URL`, `requirements-postgres.txt`); all
  migrations and all tests verified on both SQLite and PostgreSQL.
- SQLite tuned for several simultaneous users (WAL, busy timeout,
  thread-safe connections).
- Backups: `backup.bat`, `scripts/backup.py`, and a button on the Admin page,
  keeping the newest 14. Works for SQLite and PostgreSQL (pg_dump).
- Admin page: user list, last login, activity counts, disable or delete
  users, database info. Admins never see financial data.
- Users can be disabled; disabled users are logged out and can't log in.
- Automatic logout after 30 minutes of inactivity.
- Last login time recorded.
- 13 new tests (104 total).
