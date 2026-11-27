# Integration API (2.0) — read-only aggregate analytics

Off by default (`INTEGRATIONS_ENABLED=0`). When off, `/api/v1/ext/*` answers 404 and no key can be created or rotated (revocation always works).

## Onboarding checklist
Written institutional approval of the integration · named key custodian · sections and unit agreed (least privilege) · expiry chosen (max `INTEGRATION_MAX_DAYS`, default 365) · TLS only · rotation/revocation contact agreed.

## Creating a key (HQ administrator)
*Integrations → Add integration*, or `POST /api/v1/integrations/clients/` with `name`, `description`, `scopes` (any of `personnel`, `reports`, `logistics`, `training`), `org_unit` (the key is limited to that unit and everything below it) and `expires_at`.
- You can only grant a section you hold yourself for that unit (`personnel.view`, `reports.summary`, `logistics.report`, `training.report`). The default HQ administrator holds none of these, so a second person with the right access must create the key. This is intentional.
- The full key (`ahq_<id>_<secret>`) is returned **once**. Only its SHA-256 hash is stored; it cannot be recovered. Lost key → replace it (*Replace key*, `POST …/{id}/rotate/` with the current `version`); the old key stops immediately. Revoke with *Revoke* / `POST …/{id}/revoke/`.

## Calling
```
curl -H "Authorization: Bearer ahq_1a2b3c4d_…" https://armyhq.example.org/api/v1/ext/me/
curl -H "Authorization: Bearer …" "https://…/api/v1/ext/analytics/personnel/?from=2026-01-01&to=2026-06-30"
```
`GET` only. `unit` is refused (`400 unit_filter_not_allowed`) unless the operator sets `INTEGRATION_ALLOW_UNIT_FILTER=1`; when allowed it must lie inside the key's unit (otherwise 404). Dates are ISO (`YYYY-MM-DD`). Responses are `{section, min_cell, data}`; each distribution is `{total, rows, suppressed}`; withheld values are `null`. Reports sections contain approved reports only. Restricted logistics equipment never appears.

## Errors (JSON `{code, detail}`)
| HTTP | code | Meaning |
|---|---|---|
| 401 | `not_authenticated` | no `Authorization: Bearer` header |
| 401 | `invalid_key` | unknown or wrong key (indistinguishable on purpose) |
| 401 | `key_revoked` / `key_expired` | key was right but is no longer valid |
| 403 | `scope_denied` | section not granted to this key |
| 404 | `not_found` | feature off, unknown section, or unit outside the key's unit |
| 400 | `validation_error` | bad date value, or `unit_filter_not_allowed` |
| 429 | (throttled) | per-key rate (`THROTTLE_INTEGRATION`, default 60/min) or too many bad keys from one address; honour `Retry-After` |
Retry only on 429 and network errors, with back-off. Never retry 401/403 in a loop: repeated bad keys lock the source address out for `INTEGRATION_FAIL_WINDOW` seconds.

## Audit
Every authenticated call is logged (time, endpoint, status, outcome, source address) and visible to HQ administrators in the UI. Create/change/rotate/revoke and failed authentications are in the audit log. Neither log contains keys or response data.
