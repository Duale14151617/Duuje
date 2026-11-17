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
- Shows "Puntland Police Force HQ" instead of "Puntland Defence Forces HQ" (read from `/api/v1/profile/`).

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
4. **Email:** create a second Apps Script (or reuse the same Gmail account with a new script and a new `SECRET`) and set
   `APPS_SCRIPT_URL`, `APPS_SCRIPT_TOKEN`, `DEFAULT_FROM_EMAIL`, `EMAIL_VERIFICATION_ENABLED=1`, `PASSWORD_FORGOT_ENABLED=1`.
5. **Backups, uptime, alerts:** copy `.github/workflows/backup.yml` and add the repository secrets for the Police database; add
   a second UptimeRobot monitor for the new `/api/v1/health/live/`.
6. **Sign in** as `superadmin`, then create the administrators and add districts, stations and people with the normal tools.

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
