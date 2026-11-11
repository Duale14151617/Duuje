# Production readiness report

Honest status against the release gate in the specification. "Built" means code and tests exist in this repository; **nothing has been compiled or executed by the authors of this drop** (no .NET/Flutter/npm toolchain was available). A gate item is only "done" once it has passed in CI/staging and, where stated, pilot users approved it.

| Release gate item | Built | Verified | Evidence / what is missing |
|---|---|---|---|
| Company and technician onboarding pass end-to-end tests | yes | **no** | Foundation/Phase tests written; must run green in CI |
| Both relationship models + company-confirmed recommendations | yes | no | Phase2Tests |
| Concurrent dispatch cannot create conflicting confirmed assignments | yes | **no** | SQLite tests cover logic; the PostgreSQL exclusion constraint and a real concurrent test (Testcontainers) are needed |
| Status transitions and assignment histories enforced | yes | no | Phase2/3Tests |
| Both financial workflows reconcile; duplicate payments prevented | yes | no | Phase4Tests; add a concurrent double-submit test on PostgreSQL |
| Tenant isolation, document protection, audit trails, permission boundaries tested | yes | no | Phase1–6 tests |
| Backup restoration tested | scripts | **no** | run `restore-drill.sh`, log in docs/ops/restore-drills.md; configure PITR |
| Monitoring | yes | no | metrics + alerts documented; Prometheus/alerting not deployed |
| Security scans | CI config | **no** | first CI run; external pen test not done |
| Mobile layouts / unstable connectivity | yes | **no** | offline queue implemented; needs device testing on throttled networks |
| Deployment/recovery documentation | yes | review | docs/ops/*; clean-install test not yet run |
| Pilot users approve the workflow | — | **no** | docs/ops/pilot-uat.md |
| Release-blocking defects resolved; legal/provider decisions documented | — | **no** | list below |

## Decisions the business must make before launch (not invented)
Launch city/radius · company eligibility evidence · trade qualifications · relationship/suspension terms · compensation model · platform revenue model (subscription *records* exist, but no billing or enforcement) · payment methods/providers (callback is provider-neutral; no integration exists) · customer communication/consent policy · cancellation, warranty, callback, dispute policies · hosting, domain, operational owner, **retention periods** · technology choices still open (identity provider, object storage, email/SMS provider) · which roles must use MFA · legal, privacy, tax, employment and payment-service requirements. **No compliance is claimed.**

## Known functional limitations
Cancelling a job after payment obligations exist, cancellation charges and repricing after scope changes are not modelled (use refund/reversal/dispute) · one invoice per job · cancelling a payable never touches the job's platform-fee record · branch-scoped visibility not implemented · reports aggregate in memory (20,000 rows per source) · payables list does a query per row (fine for pilot scale; replace with a join/view before large tenants) · the web dashboard is functional, not polished, and has no automated UI tests · no customer portal (by design for release 1).

## Performance
Targets (p95 < 500 ms, 99.5% availability) are **unmeasured**. Use `ops/loadtest/k6-smoke.js` on staging with production-sized data; index review against real query plans is pending.

## Added in Phase 7
Outbox table + dispatcher (no consumer registered), payable cancellation, subscription records, integration account metadata. Also fixed a duplicate `ReasonReq` declaration that would have broken the first build. **None of this has been compiled or run**; `Phase7Tests` are written but have not passed. A static scan for other duplicate type names found none, which is not a substitute for a compiler.
