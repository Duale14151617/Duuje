# ID cards, official letters and scheduled reports

## ID cards and official letters (menu: People > ID cards and letters)
* **Issue a card:** open a person's record, Personal tab, **Identity card > Issue ID card**. The person must be serving and have a profile photo. The card opens ready to print (front with photo, back with QR code). Issuing a new card cancels the earlier one. A card lasts `ID_CARD_VALID_YEARS` (default 2).
* **Write a letter:** People > ID cards and letters > **New official letter**. Choose the issuing unit, recipient, subject and text. The text is fixed once issued. The letter prints on a letterhead with a QR code and a short **text fingerprint**.
* **Print:** use the Print button; in the print dialog you can also save as PDF. Cards are 85.6 x 54 mm (credit-card size), letters are A4.
* **Check a document:** scanning the QR code opens `/verify/<code>` (no sign-in needed). It says GENUINE, or NOT VALID (revoked, expired, holder no longer serving) or NOT FOUND (treat as fake). For a valid ID card it shows name, rank, unit and a partly hidden service number. It never shows the photo, date of birth, phone or any profile data. For a valid letter it shows subject, recipient, signer and the fingerprint (compare it with the one printed on the paper; an altered text will not match).
* **Revoke:** open the document and give a reason. Documents are never deleted; the record keeps who revoked it and why.
* **Who can:** permissions `credentials.view` and `credentials.issue`. Granted by default to the super administrator, headquarters administrator, regional chief and branch administrator (for units in their scope). Adjust in Users > Roles if you want fewer people to issue cards.
* **Audit:** every issue, open, revoke and public check is written to the audit log (never the letter text).
* **Settings:** `SITE_URL` (already set on Render) decides the address inside the QR code; `ID_CARD_VALID_YEARS`; `ISSUANCE_REF_PREFIX` (default `PHQ`); `THROTTLE_DOCVERIFY` (default `30/min` per address).
* **Library:** QR codes are drawn on the server with the `segno` package (added to `backend/requirements.txt`). Nothing is sent to an outside service.

## Scheduled reports by email (menu: Reporting > Scheduled reports)
* **What it sends:** the personnel strength report as plain text: serving and on-file totals, joined/left/promoted in the window, by region and by rank. Counts only; no names or service numbers.
* **Who receives it:** only active users with a **verified email** who can also view that area's personnel report. The list in the form only offers such people. The figures are built with the permissions of the person who created the schedule; if they lose access the run is skipped.
* **Create one:** choose a name, the area (that unit and everything below it), daily / weekly / monthly, the hour, and the recipients. **Send test to me** emails only you (your email must be verified on the Account page).
* **Times** are read in `SCHEDULES_TIMEZONE` (default `Africa/Mogadishu`).
* **Permission:** `schedules.manage` (super administrator, headquarters administrator, regional chief for their region).
* **Switch off the whole feature:** `SCHEDULED_REPORTS_ENABLED=0`.

### Making it run on time (needs one of these)
Outgoing email must already work (see `docs/APPS_SCRIPT_MAILER.md` or the Brevo/SMTP settings). Until it does, a run records "Email not set up" and sends nothing.

The server only sends a report when something asks it to check what is due. Pick one:
1. **Free, simplest: an outside pinger** (for example cron-job.org). Set the environment variable `SCHEDULES_CRON_TOKEN` to a long random value (24+ characters) on Render. Then create a job that calls, every 15 minutes: `POST https://armyhq.onrender.com/api/v1/schedules/run-due/` with the header `X-Cron-Token: <the same value>`. It is safe to call often: only schedules that are due are sent, and each is sent once. The call also wakes a sleeping free service.
2. **Render Cron Job** (paid): run `python manage.py send_scheduled_reports` every 15 minutes with the same environment as the web service.

Without either, nothing is sent automatically (the "Send now" button still works).
