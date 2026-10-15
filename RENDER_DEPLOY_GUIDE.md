# ARMY HQ v2.1.2 — Render demo deployment

This package adds a Render Blueprint and a single-origin Docker deployment. It keeps the existing React UI and Django API, serving both from the same Render web service so session authentication and CSRF remain same-origin. PostgreSQL is a separate Render database.

## Before you start

- Use this only as a **synthetic demo**. Do not enter real personnel, operational, security, or confidential records.
- Render's free PostgreSQL plan is temporary (currently 30 days) and may be subject to plan/region availability. Export anything you need to keep.
- The `ARMYHQ_DEMO_PASSWORD` environment variable sets one shared password for the synthetic demo accounts created by the project's demo seed command. Use a unique password of at least 12 characters; do not reuse a personal password. Privileged demo roles require MFA enrolment at first login.
- The FIELD_ENCRYPTION_KEY must remain stable after the first deployment, otherwise encrypted MFA secrets cannot be decrypted. Do not rotate it casually.

## Deploy from an Android phone

1. Extract this ZIP and upload the entire `armyhq-v2.1.2` folder contents to a **private GitHub repository**. Keep `Dockerfile` and `render.yaml` in the repository root, beside `frontend/` and `backend/`.
2. Open https://dashboard.render.com/ and choose **New + → Blueprint**.
3. Connect the repository containing `render.yaml`, then choose **Apply**. Render should create `armyhq-demo` and `armyhq-demo-db` from the blueprint. Review the plan and any charges shown before confirming.
4. Open the `armyhq-demo` web service → **Environment**. Set `FIELD_ENCRYPTION_KEY` to a valid Fernet key and set `ARMYHQ_DEMO_PASSWORD` to a unique password (12+ characters). Keep both secret. Save changes and redeploy if requested.
5. Generate a Fernet key using a trusted local Python environment with `cryptography` installed:

   ```python
   from cryptography.fernet import Fernet
   print(Fernet.generate_key().decode())
   ```

   Do not paste the key into public chats or commit it to GitHub.
6. Wait for the build/deploy to finish. Open the service URL. Health check should be `/api/v1/health/live/`.
7. If deployment fails, open **Logs** and share the error text (remove secrets, tokens, database URLs, and passwords first).

## Demo accounts

The `seed_demo_data` command creates synthetic usernames documented in `docs/SETUP.md` (for example `demo.hqadmin`, `demo.hqreports`, `demo.auditor`, `demo.bari.chief`, and others). They all use the password set in `ARMYHQ_DEMO_PASSWORD`. Privileged roles must enrol an authenticator app at first login. Keep this demo site unlisted and do not use real data.

## What this deployment configuration does

- Builds the current frontend with `npm run build` (not demo-only in-memory mode).
- Serves React and `/api/v1/*` from one origin.
- Uses Render PostgreSQL, runs migrations and idempotent reference/demo seed commands at container start.
- Keeps Django debug off, uses generated Django secret key, disables export/integrations by default, and uses HTTPS provided by Render.
- Runs synthetic demo seeding only when `ARMYHQ_DEMO_MODE=1` is explicitly set.

## Important notes

- `SECURE_SSL_REDIRECT=0` is set because Render terminates HTTPS at its proxy. The app trusts forwarded HTTPS only with `TRUST_PROXY_HEADERS=1`; review this before production use.
- This is a deployment starter, not proof of a successful live deploy. The image must build and the database migrations must complete on Render. Test sign-in, MFA enrolment, CSRF-protected writes, logout, SPA refreshes, and logs before sharing.
- This package is not approved or configured for real-world Army, Navy, or Police operations. For production, use a paid, institutionally approved deployment with backups, retention, monitoring, incident response, and a reviewed threat model.
