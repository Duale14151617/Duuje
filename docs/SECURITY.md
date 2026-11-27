# Security review notes (Version 1.4)

**This is a developer-led hardening review, not an independent assessment. No security certification, penetration
test or accreditation is claimed.** Nothing here has been executed against a running system by the author: the
automated tests described below were written but not run (see `CHANGE_REPORT_v1.4.0.md`). Real data requires written
institutional approval and an independent review first.

## Findings and what was changed in 1.4

| # | Finding | Severity (author's view) | Change |
|---|---|---|---|
| 1 | DRF trusts a client-supplied `X-Forwarded-For` when `NUM_PROXIES` is unset, so an attacker could rotate it to evade login and reset throttles. | High | `NUM_PROXIES` is 0 unless `TRUST_PROXY_HEADERS=1`, then the configured proxy count. Test: spoofed header cannot dodge the limit. |
| 2 | A valid TOTP code could be replayed inside its validity window. | Medium | Each accepted time-step is burned (`mfa_last_step`, atomic conditional update). Older steps are refused. Enrolment codes are burned too. |
| 3 | Sessions had only an idle timeout. | Medium | Absolute lifetime (`SESSION_ABSOLUTE_SECONDS`, default 12 h). Sessions without a login timestamp are rejected (fail closed). |
| 4 | Password recovery meant an administrator choosing and seeing a password. | Medium | One-time recovery codes: 40 bits, 60 minutes, single use, stored hashed, superseded by newer codes, rate-limited, identical errors for every failure, never bypass MFA, revoke all sessions. |
| 5 | Locked accounts answered faster than unlocked ones (timing oracle). | Low | A dummy password hash is computed on the locked path. |
| 6 | History and ledger tables were append-only only in application code. | Medium | PostgreSQL triggers block UPDATE/DELETE on `audit_events`, `stock_transactions`, `asset_events`, `personnel_history`, `approval_actions`, `submission_revisions`. Application guards extended to the same models. |
| 7 | Reading the audit log was not itself audited. | Low | `audit.read` events with the filters used. |
| 8 | No request-size cap; API responses cacheable; no security headers on API responses. | Low | 413 above `MAX_REQUEST_BYTES`; `Cache-Control: no-store`, CSP `default-src 'none'`, Permissions-Policy, CORP. Proxy template adds HSTS and a SPA CSP. |
| 9 | CSV import could raise unhandled parser errors; imports/exports were only throttled globally. | Low | Parser errors become a 400; imports/exports use a separate `bulk` rate limit (default 30/hour). |
| 10 | Secrets could be interpolated into logs by mistake. | Low | Redacting log filter (passwords, OTPs, tokens, cookies, Authorization headers). |
| 11 | Unsafe production settings were possible. | Medium | `manage.py check --deploy` now fails on DEBUG, weak or default secret keys, invalid encryption key, wildcard hosts, non-HTTPS CSRF origins, SQLite, insecure cookies; warns on exports enabled, API docs enabled, weak DB TLS mode. Fails CI. |
| 12 | Cookies could be set by sibling subdomains. | Low | `__Host-` cookie names in production. |
| 13 | No liveness/readiness endpoints for monitoring. | n/a | `/api/v1/health/live/` and `/ready/` (booleans only). |
| 14 | A shared test helper gave every test user MFA, so earlier tests that sign in with a password alone as a non-privileged user would have failed on first run. | Test defect | MFA now defaults to on only for privileged roles. |

## Controls verified by automated tests (written, not yet run)
Authorization before validation on every route (unauthenticated and no-role sweeps); every viewset has an explicit
permission rule for every action and no stale rules; no PUT/DELETE exposure; a canary record per module in another
region that eight Bari roles cannot see through any list, search, summary, export, detail or mutation route; CSRF on
every state-changing endpoint; no CORS headers; unknown Host rejected; error bodies without internals; session
fixation, logout, absolute lifetime; account disable, role revoke/grant/expiry, MFA reset and password change take
effect on live sessions; privileged roles confined until MFA is enrolled; query counts independent of page size;
page-size cap; migrations match models, are non-destructive and reversible; real parallel stock requests on PostgreSQL.

## Residual risks (known, not fixed)
1. **Administrator self-grant.** A headquarters administrator has no data access by default but can assign
   themselves a role that has it. The assignment is audited and `role_assignment.create` should alert, but there is no
   second-person approval. Recommend a two-person rule before real use.
2. No step-up (fresh MFA) for sensitive administrative actions.
3. Recovery codes rely on an out-of-band channel chosen by the institution; no email/SMS is built in.
4. Database least privilege and TLS are *documented* (`docs/DEPLOY_ROLLBACK.md`), not enforced by the application.
   A database superuser can drop the triggers; there is no cryptographic hash chain over the audit log.
5. Only MFA secrets are encrypted by the application. Encryption at rest for the database and disks is a hosting decision.
6. Rate limits are per client address; there is no WAF or DDoS protection.
7. Dependencies are version-ranged, not hash-pinned; `pip-audit`/`npm audit` run in CI but results have not been seen.
8. Log shipping, retention and access control for logs are not configured.
9. TOTP and audit timestamps depend on correct server time (NTP).
10. Accessibility, Android layouts and Somali text have **not** been tested by people (scaffolding only).
11. Backups and restores have **not** been tested; performance and load have **not** been measured.

## Items that need independent review
- Authorization model and scope engine (`apps/accounts/scope.py`, `permissions.py`) and every `permission_map`.
- Session, CSRF, MFA and recovery flows (`apps/accounts/views.py`, `security.py`, `middleware.py`).
- Concurrency and transaction handling in logistics and workflows under real load on PostgreSQL.
- Deployment: reverse proxy, TLS, headers, database roles, secret storage, backup custody, monitoring.
- Data classification, retention, correction and deletion policies for personnel data.
- Penetration test of a staging environment seeded with synthetic data.

Version 2.0 additions are reviewed separately in `docs/SECURITY_REVIEW_v2.0.md`.

## Break-glass override (payroll and payments)

The "must be a different person" rules (profile, run, payment, arrears, survivor and pay-decision approvals) can be skipped for ONE action
by a user holding `system.full_access` (super administrator), and only with a written reason of at least 15 characters (header
`X-Override-Reason`; the screen asks for it after a rule refuses the action). Every use is written to the audit log as
`breakglass.override` with the check that was skipped and the reason. Nothing else is overridden: state, amounts and permissions still apply.

Switch it off with `ARMYHQ_BREAK_GLASS=0` (default: on). Review the `breakglass.override` events after any emergency use.
