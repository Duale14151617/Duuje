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
- Automated backup: `.github/workflows/backup.yml` dumps the database, proves the dump restores into a scratch database, encrypts it and keeps it as a private artifact for 30 days. It needs two repository secrets (`BACKUP_DATABASE_URL` and `BACKUP_AGE_RECIPIENT`, the public half of the backup key); the steps are in `docs/BACKUP_AND_RECOVERY.md`.
- Keep `FIELD_ENCRYPTION_KEY` and the backup private key (`duuje-backup.key`) in a password manager, separate from the backups. Without them a backup cannot be used.
- PostgreSQL version: if the backup fails with a server version mismatch, change `PG_VERSION` in `.github/workflows/backup.yml` to the version the database runs (the dump client and the scratch restore database both use it).

## 5. Accounts and first boot
- A fresh database is empty. With `ARMYHQ_SAMPLE_MODE=1` the first boot creates `superadmin`, `hqadmin` and synthetic data using `ARMYHQ_SAMPLE_PASSWORD`.
- Privileged accounts must set up an authenticator app at first sign-in.
- Five failed sign-ins lock an account for 15 minutes. An administrator re-enabling the account clears the lock. When copying a temporary password, check there are no extra spaces.
- Vehicle categories are switched off with the **Remove** button, never deleted.

## 5b. Monthly routine
- **Access review (first working day of each month, about 10 minutes):** sign in as an administrator, open **Users**, open the **access review**, and act on it: disable leavers and accounts nobody uses, reset expired temporary passwords, confirm at least two user administrators, and check who holds whole-system access. (The same report can be emailed with `python manage.py access_review --email`.)
- Check that the nightly backup has a green tick in GitHub Actions and that UptimeRobot shows no unexplained downtime.

## 5c. Public pages
- `frontend/public/about.html` and `frontend/public/privacy.html` (linked from the login page footer) describe who runs the system and how data is handled. The owner details are filled in (name, Garowe, contact email, 15 November 2026); update the date, the contact and the retention periods when they change. These pages are what email providers ask to see.

## 6. Known limits of this deployment
- Free web service sleeps when idle; the first request can take up to a minute.
- Neon pauses an idle database; the first query after a quiet period is slower.
- Single Gmail sender, no domain, no owner/privacy page.
- When sample mode is off the start command now skips the sample-data steps instead of failing part-way.

## 7. When the ministry approves hosting
Ask them for: where the system will run, which domain it will use, where data may be stored, who runs backups, and how email should be sent. Then:
1. Stand up the database and the app on the approved host using the Docker image and the variables in section 2.
2. Authenticate the new sender domain with an email provider and set `DEFAULT_FROM_EMAIL`; remove the Apps Script variables.
3. Turn sample mode off, create real administrators with `python manage.py create_hq_admin`, and enrol MFA for each.
4. Add an owner/contact page and a privacy policy to the site.
5. Move backups to the approved location and run a restore test before go-live.

## 8. Contacts
- System owner and operator: Abdullaahi Ahmed Mohamoud Du'ale, Garowe, Puntland, Somalia (duujesuites@gmail.com, also the account that sends the system's email)
- Ministry contact: (fill in when approval is granted)
- Hosting/domain owner: (fill in; the demo uses free Render and Neon accounts held by the operator)
- Where the passwords and keys are stored: (fill in: the password manager that holds the backup private key (`duuje-backup.key`), `FIELD_ENCRYPTION_KEY`, the Apps Script `SECRET` and the Render/Neon/GitHub logins)
