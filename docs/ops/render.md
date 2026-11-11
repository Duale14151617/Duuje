# Deploying to Render (staging / pilot)

One Blueprint (`render.yaml`) creates a Docker web service (React dashboard + API + background worker in one process) and a private PostgreSQL database. The dashboard is served by the API from the same origin; the API is reached under `/api`, so there is no CORS to configure. Provider callbacks and health probes stay unprefixed (`/payments/provider-callback`, `/health/ready`).

## Deploy
1. Push this repository to GitHub/GitLab.
2. Render dashboard -> **New -> Blueprint**, pick the repo. Enter `Bootstrap__AdminEmail` and `Bootstrap__AdminPassword` when asked (long, unique password).
3. Wait for the build. The first build compiles the whole solution: **it has never been compiled before, so expect to fix compile errors shown in the build log.**
4. Open the service URL, sign in as the bootstrap admin, enable MFA (Security tab).

## Migrations (important)
No migrations are committed. On the **first** deploy the image build generates them from the compiled model with fixed ids (`scripts/render-migrations.sh`) and the app applies them at startup (`Database__AutoMigrate=true`).
**Before you change the model (new table/column) or after the first successful deploy, generate and commit real migrations:**
`scripts/make-migrations.sh` locally, commit `src/Duale.Api/Migrations/`. When that folder exists the build uses it and skips generation. If you change the model without committing migrations, the database will silently NOT get the change.

## What this setup is not
- **No virus scanning** (`Scanner__AllowNoop=true`). Do not upload real identity documents. Add ClamAV (a separate private service) and set `Scanner__ClamAv__Host`, then remove the override.
- **Single instance only**: uploads live on a persistent disk, which cannot be attached to several instances, and rate limits are per process. Move files to object storage (`IFileStore`) before scaling out.
- **Disk downtime**: a service with a disk restarts with brief downtime on deploy and has no zero-downtime deploys.
- **No email/SMS provider**: password recovery e-mails are not sent outside Development (see README).
- Backups: use Render's Postgres backups/point-in-time recovery on a paid plan, and run `scripts/restore-drill.sh` against a restored copy. Back up the disk separately (snapshots).
- Plan sizes/costs (starter web + basic-256mb database + 5 GB disk) are starting values; check current Render pricing and size for your data.
- `btree_gist` is required by the assignment-overlap constraint; the first deploy fails with a clear error if the database refuses it.

## Operations
Health: `/health/ready`. Metrics need `Metrics__Token` (generated; view it in the service's environment) and a scraper. Everything else is in the other `docs/ops/*.md` files; none of the business or legal decisions in `docs/production-readiness.md` are made by this deployment.
