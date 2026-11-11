# Duale BuildLink — Phases 1-6

ASP.NET Core 8 + EF Core + PostgreSQL modular-monolith backend, following the spec's proposed stack.

## Layout
- `src/Duale.Api` ASP.NET Core 8 API (modular monolith) · `tests/Duale.Api.Tests` xUnit
- `web/` React + TypeScript company dashboard and platform admin ([web/README.md](web/README.md))
- `mobile/` Flutter technician app, Android first ([mobile/README.md](mobile/README.md))
- `scripts/` migration generation · `docs/` spec PDF and SQL reference

## Run the API
```
cp .env.example .env              # fill in secrets, including Mfa__Key (openssl rand -base64 32)
dotnet tool install -g dotnet-ef
scripts/make-migrations.sh        # Windows: scripts\make-migrations.ps1   (creates src/Duale.Api/Migrations)
docker compose up -d db
dotnet test                       # tenant isolation, documents, MFA and recovery tests (SQLite in memory)
docker compose up --build api     # Database__AutoMigrate=true applies migrations at startup
```
`Bootstrap__*` creates the first platform admin. **Migrations are not included in this drop**: the environment that produced it had
no .NET SDK, and an EF migration plus its model snapshot must be generated from the compiled model, so a hand-written one would
drift. The script runs `dotnet ef migrations add Initial` and then adds a second migration, `PostgresConstraints`, that applies the
PostgreSQL-only overlap constraint (`src/Duale.Api/Data/PostgresConstraints.cs`). Commit the generated `Migrations/` folder.

## Included
- Auth: register, login (JWT, 30 min), log out everywhere (token-version revocation), suspended users rejected, auth rate limiting.
- Company onboarding: create (creator becomes owner) -> review queue -> approve / reject / request info -> owner resubmits. Reviewers cannot decide on their own company.
- RBAC: roles, permissions, role_permissions, memberships, platform role assignments. Permissions are read from the DB on every request; non-members get 404, members lacking a permission get 403.
- Staff: add/remove members (company roles only, company must be approved, last owner protected).
- Trade/skill catalog (trade names seeded from the spec); technician profile, skill claims, platform verification with expiry.
- Append-only audit events written in the same transaction as each change; no cascade deletes.

## Added in this drop
- **Branches:** create, edit, close/reopen (never deleted), assign staff. Company id is part of every lookup; foreign branch or membership ids are rejected. New permission `branch.manage` (owner).
- **Service areas:** platform-managed list; technicians choose theirs; a service location may carry an area, and matching blocks technicians who do not serve it (with the reason shown).
- **Technician documents:** multipart upload (kind identity/qualification/other), 5 MB limit, content type taken from the file's bytes (PDF/JPEG/PNG only), random storage key, SHA-256 recorded, stored outside the web root. Reads only through a signed link valid 120 s, bound to the document and the user it was issued to, and re-authorized at read time (owner or `technician.verify`). Reviewers decide approve/reject/request-info with a note; nobody reviews their own documents. Views and decisions are audited. A skill review queue is at `GET /platform/technician-skills`.
- **MFA (TOTP, RFC 6238):** setup, enable (returns 10 single-use recovery codes, stored hashed), disable (password + code, signs out everywhere). Login returns a 5-minute `mfaToken` with a different audience, so it cannot act as an access token. Codes cannot be replayed; 5 failures lock the factor for 15 minutes. Secrets are AES-GCM encrypted with `Mfa__Key`.
- **Account recovery:** `POST /auth/recovery/request` always answers 204; reset tokens are random, stored hashed, single-use, 30 minutes; a reset ends all sessions and still requires the second factor when MFA is on. Lost device and codes: a user with `user.support` resets MFA for someone else (never themselves); the user is notified and signed out.
- `GET /me` for the UIs. **React web** and **Flutter app** as above.

## Before production (still open)
- **Recovery delivery is not wired.** No email/SMS provider is chosen, so in non-development environments nothing is sent (logged as an error). Implement `IRecoveryDelivery` once the provider is selected. In Development the token is written to the log.
- **Upload scanning is a no-op** (`NoopUploadScanner`); plug in a real scanner (e.g. ClamAV) before accepting real identity documents. Files are on a local volume; move to private object storage with the same `IFileStore` interface.
- MFA is optional for everyone; decide which roles (platform staff at least) must use it.
- Branch membership is recorded but not yet used to restrict what branch staff can see, and jobs have no branch yet. That needs a business rule for "no branch = company-wide?".
- Not compiled or run anywhere yet (no .NET, Flutter or network access in the build environment): expect small fixes on first `dotnet build`, `npm run build`, `flutter analyze`.
- Phases 3-6 are below.

