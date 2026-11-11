# Incident response

**Severity.** SEV1: data exposure, wrong money moved, outage of sign-in or payments. SEV2: a feature is down or degraded, backlog growing. SEV3: cosmetic or single-user.

1. **Detect & declare** (alert, user report, integrity failure). Name an incident lead and a scribe; open a timeline (UTC). Keep the correlation ids.
2. **Contain.** Suspected account compromise: suspend the user (`account status`), "log out everywhere" bumps the token version and kills sessions immediately. Suspected key leak: rotate `Jwt__Key` (everyone signs in again), `Finance__CallbackSecret` (tell the provider), `Metrics__Token`, DB password; rotating `Mfa__Key` requires re-enrolment of all MFA users (existing secrets become unreadable). Payment anomaly: set `Finance__Methods` to exclude the method and redeploy, or fail the initiated payments.
3. **Preserve evidence.** Do not edit data. Audit events and ledger entries are append-only (application and, on PostgreSQL, triggers). Export the relevant `AuditEvents` by `CorrelationId`/company/time range before any restore.
4. **Assess** with `GET /platform/integrity`, the finance reconciliation view and the provider's reports.
5. **Recover** (restart, roll back, or restore per backup-restore.md). Corrections to money are reversal/adjustment entries, never edits.
6. **Notify.** Personal-data breach: involve the legal/privacy owner immediately; notification duties and deadlines depend on the jurisdiction and are **not decided here**. Tell affected companies/technicians what happened and what to do.
7. **Review** within 5 working days: root cause, timeline, what detection missed, actions with owners. Add a test that would have caught it.
