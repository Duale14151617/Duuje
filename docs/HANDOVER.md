# ARMY HQ - handover and deployment notes (demo deployment)

Keep this file free of passwords, keys and connection strings. Values live only in Render, Neon, GitHub and your password manager.

## 1. What this is
- Django (API) + React (web app) in one Docker image, served from a single Render web service named `armyhq-demo` (Singapore).
- Database: PostgreSQL on Neon (free tier, Singapore). It does not expire. The old Render free database expired after 30 days and was lost.
- The deployment is a **sample build with synthetic data only**. It is not approved for operational use. Do not enter real personnel records.
- Source: this repository. Deploys are triggered from Render ("Manual Deploy" or on push).

## 2. Environment variables on the `armyhq-demo` service
Names only. Set them in Render, Environment.

| Purpose | Variables |
|---|---|
| Database (Neon, direct host, no `-pooler`) | `POSTGRES_HOST`, `POSTGRES_PORT` (5432), `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_SSLMODE` (`require`) |
| Core secrets | `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `FIELD_HMAC_KEY` (if used) |
| First boot users (sample mode) | `ARMYHQ_SAMPLE_MODE` (1), `ARMYHQ_SAMPLE_PASSWORD` (12+ chars, not a database password) |
| Behind Render and Cloudflare | `TRUST_PROXY_HEADERS` (1), `NUM_PROXIES` (3 on Render today; re-check if the proxy chain changes) |
| Public address and email links | `ARMYHQ_SITE_URL` (https://armyhq-demo.onrender.com), `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` as needed |
| Email sending | `APPS_SCRIPT_URL`, `APPS_SCRIPT_TOKEN`, `DEFAULT_FROM_EMAIL` |
| Email features switched on | `EMAIL_VERIFICATION_ENABLED` (1), `PASSWORD_FORGOT_ENABLED` (1) |
| Alerts | `ARMYHQ_ALERT_EMAILS` (optional extra recipients) |
| Temporary debugging only | `DEBUG_CLIENT_IP` (leave unset; it logs client addresses) |

Never keep `BREVO_API_KEY` set unless Brevo is working: the Apps Script sender is chosen first, then Gmail API, then Brevo, then SMTP.

## 3. How email works
- Render's free tier blocks SMTP, and Brevo declined the account (no owned domain, no owner/privacy page on the site).
- Mail goes out through a Google Apps Script web app that runs as the sender Gmail account (`docs/APPS_SCRIPT_MAILER.md`). The script holds a `SECRET` that must equal `APPS_SCRIPT_TOKEN`.
- Limits: about 100 recipients per day for a consumer Gmail account. Mail comes from that Gmail address.
- Password reset emails contain a link plus a one-time code. Each user must verify their own email in the account icon (top right) before reset and alerts reach them.
- If mail stops: check Render logs for `email could not be sent`, the script's Executions page, the daily quota, and that the token still matches.
- Rotate `SECRET` and `APPS_SCRIPT_TOKEN` together if either leaks.

## 4. Database and backups
- Neon connection details: take them from the Connect dialog with pooling **off**. If a password is ever pasted anywhere public, reset it in Neon and update `POSTGRES_PASSWORD` in Render.
- Automated backup: `.github/workflows/backup.yml` dumps the database, proves the dump restores into a scratch database, encrypts it and keeps it as a private artifact for 30 days. It is manual until you add two repository secrets (`BACKUP_DATABASE_URL`, `BACKUP_PASSPHRASE`) and enable the schedule; the steps are at the top of that file and in `docs/BACKUP_AND_RECOVERY.md`.
- Keep `FIELD_ENCRYPTION_KEY` and the backup passphrase in a password manager, separate from the backups. Without them a backup cannot be used.
- Neon's pg client version: if the backup fails with a server version mismatch, change both `postgres:17` images in the workflow to the version Neon runs.

## 5. Accounts and first boot
- A fresh database is empty. With `ARMYHQ_SAMPLE_MODE=1` the first boot creates `superadmin`, `hqadmin` and synthetic data using `ARMYHQ_SAMPLE_PASSWORD`.
- Privileged accounts must set up an authenticator app at first sign-in.
- Five failed sign-ins lock an account for 15 minutes. An administrator re-enabling the account clears the lock. When copying a temporary password, check there are no extra spaces.
- Vehicle categories are switched off with the **Remove** button, never deleted.

## 6. Known limits of this deployment
- Free web service sleeps when idle; the first request can take up to a minute.
- Neon pauses an idle database; the first query after a quiet period is slower.
- Single Gmail sender, no domain, no owner/privacy page.
- Startup seeding prints "Background seeding stopped early" if sample mode is off and the database already has users. Harmless, but worth cleaning up.

## 7. When the ministry approves hosting
Ask them for: where the system will run, which domain it will use, where data may be stored, who runs backups, and how email should be sent. Then:
1. Stand up the database and the app on the approved host using the Docker image and the variables in section 2.
2. Authenticate the new sender domain with an email provider and set `DEFAULT_FROM_EMAIL`; remove the Apps Script variables.
3. Turn sample mode off, create real administrators with `python manage.py create_hq_admin`, and enrol MFA for each.
4. Add an owner/contact page and a privacy policy to the site.
5. Move backups to the approved location and run a restore test before go-live.

## 8. Contacts (fill in)
- System owner: 
- Ministry contact: 
- Hosting/domain owner: 
- Where the passwords and keys are stored: 
