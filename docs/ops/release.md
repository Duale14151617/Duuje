# Release process

Pipeline (`.github/workflows/ci.yml`): build → unit/integration/security tests → vulnerable-package scan (`dotnet list package --vulnerable`, `npm audit`) → secret scan → migrations applied to an empty PostgreSQL → web build → Flutter analyze/test → container build + Trivy. A red job blocks release.

1. Tag a release candidate. Deploy to **staging** with a copy of production-shaped data (anonymised).
2. Staging checks: `scripts/smoke.sh`, `scripts/clean-install-check.sh` (on a CI runner), k6 (`ops/loadtest/k6-smoke.js`), UAT scripts (pilot-uat.md) for any changed workflow.
3. Approve for production (named approver). Take a backup immediately before. Apply migrations, deploy, run smoke, watch metrics for 30 minutes.

## Migrations
Prefer backward-compatible, two-step changes (add nullable column/table → deploy code → backfill → later tighten/remove). Never edit a migration that has run anywhere. Destructive steps need a verified backup and an explicit approval.

## Rollback vs forward-fix
- Code only (no migration, or a backward-compatible one): redeploy the previous image tag.
- Migration already applied and old code still works with the new schema: redeploy previous image, leave schema.
- Migration not compatible with old code: **forward-fix** with a new release; restoring from backup is the last resort and loses data written since (see backup-restore.md).
- Finance data is never rolled back by deleting rows; correct with reversals.
