# Police deployment (separate copy of the system)

The Police system is the SAME code as the Army system, run as a second deployment with its own database, secrets and email
settings. One variable chooses the organization: `ARMYHQ_PROFILE=police`. The Army deployment is not touched.

## What the Police profile does
- Builds the Police structure on start-up (`apply_police_structure`): Police Headquarters with CID, Traffic and Tax Collection
  directorates, and **one regional command per region**: Bari, Karkaar, Mudug, Nugaal, Gardafuu, Highland, Sool, Sanaag, Cayn.
  Each regional command also gets CID, Traffic and Tax Collection sections.
- Adds the appointment titles: regional commander and deputy, district chief and deputy, station commander and deputy.
- Districts, stations and Kooxo are added by authorized users in the app (the real names are theirs to enter). Every new
  station is created with two Kooxo, "Koox 1" and "Koox 2"; add more by hand. A city can have as many stations as it needs.
- Uses the same 18-rank ladder as the Army. Internally the service branch keeps the code `ARMY`, labelled "Police".
- Shows "Puntland Police HQ" instead of "Puntland Defence Forces HQ" (read from `/api/v1/profile/`).

## Set it up (free tier, about 30 minutes)
1. **Repository:** copy this repo (a new private GitHub repo) or add a second Render service from the same repo.
2. **Database:** create a NEW Neon project (Singapore, pooling off). Never share a database with the Army system.
3. **Render service:** new Web Service from the repo (Docker). Set:
   - `POSTGRES_HOST`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT=5432`, `POSTGRES_SSLMODE=require`
   - `ARMYHQ_PROFILE=police`
   - `ARMYHQ_ADMIN_PASSWORD` = a strong password (12+ characters). On first start this creates the user `superadmin` with
     that password; the first sign-in forces a password change and authenticator setup. **Remove the variable afterwards.**
   - NEW values for `DJANGO_SECRET_KEY`, `FIELD_ENCRYPTION_KEY` (and the HMAC key if you use one): never reuse the Army's.
   - `TRUST_PROXY_HEADERS=1`, `NUM_PROXIES=3`, `ARMYHQ_SITE_URL=https://<new-service>.onrender.com`, allowed hosts and CSRF origins.
   - Do NOT set `ARMYHQ_SAMPLE_MODE` (no synthetic data in the Police system).
4. **Email:** follow `docs/APPS_SCRIPT_MAILER.md`: create a second Apps Script (or reuse the same Gmail account with a new script and a new `SECRET`) and set
   `APPS_SCRIPT_URL`, `APPS_SCRIPT_TOKEN`, `DEFAULT_FROM_EMAIL`, `EMAIL_VERIFICATION_ENABLED=1`, `PASSWORD_FORGOT_ENABLED=1`.
5. **Backups, uptime, alerts:** copy `.github/workflows/backup.yml` and add the repository secrets for the Police database; add
   a second UptimeRobot monitor for the new `/api/v1/health/live/`.
6. **Second super administrator (recommended).** Only a super administrator can reset another super administrator's password or
   authenticator, so with one account a lost phone locks everyone out of those powers. Sign in as `superadmin`, open Users, create a
   second account for a different trusted person, then open it, choose Assign role: Super administrator, unit: Headquarters (needs an
   authenticator code). The new person signs in, changes the password and enrols their own authenticator. HQ administrators cannot
   grant this role. Keep the two accounts with two different people.
7. **Account pictures.** HQ administrators and super administrators can set a profile picture for their own account and for other
   accounts (Account page, or Users, open an account). Only a super administrator can change a super administrator's picture. An
   account without its own picture shows the photo on its linked personnel record, else the default.
8. **Notification emails (optional).** Set `NOTIFICATION_EMAILS_ENABLED=1` once email works. Each user then chooses "Email me when I
   have new notifications" on their Account page (needs a verified address). The email is generic ("you have N unread
   notifications") and never names a person, report or leave request; at most one per user every 30 minutes
   (`NOTIFICATION_EMAIL_MIN_MINUTES`), which also keeps a Gmail sender well inside its daily limit.
9. **Printed documents.** Every PDF now carries the Police crest, headquarters name, a reference number, the date, who generated it
   and a confidential footer. The reference is created in the browser to identify that printout; it is not a registered serial number.
10. **Status footer and sign-in notice.** Signed-in pages end with a footer showing whether the system is healthy, the running version
    and build, and a support contact: set `SUPPORT_CONTACT` (an email address or phone number) in Render to show it. The version
    is only sent to signed-in users. On the dashboard each user sees their previous sign-in (time and address) and a warning if
    sign-in attempts failed on their account in between; it is read from the audit log and can be dismissed for the session.
11. **Sign in** as `superadmin`, then create the administrators and add districts, stations and people with the normal tools.

## Backup codes, passkeys and the idle warning

