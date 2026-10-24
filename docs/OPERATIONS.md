# Operations

Day-to-day running of a FinanceOS installation.

## Health

- Health endpoint: `GET /_stcore/health` returns `ok`. Docker uses it; point an uptime
  monitor (UptimeRobot, Better Stack) at it too.
- Admin page: users, recent activity, database in use, latest backup, security log.

## Logs

- App and jobs log to `logs/financeos.log` (rotates at 5 MB, keeps 5 files) and to the console.
- Docker: `docker compose logs -f app` or `... worker`.
- Logs never contain passwords, codes, API keys or transaction details.
- Set `LOG_LEVEL=DEBUG` temporarily to investigate a problem.

## Scheduled jobs

| Job | Docker | Windows |
| --- | --- | --- |
| Bill reminders, Monday summaries | `worker` service | Task Scheduler → `notify.bat` daily |
| Database backup | `worker` service | Task Scheduler → `backup.bat` daily |

## Backups

- Created daily by the worker (or `backup.bat`), on demand from Admin → Back up now, or
  `python scripts/backup.py`.
- Stored in `backups/` (Docker volume `backups`); the newest `BACKUP_KEEP` are kept.
- **Copy backups off the server** daily (for example `rclone` to cloud storage). A backup on
  the same disk doesn't survive a lost server.
- Test a restore every month.

### Restore: SQLite

1. Stop the app.
2. Copy the chosen `backups/financeos-YYYYMMDD-HHMMSS.db` over `financeos.db`.
3. Delete `financeos.db-wal` and `financeos.db-shm` if present.
4. Start the app.

### Restore: PostgreSQL (Docker)

```bash
docker compose stop app worker
docker compose cp backups/financeos-YYYYMMDD-HHMMSS.dump db:/tmp/restore.dump
docker compose exec db pg_restore --clean --if-exists -U financeos -d financeos /tmp/restore.dump
docker compose start app worker
```

## Upgrades and migrations

1. Back up.
2. Deploy the new version (`git pull`, rebuild).
3. Migrations run automatically on start (`python -m app.database.init_db`).
4. Check the logs and the Admin page.
5. To roll back code, also restore the backup taken in step 1.

## Common tasks

| Task | How |
| --- | --- |
| Make someone an admin | Add their email to `ADMIN_EMAILS`, restart |
| Disable a user | Admin → Users → untick Active → Save |
| Delete a user on request | Admin → Delete a user (or they use Settings → Delete my account) |
| Change sender email | `python scripts/configure.py`, restart |
| Find failed logins | Admin → Security log → `login_failed` / `login_locked` |

## Incident response

1. **Contain:** if accounts may be compromised, disable them on the Admin page; rotate
   `SECRET_KEY`, database and email passwords; restart.
2. **Investigate:** Admin → Security log and `logs/`.
3. **Recover:** restore from the last good backup if data was damaged.
4. **Notify:** under the DPDP Act, report personal data breaches to the Data Protection
   Board of India and to affected users. CERT-In requires reporting cyber incidents within
   6 hours. Check current requirements with your lawyer.
5. **Learn:** write down what happened and what changes prevent it.