## Business decisions still needed (not invented here)
Business categories and company verification evidence, role-to-permission assignments (a starting point is in `Data/Seed.cs`), trade qualifications, launch city, hosting and identity provider.

---

## Phase 2 — Relationships and dispatch (added)
- **Relationships:** company invites a technician (must have a verified skill), technician accepts or declines; Employed or Independent; company can suspend, reactivate or end; both sides are blocked from ending while offers/jobs are open.
- **Availability:** technicians publish non-overlapping windows (max 31 days each).
- **Customers and service locations:** company-scoped; foreign customer/location ids are rejected.
- **Jobs:** unique reference, required skills (must belong to the trade), schedule, priority, status history, cancel, reschedule (withdraws any live offer and re-opens the job).
- **Matching:** `GET .../jobs/{id}/candidates` filters on active relationship valid for the time, verified and unexpired skills, availability covering the window, and no overlapping confirmed job. It ranks with configurable weights (`Matching:EmployedBonus`, `Matching:SameDayJobPenalty`) and explains every score or blocker. **Recommending never assigns.**
- **Dispatch:** explicit `offer` by staff with `job.dispatch`, technician `respond` (accept re-checks eligibility inside a serializable transaction), `withdraw`, `reassign` (old assignment kept as `Reassigned`). One live assignment per job is enforced by a filtered unique index.
- **Job state machine:** full spec state list in `JobRules`; all changes go through `JobFlow.Move`.
- **In-app notifications** (`/notifications`) written in the same transaction as the event.

### Before production
- Apply `docs/postgres-constraints.sql` in the first migration (overlap exclusion constraint).
- Ranking ignores service areas (not modelled yet) and acceptance history; the weights are placeholders, not validated business rules.
- Notifications are in-app rows only; the persistent delivery queue and provider integrations are Phase 5.

---

## Phase 3 — Execution and quality (added)
- **Technician field workflow:** Accepted -> EnRoute -> Arrived -> InProgress, each recorded in the job's status history (device time kept in the reason). Skipping steps is refused by the state machine.
- **Minimum necessary customer data:** the customer's name, phone, address and access notes are returned only to the technician whose assignment is *Accepted* and only while the job is in the field; never before acceptance, never to other technicians.
- **Evidence:** multipart upload (before / progress / after / other), PDF/JPEG/PNG sniffed from the bytes, 5 MB, random storage key, SHA-256, scanner hook, 40 per job. Reads only via a 120 s signed link bound to the evidence and the user, re-authorized at read time (own technician, or company staff with `job.read`). Views are audited.
- **Work reports** are versioned. Submitting needs `Jobs:MinEvidence` (default 1) new evidence items since the last return. **Scope changes** are reported on site and decided by a reviewer; a pending one blocks approval.
- **Supervisor review** (`job.review`: supervisor, owner): approve -> Completed (stamps `CompletedAt` and warranty end), or return with a required note -> ReturnedForCorrection. Nobody can review their own work.
- **Complaints** (raise, resolve) and **callbacks**: a callback is a new Open job linked to the completed one, recording rework responsibility and whether it was under warranty. Warranty length is set per job (`warrantyDays`) because the terms are a business decision.
- **Idempotency:** status, evidence, scope-change and report requests honour an `Idempotency-Key` header; the first result is stored in the same transaction, so a retry after a dropped connection replays it instead of repeating it.
- **Clients:** Flutter `JobDetailScreen` (status steps, evidence, scope change, report) and a web **Review** tab for supervisors.

### Open for Phase 3
- Financial follow-up after completion (`PHASE4-HOOK` in the review endpoint) arrives in Phase 4.
- Offline queueing on the phone (store-and-forward with the same idempotency keys) is part of Phase 6.

---

## Phase 4 — Finance (added)
**Money model.** `NUMERIC(19,4)` / `decimal` everywhere, positive, at most 4 decimals; every record carries its currency and currencies are never mixed
(a payment in another currency than its invoice/payable is refused; reports are one block per currency). Allowed currencies and methods are configuration, not code.

