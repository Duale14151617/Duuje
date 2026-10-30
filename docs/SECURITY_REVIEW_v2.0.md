# Security review — Version 2.0 (self-review; no certification claimed)

Scope: only what 2.0 adds: analytics endpoints, integration clients and the `/ext/` API, the unit tree. 1.4 controls (sessions, MFA, CSRF, throttling, audit triggers) are unchanged. Not independently reviewed; nothing here was executed by the author (see change report).

## Controls
| Surface | Control |
|---|---|
| Analytics (users) | Gate `analytics.view` **and** the section's existing permission; queries limited by `unit_scope_q`; out-of-scope `unit` ⇒ 404 identical to "does not exist"; GET only; restricted equipment excluded; no exports. Administrators get no analytics by default. |
| Integration keys | 256-bit random secret; only SHA-256 stored; constant-time compare with dummy compare for unknown IDs (no ID oracle); wrong key always `invalid_key`; revoked/expired only revealed for a correct secret; mandatory expiry ≤ `INTEGRATION_MAX_DAYS`; rotate/revoke immediate; shown once, `Cache-Control: no-store`. |
| No privilege amplification | A key can only be given sections the creator holds for that unit; checked on create and on change of scopes/unit. |
| Blast radius | One unit subtree, selected sections, aggregates only, approved report content only, small cells withheld, per-key rate limit, per-address bad-key lockout. |
| Isolation | `/ext/` accepts only bearer keys (never sessions/cookies, so no CSRF surface); session users cannot use it; keys cannot use session endpoints. |
| Feature flag | Off ⇒ `/ext/` is 404 and create/rotate/change refused; revoke always allowed. |
| Audit | `integration.create/update/rotate/revoke`, `integration.auth_failed` in the audit log; append-only `integration_calls` (app guard + PostgreSQL trigger). No secrets or data in either. |

## Structure-change gate (added)
| Control | Detail |
|---|---|
| Separation of duties | Proposer ≠ approver, always; `org.structure_approve` is held by a dedicated MFA role with no data access and is excluded from the default administrator. |
| Nothing live before approval | Drafts/submitted proposals only store plain-data operations (validated, never executed); approval re-evaluates against the current catalogue and applies in one transaction. |
| Impact check | Blocks changes that would invert existing units' hierarchy or deactivate levels in use. |
| Direct-edit bypass | Direct unit-type writes are refused by default (`approval_required`). Risk: setting `STRUCTURE_CHANGES_REQUIRE_APPROVAL=0` or database access bypasses the gate; keep the setting under change control. |
| Audit | `structure_change.create/update/submit/approve/reject` plus `unit_type.*` events with the change id. |
Open point: with only two humans (one proposer, one approver) collusion is possible; the institution decides how many approvers to appoint.

## Residual risks (known, not fixed)
- **R1 Stolen key:** whoever holds a key reads its aggregates until expiry/revocation. Mitigate with short expiries, custody rules, `integration_report`, IP allow-listing at the proxy (recommended, not built).
- **R2 Creator privilege drift (partly mitigated):** a key is not re-evaluated at call time. `manage.py integration_report` now flags (exit 2) active keys whose creator is disabled or no longer holds the granted access; run it on a schedule. Enforcement at call time was not added because it would silently break integrations when staff change.
- **R3 Differencing (partly mitigated):** small-cell suppression applies per response. An authorized key holder can combine many filtered calls (different `unit`/dates) to infer small groups. It is not differential privacy. `?unit=` is now refused for keys by default (`INTEGRATION_ALLOW_UNIT_FILTER=0`), which removes the easiest route; date filters remain. Also scope keys to large units, keep rate limits and review the call log.
- **R4 Bad-key lockout is per source address:** shared NAT can lock out a legitimate system; behind a proxy with `TRUST_PROXY_HEADERS` misconfigured every client shares one address (self-inflicted denial of service). Verify `NUM_PROXIES`.
- **R5 Proxy/log hygiene:** `Authorization` headers must not be logged by proxies or WAFs. The application does not log them; the proxy is outside this repository.
- **R6 Cost:** analytics queries are live and unpaginated (turnaround uses at most 5,000 rows); not load-tested.
- **R7 Call-log growth:** append-only, no purge; needs a retention decision.
- **R8 Inherited:** an HQ administrator can still grant themselves a data role (1.4 risk); a two-person rule is recommended and is what the no-amplification rule leans on.
- **R9 Unit tree** lists unit names in scope (already visible via the Organization page); capped at 2,000 units.

## Test evidence (written, not run)
`analytics/tests/test_analytics.py` (scope per role, 404 for out-of-scope units, permission gate, restricted exclusion, small-cell logic), `integrations/tests/test_integrations.py` (hash-only storage, no amplification, validation, rotation, revocation with flag off, expiry, indistinguishable failures, scope denial, approved-only reports, suppression, per-key and per-address throttling, append-only log, audit without secrets), `organization/tests/test_tree.py`, `core/tests/test_v2_compatibility.py`, plus the existing authorization sweep which now covers the new routes. Only the pure small-cell function and key-format regex were actually executed (outside Django).

## Needs independent review
Key lifecycle and storage; the `/ext/` authentication class and throttling; analytics scope derivation (`UserScope`, `ClientScope`); differencing risk acceptance; proxy configuration for `Authorization` and client addresses.
