# Deployment

Three ways to run FinanceOS, from simplest to production.

## 1. Your own laptop (Windows)

See the Quick start in the README: install Python 3.12, run `setup.bat`, then `run.bat`.
Data stays in `financeos.db` on your machine. `APP_ENV=development`.

## 2. Production on a server with Docker (recommended)

Works on any Linux VPS (for example 2 GB RAM, Ubuntu 24.04, from a provider with an
Indian region such as AWS Mumbai, DigitalOcean Bangalore or Azure Central India).

### Prerequisites

- A domain name, with an **A record** pointing at the server's IP.
- Docker with the Compose plugin: `curl -fsSL https://get.docker.com | sh`
- Ports 80 and 443 open in the firewall; keep 8501 and 5432 closed to the internet.
- An email sender: Brevo with your own domain verified is best for deliverability.

### Steps

```bash
git clone <your-repo> financeos && cd financeos
cp .env.example .env
nano .env
```

Set at least:

```
APP_ENV=production
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
POSTGRES_PASSWORD=<long random password>
DOMAIN=finance.example.com
SUPPORT_EMAIL=support@example.com
ADMIN_EMAILS=you@example.com
EMAIL_PROVIDER=brevo
BREVO_API_KEY=<key>
SMTP_FROM=FinanceOS <no-reply@example.com>
LEGAL_OPERATOR_NAME=<your company or name>
LEGAL_GRIEVANCE_OFFICER=<name, email>
LEGAL_JURISDICTION=<city>
LEGAL_LAST_UPDATED=<date>
```

Leave `DATABASE_URL` out; docker-compose sets it to the bundled PostgreSQL.

```bash
docker compose --profile https up -d --build
docker compose ps            # all services "healthy" / "running"
docker compose logs -f app   # watch the first start
```

Open `https://<your domain>`. Caddy obtains the TLS certificate automatically.

What runs:

| Service | Purpose |
| --- | --- |
| `db` | PostgreSQL 16, data in the `pgdata` volume |
| `app` | FinanceOS, runs migrations on start, health-checked |
| `worker` | Daily reminder emails, Monday summaries and backups at `DAILY_JOBS_HOUR` |
| `caddy` | HTTPS, HSTS and security headers, reverse proxy to the app |

### Updating

```bash
git pull
docker compose --profile https up -d --build   # migrations run automatically
```

Back up first (see OPERATIONS.md).

## 3. Without Docker on a Linux server

1. Install Python 3.12, PostgreSQL 16 and Caddy (or nginx with certbot).
2. Create the database and user (see README, PostgreSQL section).
3. `python3.12 -m venv venv && . venv/bin/activate && pip install -r requirements.txt -r requirements-postgres.txt`
4. Fill in `.env` as above, with `DATABASE_URL=postgresql://...`.
5. `python -m app.database.init_db`
6. Run the app as a systemd service:

```ini
# /etc/systemd/system/financeos.service
[Unit]
Description=FinanceOS
After=network.target postgresql.service

[Service]
User=financeos
WorkingDirectory=/opt/financeos
Environment=STREAMLIT_SERVER_HEADLESS=true STREAMLIT_CLIENT_SHOW_ERROR_DETAILS=false
ExecStart=/opt/financeos/venv/bin/streamlit run streamlit_app.py --server.address 127.0.0.1 --server.port 8501
Restart=always

[Install]
WantedBy=multi-user.target
```

7. A second unit (or cron) for `scripts/scheduler.py`.
8. Point Caddy at `127.0.0.1:8501` using `deploy/Caddyfile`.

## Production checklist

- [ ] `APP_ENV=production` (the app refuses to start with unsafe settings)
- [ ] Strong `SECRET_KEY` and `POSTGRES_PASSWORD`; `.env` readable only by the app user
- [ ] PostgreSQL, not SQLite
- [ ] HTTPS working; ports 8501 and 5432 not reachable from the internet
- [ ] Email sender on your own domain (SPF, DKIM, DMARC set up with the provider)
- [ ] `ADMIN_EMAILS` and `SUPPORT_EMAIL` set
- [ ] Legal pages filled in and reviewed by a lawyer (docs/legal)
- [ ] Daily backups running and copied off the server; a restore tested
- [ ] Server disk encryption on (most cloud providers offer it by default)
- [ ] Uptime monitoring on `https://<domain>/_stcore/health`
- [ ] CI passing on the commit you deploy

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `APP_ENV` | development | `production` enables strict checks |
| `SECRET_KEY` | (random per run) | Signs OTP hashes; required in production |
| `DATABASE_URL` | SQLite in project folder | `postgresql://user:pass@host:5432/db` |
| `EMAIL_PROVIDER` | smtp | `smtp` or `brevo` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | Gmail | SMTP sending |
| `BREVO_API_KEY` | | Brevo sending |
| `EMAIL_DEV_MODE` | false | Print codes instead of sending (never in production) |
| `EMAIL_CHECK_DELIVERABILITY` | true | DNS check on sign-up emails |
| `OTP_EXPIRY_MINUTES` | 10 | Code lifetime |
| `ADMIN_EMAILS` | | Comma-separated admin emails |
| `SUPPORT_EMAIL` | | Shown in legal pages and emails |
| `SESSION_TIMEOUT_MINUTES` | 30 | Idle logout |
| `BACKUP_KEEP` | 14 | Backups kept |
| `DAILY_JOBS_HOUR` | 8 | Worker run time |
| `LOG_LEVEL` | INFO | Logging detail |
| `AA_PROVIDER` | mock | `mock` or `setu` |
| `POSTGRES_PASSWORD`, `DOMAIN` | | Docker deployment |
| `LEGAL_*` | | Filled into the Privacy Policy and Terms |
