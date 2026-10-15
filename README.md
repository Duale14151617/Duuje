# ARMY HQ — Version 2.0 (… + Institutional expansion)

Administrative web platform for Puntland's Army, Navy and Police (development specification,
**synthetic data only**). Stack: Django + DRF, PostgreSQL, React + TypeScript.
Not production-ready: see `docs/LIMITATIONS.md` and `docs/CHANGE_REPORT_v1.0.md`.

## Included in 1.0
- Login (session cookie + CSRF), lockout, throttling, TOTP MFA (mandatory for privileged roles),
  forced password change, session revocation (disable, role revoke, admin "sign out everywhere").
- Users, roles, permissions, scoped role assignments (subtree of the organization + optional service branch,
  validity dates). Deny by default; every check is server-side.
- Configurable organization: HQ → region → branch command → unit. Seeded: Bari, Karkaar, Nugaal, Mudug;
  Army, Navy, Police.
- Rank catalogue (service-specific, English/Somali, draft/approved), managed in the database. The Army list is the
  16 official Puntland Army ranks (Dable ... Sarreye Guud), stored as supplied with no invented translations.
- Organizational template for the Army: Taliska Guud (regional command), Qayb, Gaas, Guuto, Urur, Horin, Koox, Unug,
  with reference strengths (information only), approved strength exceptions, specialist designations (Sahan, Sanco) and
  expected-relationship checks, on the **Structure** page.
- Append-only audit log (model guard + PostgreSQL trigger), correlation IDs.
- Role-aware dashboard (real counts for scope/ranks/accounts/audit; clearly labelled synthetic demo figures).
- Somali/English UI, mobile-first (bottom nav on phones, sidebar on desktop).
- OpenAPI at `/api/v1/docs/` when `ENABLE_API_DOCS=1`.

## Added in 1.1 (Personnel)
- Personnel records: system ID, optional unique service number, name, phone, branch (derived from unit), unit,
  **approved** rank of the same branch, service status. Scoped on every list, detail, edit, search, history, import, export.
- Effective-dated history for rank, unit and status; transfer / change-rank / change-status workflows (no future-dated changes).
- Duplicate detection (service number hard-blocked; same name+phone/unit needs explicit confirmation).
- CSV import: preview (validated against *your* scope, no personal data echoed back) then commit (all-or-nothing, re-validated).
- CSV export: separate permission, **disabled unless `PERSONNEL_EXPORT_ENABLED=1`**, scoped, audited, formula-safe.
- Headquarters administrators get **no** personnel access by default; personnel permissions go to regional chiefs,
  branch/unit administrators, reporting users and read-only users within their scope.
- Personnel needs approved ranks: approve ranks (with Somali names) before adding people.

## Added in 1.2 (Requests, reports, approvals)
- Configurable request/report types (seeded: monthly administrative report with whitelisted numeric figures, transfer
  request, training request). HQ administrators can add types; types in use cannot change kind/figures.
- Workflow: draft → submitted → under review → approved / rejected / returned for correction; approved items can be
  amended and re-approved. Every submit creates an immutable revision; every step records actor, time, comment.
- Separation of duties per type (default on): nobody who submitted any revision can review it. Denials are audited.
- Identity, status, scope and approval state are never read from the client: actor = session, transitions only through
  action endpoints, scope enforced per item and per summary row, optimistic concurrency on every change.
- Summaries: approved content only, by region and consolidated, date/type/unit filters, limited to the caller's scope.
  A previously approved revision keeps counting while an amendment is pending.
- Notifications: submit/resubmit → reviewers in scope; review/decision → submitter. Private to the recipient and
  re-authorized when read (no title once scope is lost).
- Summary CSV export: own permission, **off unless `REPORT_EXPORT_ENABLED=1`**, scoped, audited, formula-safe.

## Added in 1.3 (Logistics and training)
- **Categories:** created by HQ administrators as drafts; usable only after *institutional review* by a separate
  `logistics_reviewer` (creator cannot approve; Somali name required; restricted categories need the stronger
  `logistics.restricted_approve`). Renaming an approved category sends it back for review.
- **Stock:** quantity lines per unit with an append-only ledger (receive / issue / adjust / transfer). Row-locked,
  never negative (also a database CHECK), optional `expected_balance` guard, reasons required for adjustments,
  transfers only into units you also manage.
- **Assets:** individually tracked items with unit-level issue/return, maintenance, missing/lost/retired, transfer, an
  accountable custodian (a user authorised for that unit) and a full event history.