- **Financial terms** per job (`/companies/{id}/jobs/{jobId}/financial-terms`): versioned, proposed by `finance.terms` (dispatcher, owner), approved by `finance.terms.approve` (owner).
  Approver must differ from proposer unless the amount is within `Finance:SelfApprovalLimit` (default 0). One approved version per job (unique index); once obligations exist, terms cannot change.
  Each terms row says who pays the technician: `company` or `customer` (direct). Platform fee is an amount on the terms; the revenue model that produces it is **not** decided here.
- **Completion starts the finance workflow, separately from the approval.** When a supervisor approves work (or terms are approved after completion) the system creates the technician payable
  (company-paid: `Accrued` until finance approves it; direct: `Approved`, tracked only) and a platform-fee record. Missing terms never block completion; finance is notified instead.
- **Invoices** (`finance.invoice`): from a completed job with approved terms; lines must sum to the approved customer charge; one live invoice per job; void (owner) reverses the ledger and never deletes.
- **Payments:** initiate -> confirm -> reconcile, three steps, and the person cannot be the same at consecutive steps (initiator != confirmer, confirmer != reconciler; reversal != confirmer).
  Cash needs the acknowledging party; other methods need a provider/bank reference. Manual confirmation is stored as `verified=false`; only a signed provider callback sets `verified=true`.
  Over-payment is refused (initiated + confirmed <= amount due); the same provider reference cannot be posted twice (unique index); concurrent changes to one invoice/payable/refund are serialised by a concurrency token.
  Failed, reversed and refunded money is kept and reported separately; every step is appended to `PaymentEvents`.
- **Provider callback** `POST /payments/provider-callback` (anonymous, HMAC-SHA256 of the raw body in `X-Signature`, secret `Finance:CallbackSecret`). Provider-neutral: the body carries our payment `reference`.
  Duplicates answer 200 without posting again; amount/currency mismatches are refused and logged for review. No provider is selected, so this is an interface, not an integration.
- **Direct customer-to-technician payments:** the technician records what they received (`/technicians/me/payables/{id}/acknowledge`, idempotent). It is *self-reported* until company finance reconciles it, and it never touches the company ledger.
- **Refunds:** requested (`finance.refund.request`), decided by someone else (`finance.refund.approve`), paid through the normal payment flow; total refunds cannot exceed what was collected.
- **Disputes:** technician or finance raises; an open dispute blocks payout; decided by someone else with a written resolution. Any adjustment is posted separately (refund/reversal) and referenced in the resolution.
- **Ledger:** double-entry, immutable (`LedgerEntries`), unique `LineKey` so a posting cannot be made twice, reversals instead of edits. Accounts: 1000 cash, 1100 receivable, 2100 technician payable, 2200 platform fees payable,
  4000 revenue, 4900 refunds, 5000 technician expense, 5100 platform fee expense. `GET .../finance/reconciliation` shows unreconciled and self-reported payments, stuck payments and the trial balance.
- **Platform finance** (`platform_finance` role): list fees, mark settled or waived (note required to waive).
- **Database backstops** (in the `PostgresConstraints` migration): positive-amount checks, one-sided ledger lines, append-only triggers on ledger/payment events/audit, and a deferred trigger that rejects an unbalanced posting.
- New roles/permissions are in `Data/Seed.cs` (company_finance can invoice, pay, reconcile and request refunds; owner holds the approval powers). **Confirm these with the business.**

## Phase 5 — Reporting and notifications (added)
- **Reports** (`since`/`until` query params, default last 30 days; always scoped to the company in the URL): `reports/jobs` (volume, status, cancellations, acceptance, duration, complaints, callbacks),
  `reports/technicians` (offers, acceptance, completions, scheduled vs available hours = utilization), `reports/finance` (per currency: receivables, payables, direct payments, refunds, disputed, platform fees,
  payments by status, unreconciled, and the ids of the source records behind each figure). Job/technician reports need `report.read`; finance needs `finance.read`.
  Reports aggregate in memory (decimal-safe on every database) and cap at 20,000 rows per source, flagged as `truncated`; move heavy reporting to SQL views/read replicas in Phase 6.
- **Persistent delivery queue.** The in-app notification is the event (committed with the change). A worker fans it out to `NotificationDeliveries` for channels the user enabled, sends through `INotificationProvider`,
  retries with exponential backoff, and marks a delivery `Dead` after `Notifications:MaxAttempts` (or at once if the recipient has no address). Providers must treat `DeliveryId` as an idempotency key (the worker is at-least-once).
  **No email/SMS provider is registered** (not chosen yet); enabling a channel without one returns 409. Register providers in `Program.cs`.
