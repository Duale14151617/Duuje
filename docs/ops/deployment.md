# Deployment

Three separate environments (development, staging, production), each with its own database, secrets, domain and `prod.env`. Production secrets never enter source control or CI logs.

## Prerequisites (business/IT decisions still open — see production-readiness.md)
Hosting provider and region, domain + DNS, operational owner, identity provider choice (first-party auth is used today), email/SMS/payment providers, retention periods.

## First install (staging and production)
1. Host: Linux VM with Docker. Open only 80/443. Create `/etc/duale/prod.env` (mode 600, owner root) from `.env.example`. Required: `Jwt__Key`, `Mfa__Key` (`openssl rand -base64 32`), `Bootstrap__AdminEmail/Password`, `Finance__CallbackSecret`, `Metrics__Token`, `Security__MfaRequiredPermissions` (decide), `DB_PASSWORD`, `DOMAIN`, `ACME_EMAIL`.
2. Generate migrations once, in a dev checkout, and commit them: `scripts/make-migrations.sh` (creates `Initial` and `PostgresConstraints`). Review the SQL.
3. `docker compose -f docker-compose.prod.yml --env-file /etc/duale/prod.env up -d db clamav`, then apply migrations as a deliberate step: run the API once with `AUTO_MIGRATE=true`, or `dotnet ef database update` from CI against the target. Keep `AUTO_MIGRATE=false` afterwards.
4. `docker compose -f docker-compose.prod.yml --env-file /etc/duale/prod.env up -d`. Caddy obtains certificates automatically; `/metrics` and `/health/*` are blocked at the proxy (scrape from inside the network: `api:8080`).
5. `BASE=https://<domain> ADMIN_EMAIL=… ADMIN_PASSWORD=… scripts/smoke.sh`. Remove `Bootstrap__*` from the env file after the first admin exists, enrol the admin in MFA, and create named platform accounts.
6. Schedule `scripts/backup.sh` and a monthly `scripts/restore-drill.sh` (see backup-restore.md). Configure Prometheus + alerts from monitoring.md.

## Clean-install test
`scripts/clean-install-check.sh` builds from nothing with fresh volumes and throw-away secrets, waits for readiness, runs the smoke test, then tears everything down. Run it before each release candidate and record the result.

## Web and mobile
- Web: `cd web && npm ci && npm run build`; serve `dist/` from the proxy (or any static host) with `/api` routed to the API. The API itself sends `Cache-Control: no-store` and a strict CSP for API responses only.
- Android: `flutter build appbundle --dart-define=API_BASE=https://<domain>`; signing keys are held by the operational owner, not in the repo.