- **Restricted equipment:** a separate permission (`logistics.restricted`) controls visibility *and* every action;
  restricted categories, items, reconciliations and summary rows are invisible to everyone else. The inventory has
  **no link to personnel records** (a test enforces this): items are accounted to units and custodians, never as a
  person-by-person assignment directory.
- **Reconciliation:** one open count per unit; variances become audited adjustments against the *current* balance;
  items not found become "missing", found ones are restored. Restricted lines only in restricted reconciliations.
- **Training:** HQ-managed course catalogue (English/Somali); records tied to personnel with a strict status flow
  (enrolled → in progress → completed/failed, or withdrawn), completion dates validated. Training staff pick people
  through a minimal roster (name + unit only) and get **no** general personnel access.
- **Summaries:** logistics (by category and region; stock totals, below-reorder, assets by status) and training
  (by course and region and status), both limited to the caller's scope.

## Added in 1.4 (Hardening: no new product features)
- Fixes found in review: rate-limit bypass through a spoofed `X-Forwarded-For`, TOTP code replay, no absolute session
  lifetime, admin-chosen recovery passwords (now one-time codes), timing difference for locked accounts, unprotected
  history tables (now PostgreSQL triggers), unaudited audit reads, unbounded request size, missing headers.
- Guard rails: `manage.py check --deploy` rules, secret redaction in logs, health endpoints, bulk-operation rate limit,
  retention job for CSV import data, `security_report` for alerting.
- Evidence: deny-by-default sweep over every route, cross-region canary matrix across all modules, CSRF/CORS/session/MFA/
  recovery tests, migration safety and query-count tests, PostgreSQL concurrency test.
- Operations: `docs/SECURITY.md` (findings, residual risks, items for independent review), `docs/RUNBOOK.md` (backup,
  restore, monitoring, incident response, rollback), `docs/TEST_PLAN_1.4.md`, `ops/` scripts, `deploy/` proxy template,
  `backend/Dockerfile`, CI workflow, accessibility/layout end-to-end scaffolding.

**Not production-ready.** Nothing in 1.4 has been executed by the author; the restore test, accessibility, Android,
performance and independent security review are still to be done (see the test plan). No security certification is claimed.

Not yet (by design): integrations/offline (2.0, only after institutional approval), tactical features.

See `docs/SETUP.md` to run it and `docs/DEPLOY_ROLLBACK.md` for migrations and rollback.

## Added in 2.0 (Institutional expansion; additive, 1.x contracts unchanged)
- **Analytics** (`/api/v1/analytics/`, page *Analytics*): aggregate personnel, reports, logistics and training figures with date and region filters. Needs `analytics.view` plus the section's existing permission; limited to the caller's scope; read-only; restricted equipment excluded.
- **Integration API** (`/api/v1/ext/`, admin at `/api/v1/integrations/clients/`, page *Integrations*): scoped, expiring, revocable bearer keys that read aggregate analytics only; small cells withheld; per-key rate limit; full call log. **Off unless `INTEGRATIONS_ENABLED=1`.** See `docs/INTEGRATIONS.md`.
- **Governed structure changes** (`/api/v1/organization/structure-changes/`, page *Structure changes*): levels (names, order, parents, strength standards) change only by proposal + approval by a different person (role *Structure approver*); direct edits refused by default (`STRUCTURE_CHANGES_REQUIRE_APPROVAL`). See `docs/STRUCTURE_APPROVAL.md`.
- **Unit tree** (`/api/v1/organization/units/tree/`, page *Unit tree*): scoped nested view of the organization.
- Not built: configurable top-level categories, outbound integrations, offline access (`docs/OFFLINE_DECISION.md`).
- Docs: `IMPACT_ASSESSMENT_v2.0.md`, `MIGRATION_PLAN_v2.0.md`, `SECURITY_REVIEW_v2.0.md`, `COMPATIBILITY_v2.0.md`, `CHANGE_REPORT_v2.0.0.md`.
- Upgrade: `migrate` then `seed_reference_data` (see `docs/MIGRATION_PLAN_v2.0.md`).


## Frontend on Netlify (2.1.2, no backend)
`cd frontend && npm run build:demo` builds a standalone demo with built-in sample data (no backend); `API_ORIGIN=https://your-backend npm run build:netlify`
builds against a real backend. Deploy `frontend/dist`, or connect the repo with Base directory `frontend`. See `docs/NETLIFY.md`.