- **Reminders** (deduplicated by key, safe to run on several instances): job starting soon, qualification expiring, review overdue, approved payable unpaid.
- **Platform oversight:** `GET /platform/overview` (companies, verification queues, jobs, notification queue health, open disputes) and delivery list/retry (no message bodies exposed). Needs `platform.oversight`.
- **Clients:** web Finance and Reports tabs, notification preferences; Flutter Earnings tab (own payables, "I received money", report a problem).

## Not verified / still open after Phases 4-5
- **Nothing here was compiled or run** (no .NET SDK, Flutter or npm network in the build environment). Expect small fixes on first `dotnet build` / `dotnet test`. The new tests (`Phase4Tests`, `Phase5Tests`) are written but have not passed.
- Concurrency is protected by concurrency tokens and unique indexes, but there is **no concurrent-request test**; the SQLite test harness shares one connection. Add a PostgreSQL integration test (Testcontainers) in Phase 6.
- Decisions not invented: compensation model, platform revenue model (subscriptions are **not** built), supported payment providers, refund/dispute/cancellation policy, retention. Currencies/methods/limits are configuration placeholders.
- Cancelling a job with an existing payable, cancellation charges and scope-change repricing are not modelled; use refund/reversal/dispute for now.
- Payable cancellation, partial-refund-after-void and multi-invoice jobs are out of scope. Branch-scoped finance visibility is not implemented (same open question as jobs).
- No migrations are included; re-run `scripts/make-migrations.sh` (the model changed). Phase 6: security review, load tests, backups, monitoring, clean-install test, offline queue on the phone.

---

## Phase 6 — Hardening (added)
**Read [docs/production-readiness.md](docs/production-readiness.md) first: it says plainly what is built, what is verified (almost nothing yet), and which business decisions block launch.**

- **API hardening:** security headers and `X-Correlation-Id` on every response, no server banner, request-size cap, HSTS in production, per-user/IP global rate limit (`RateLimit__ApiPerMinute`) on top of the auth limit, trusted-proxy mode (`Security__TrustProxy`) for correct client addresses behind TLS termination.
- **Configurable MFA requirement:** `Security__MfaRequiredPermissions` lists permissions (company or platform) that need a second factor. Which roles must use MFA is a business decision, so nothing is forced by default.
- **Upload scanning:** ClamAV client (INSTREAM, fail-closed). Production **refuses to start** without `Scanner__ClamAv__Host` unless `Scanner__AllowNoop=true`. Note: the plain `docker-compose.yml` runs in Production mode too, so set `Scanner__AllowNoop=true` there for local trials.
- **Operability:** `/health/live`, `/health/ready` (database, pending migrations, file storage), token-protected Prometheus `/metrics` (request rate/errors/latency plus queue, payment, dispute and verification gauges), `GET /platform/integrity` (ledger balance, postings for confirmed/reversed payments, invoice lines, over-payment, single live assignment, history).
- **Retention:** idempotency records older than `Retention__IdempotencyDays` (default 14, longer than a phone should stay offline) are purged hourly by the worker. All other retention periods are undecided and nothing else is deleted.
- **Offline phone queue (Flutter):** status, scope-change, report and evidence actions are stored on the phone when there is no connection and sent in order with their original idempotency keys on app start, resume, a 30 s timer or "Send now". Network/5xx failures keep the action; a refusal (4xx) moves it to a visible "not accepted" list instead of blocking the queue. Not run on a device yet.
- **Ops kit:** `docker-compose.prod.yml` (Caddy TLS proxy, unprivileged read-only API, Postgres, ClamAV), unprivileged `Dockerfile` with healthcheck, CI (`.github/workflows/ci.yml`: build, tests, vulnerable packages, secret scan, migrations on empty PostgreSQL, web build/audit, Flutter analyze/test, image scan), `scripts/backup.sh`, `scripts/restore-drill.sh`, `scripts/smoke.sh`, `scripts/clean-install-check.sh`, `ops/loadtest/k6-smoke.js`.
- **Documentation:** `docs/ops/` — deployment, backup-restore, monitoring/alerts, incident-response, operations-runbook (permission administration, verification, payment reconciliation, failed notifications, disputes, data requests), release (CI/CD, migrations, rollback vs forward-fix), pilot-uat, security (controls ↔ tests, known gaps), restore-drills log; `docs/permission-matrix.md` generated from `Seed.cs`.
- **Tests (`Phase6Tests`):** security headers; readiness; metrics hidden without token; rate limiting; MFA-required permissions; cross-company id substitution sweep incl. evidence links; role escalation; malicious uploads and scanner rejection; audit/ledger/payment-event immutability; idempotency purge; replay of queued requests; 250-message backlog through a provider outage; integrity check clean vs tampered.