- **Backup codes.** When a user switches on the authenticator app they are shown 10 one-time codes (copy, download or print). A code can be typed in the authenticator-code box at sign-in or when confirming a sensitive action, and works once. Account page: make a new set any time (the old set stops working). Using a code is written to the audit log, and for privileged accounts it raises an alert.
- **Passkeys.** On the Account page a user who already has the authenticator app can add passkeys (security key, or fingerprint/face unlock on a phone or laptop). A passkey replaces the 6-digit code, not the password: sign in with the password, then choose "Use a passkey". Nothing to configure on Render; the passkey is tied to the site address, so register passkeys on the final address. If you later move to a new domain, users add them again. Resetting a user's authenticator also removes their backup codes and passkeys.
- **Idle warning.** Two minutes before the idle limit (default 30 minutes) a dialog counts down with "Stay signed in". Typing or clicking keeps the session alive. The 12-hour cap cannot be extended; a banner shows the last 5 minutes. Change with `SESSION_IDLE_SECONDS`, `SESSION_IDLE_WARNING_SECONDS`, `SESSION_ABSOLUTE_SECONDS`.
- **Database.** Run migrations (the Docker start command already does): `0008_backup_codes_and_passkeys`.

## Backups (nightly, off-site, encrypted)

Render's free database has no real backups, and **a free Render database is deleted after 30 days unless you upgrade it**. The repository includes `.github/workflows/backup.yml`, which every night dumps the database, encrypts it and keeps it for 30 days as a private download in GitHub (Actions, the run, "Artifacts"). It can also refresh a live copy in Neon.

One-time setup (the GitHub repository must be **private**):

1. On any computer install `age` (https://age-encryption.org) and run `age-keygen -o policehq-backup.key`. It prints a public key starting `age1...`. **Keep `policehq-backup.key` offline with two trusted people.** Without it a backup cannot be opened; with it anyone holding a backup can read the data.
2. In Render open the database and copy its **External Database URL**.
3. In GitHub: Settings, Secrets and variables, Actions, New repository secret. Add `BACKUP_DATABASE_URL` (the URL from step 2) and `BACKUP_AGE_RECIPIENT` (the `age1...` public key). Optional: `BACKUP_NEON_URL` (a Neon connection string) to also keep a ready-to-use second copy.
4. Actions tab, "Nightly database backup", Run workflow. Check it turns green and an artifact appears. If your Render database is not PostgreSQL 16, change `PG_VERSION` in the file.

To make the **System health** page show whether the backup really ran, also set a long random value (24+ characters) as `BACKUP_HEARTBEAT_TOKEN` on Render, and add two more GitHub secrets: `BACKUP_HEARTBEAT_TOKEN` (the same value) and `BACKUP_HEARTBEAT_URL` (your site address, for example `https://policehq.onrender.com`). A backup older than 36 hours is then shown as a problem.

To restore, download the artifact, then use `ops/restore_test.sh` (restores into a scratch database and checks it) or `age -d -i policehq-backup.key policehq-....dump.age > dump` followed by `pg_restore --clean --if-exists --no-owner -d <new database URL> dump`. Test a restore once now, not on the day you need it.

## System health, due-soon reminders and the audit export

- **System health** (menu: Administration, for user administrators) lists what is configured and working: database, encryption key, secure cookies, debug and sample-data modes, email (with a "send me a test" button), the scheduler, the nightly backup and the number of administrators. Open it after every deployment.
- **Due soon** (Reports and tasks) lists ID cards expiring within 30 days, vehicles due for service within 14 days, and court dates or ended remand orders in custody within 2 days, limited to the areas the person can see. Once a day each person who has something due gets one in-app notification (counts only). It rides on the same outside scheduler as scheduled reports: call `POST /api/v1/schedules/run-due/` with the `X-Cron-Token` header at least once a day (every 15 minutes is fine; each person is told at most once a day). The System health page shows when the scheduler last called.
- **Audit log** filters by person, action, outcome and dates, and exports the filtered list as CSV (up to 10,000 rows, needs a fresh authenticator code). The file's SHA-256 is recorded in the audit log itself, so a copy given to an investigator can be matched later.

## Assumptions to confirm with the Police
Labels are working labels: Somali names of the titles and units, and whether CID, Traffic and Tax Collection also exist as
sections inside every regional command (they are created there and can be retired). There is no commissioner appointment yet; add
the title as data when decided. The PDF header, the authenticator-app label, the About and Privacy pages, the offline page and the login page now follow the profile.
In the Police deployment the login page shows the Police emblem (`frontend/public/police-emblem.jpg`) as the crest, the Police
Headquarters photo (`frontend/public/login/police-hq.jpg`) as the background, and the judiciary logo
(`frontend/public/judiciary.jpg`, "Puntland Court of Armed Forces") in the footer and on the Institutions page (Somali: "Maxkamada Ciidamada Qalabka Sida ee Puntland") in place of the Ministry of
Security. Still showing Army wording or images, to replace when the Police supplies its own: the installed-app name and icons
(`frontend/public/manifest.webmanifest`, `icon-*.png`, `favicon*`) and the right-hand map background (`login/bg-right.jpg`).
The About page still names the Ministry of Security Puntland; confirm the correct wording for the Police.
