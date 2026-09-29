# PathForge deployment checklist

PathForge should not be exposed publicly until each required item below is
complete. Keep production secrets in the hosting provider's encrypted settings,
not in the repository.

## Required configuration

1. Set `PATHFORGE_ENV=production`.
2. Set `PATHFORGE_DATABASE_PATH` to an absolute path on persistent storage.
3. Set `PATHFORGE_ALLOWED_ORIGINS` to the exact HTTPS frontend origin. Separate
   multiple origins with commas; do not use a wildcard.
4. Set `RESEND_API_KEY` and `PATHFORGE_FROM_EMAIL` for account email.
5. If USAJobs synchronization is enabled, set `USAJOBS_API_KEY` and
   `USAJOBS_USER_AGENT`.

For local development, run `python configure_usajobs.py`. The API key is entered
without being displayed and is stored in the Git-ignored `.env` file. Production
credentials should still be configured through the hosting provider's secret
settings.

See `.env.example` for the complete variable names. The application does not
automatically load that file; copy the values into the deployment environment.

## Before each release

```powershell
python migrate_database.py
python -m pytest -q
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Then verify `/health/email`, registration, email verification, login, logout,
job discovery, saving a job, application tracking, employer access, and the
administrator moderation page through the deployed HTTPS site.

## Operational requirements

- Terminate TLS at the hosting platform or reverse proxy and redirect HTTP to
  HTTPS.
- Back up the SQLite database and test restoring it before launch.
- Store the database on a single persistent volume. Do not run multiple
  write-capable application instances against a network-mounted SQLite file.
- Run `sync_jobs.py` on a controlled schedule and alert when a source fails.
- Monitor application errors, response latency, disk space, database size, and
  the public `/health/email` availability signal.
- Keep API documentation disabled in production by retaining
  `PATHFORGE_ENV=production`.
- Review privacy, terms, retention, and contact information before collecting
  real applicant or employer data.

## Rollback preparation

Before deploying, retain the previous application build and create a verified
database backup. Database migrations are designed to be repeatable, but a code
rollback may still require restoring the matching database backup when a schema
change is not backward compatible.

Create and verify a backup before deployment or migration:

```bash
python backup_database.py
```

Restore only while PathForge is stopped. The restore command validates the
selected backup and creates another safety copy of the current database:

```bash
python restore_database.py backups/pathforge-YYYYMMDD-HHMMSS.db --confirm
```