### Still open after Phase 6 (honest list)
Nothing has been compiled or run · no restore drill, load test, clean install, pen test or pilot has happened · no PostgreSQL concurrency/constraint tests (SQLite harness) · PITR/WAL archiving depends on hosting · identity provider, object storage and email/SMS/payment providers not selected · audit rows are not hash-chained · retention, MFA-role, privacy/legal and all business decisions listed in the readiness report.

---

## Phase 7 — Remaining spec items (added)
Closes the gaps between the spec's minimum schema/workflows and Phase 6. **Not compiled or run** (same limitation as every earlier drop: no .NET SDK in the build environment).

- **Outbox (`OutboxEvents`).** Spec: "use an outbox pattern for reliable event delivery". `Outbox.Add` writes the event in the same transaction as the change. Wired to `job.offered`, `job.approved`/`job.returned`, `finance.payment_confirmed`, `finance.payable_cancelled` and the subscription events. `OutboxDispatcher` (run by the maintenance worker) sends to every registered `IOutboxPublisher`, retries with exponential backoff (cap 1 h), and marks an event `Dead` after `Outbox:MaxAttempts` (default 8). **No publisher is registered** (consumers are not chosen), so events stay `Pending` and are visible in `/platform/overview`, `/platform/outbox` (no payloads) and the `duale_outbox_*` metrics. Delivery is at-least-once: consumers de-duplicate on the event id. Payloads carry ids and amounts only, never customer data.
- **Payable cancellation.** `POST /companies/{id}/payables/{pid}/cancel` (`finance.adjust`, reason required). Refused while a payment is initiated or confirmed (fail/reverse it first) or a dispute is open. An approved company-paid accrual is reversed in the ledger (`payable-cancel:{id}`); nothing is deleted; the technician is notified. The platform-fee record for the job is **not** touched (decide fee policy first). Cancelling does not create a replacement payable: accrual only runs at job approval / terms approval.
- **Platform subscriptions (`PlatformSubscriptions`).** Platform finance records a subscription (plan label, amount, currency, inclusive period) per company, cancels with a reason, and the company owner/staff can read their own (`GET /companies/{id}/subscription`). Overlapping active periods are refused in the app and by a PostgreSQL exclusion constraint. **No billing, pricing or enforcement**: the revenue model is a business decision and nothing in the system is gated by a subscription.
- **Integration accounts (`IntegrationAccounts`).** `platform_admin` registers provider metadata (kind, provider, display name, `SecretRef`). `SecretRef` is validated as a secret *name*; values never enter the database. Enabling an account does not add provider code; register a provider in `Program.cs`.
- **Fixed a compile error in the Phase 6 drop:** `ReasonReq` was declared in both `Phase2Endpoints.cs` and `Phase4Endpoints.cs`.
- New permission `integration.manage` (platform_admin). Tests: `Phase7Tests`.

### Deliberate deviations from the spec's minimum schema
- `file_metadata`: file metadata (type, size, SHA-256, storage key, reviewer) lives on `TechnicianDocuments` and `JobEvidence` rather than in one shared table; the access rules differ per owner, so a shared table would add joins without adding control.
- `financial_allocations`: each payment targets exactly one invoice, payable or refund (`PaymentRecords`), so allocation is the payment's own foreign key. Split payments across several invoices are out of scope (one invoice per job).

### Still open after Phase 7
Migrations are still not included (run `scripts/make-migrations.sh`; it will pick up the three new tables) · PostgreSQL concurrency/constraint tests (Testcontainers) not written · `jobs.BranchId` and branch-scoped visibility need the "no branch = company-wide?" decision · audit rows are not hash-chained · web UI for subscriptions, integrations and the outbox is not built (API only) · everything in the readiness report's decision list.

---

## Render deployment (added)
`render.yaml` + `Dockerfile.render` deploy the dashboard and API as one service with a private PostgreSQL database. See [docs/ops/render.md](docs/ops/render.md) for the steps and the limits (staging/pilot shape, no virus scanner, single instance, migrations must be committed after the first deploy). Not run on Render by the authors.
