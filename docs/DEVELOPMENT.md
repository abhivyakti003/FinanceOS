# Development

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt ruff
python scripts/configure.py    # or set EMAIL_DEV_MODE=true in .env to print codes locally
python -m app.database.init_db
streamlit run streamlit_app.py
```

## Everyday commands

| Command | What it does |
| --- | --- |
| `pytest` | All tests on a temporary SQLite database |
| `TEST_DATABASE_URL=postgresql://... pytest` | Same tests on PostgreSQL (use an empty test database) |
| `ruff check .` | Lint |
| `ruff format .` | Format |
| `alembic revision --autogenerate -m "message"` | New migration after editing models |
| `python -m app.database.init_db` | Apply migrations |

CI (`.github/workflows/ci.yml`) runs lint, both test suites and a fresh-database
migration on every push. Keep it green.

## Project layout

```
streamlit_app.py      Entry point: settings check, auth screens, navigation, session checks
pages/                One file per screen
app/config.py         Settings from .env, production validation
app/logging_config.py Logging setup
app/database/         Engine, sessions (get_session, use_session), models, migration runner
app/services/         Business logic
app/ui/               Theme, shared widgets, legal page viewer
scripts/              configure, backup, notifications, scheduler
migrations/           Alembic
docs/                 Documentation and legal templates
deploy/               Caddyfile
tests/                pytest suite
```

## Conventions

- **Pages never touch the database.** Put logic in a service and call it.
- **Every service function that reads or writes user data takes `user_id` first** and
  filters by it. Look rows up with both the id and the `user_id`.
- **User-facing errors** are raised as a service-specific `ValueError` subclass
  (`AuthError`, `BillError`...) with a message safe to show; pages catch and `st.error()` it.
- **Money** is `Decimal`; convert to float only for charts.
- **Several writes that belong together** share one transaction: accept `session=None`
  and use `with use_session(session) as session:`.
- **Security-relevant actions** call `audit_service.record(...)`.
- **Copy**: plain, sentence case, say what happens ("Save budget", not "Submit").

## Adding a feature

1. Model changes in `app/database/models.py`, then `alembic revision --autogenerate`.
   Review the generated file; add `server_default` for new non-null columns.
2. Service in `app/services/` with `user_id` filtering and validation.
3. Tests in `tests/`, including one proving another user can't access the data.
4. Page in `pages/`, registered in the `pages` dict in `streamlit_app.py`.
5. Update docs and `CHANGELOG.md`.

## Connecting a real Account Aggregator

Implement `SetuAAProvider` (or another provider class) in `app/services/aa_service.py`:
`create_consent`, `consent_status`, `fetch_accounts` returning the documented dict shape.
Set `AA_PROVIDER` in `.env`. The rest of the app (accounts, dedupe, categorisation,
balances) already works with that shape.
