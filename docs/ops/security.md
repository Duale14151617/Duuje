# Security controls and test coverage

| Area (OWASP) | Control | Test |
|---|---|---|
| Broken access control | Server-side check of membership, active status, company status, permission and company id in every lookup; non-members get 404 (ids cannot be probed); technicians reach only their own assignments/payables | Phase1–6 tenant tests; `Another_company_cannot_reach_any_record_by_substituting_ids`; `Staff_cannot_escalate_their_own_role` |
| Separation of duties | See permission-matrix.md | Phase4Tests |
| Authentication | Password hashing (ASP.NET Identity hasher), JWT 30 min, token-version revocation, suspended users rejected, TOTP MFA with replay protection/lockout, recovery tokens hashed/single-use, auth rate limit | Foundation2Tests |
| Rate limiting | Per-user/IP global limiter + stricter auth policy; 429 counted in metrics | `Requests_are_rate_limited_per_client` |
| Injection | EF Core parameterised queries only; no raw SQL with user input; JSON binding | code review rule; dependency scan |
| Insecure file handling | Type sniffed from bytes (PDF/JPEG/PNG only), size cap (5 MB; Kestrel 12 MB), random storage keys, names never used as paths, SHA-256, scanner hook (ClamAV, fail-closed; production refuses to start without one), 120 s signed links bound to user and re-authorised | `Malicious_uploads_are_refused_and_names_cannot_escape`, `A_failing_scanner_blocks_the_upload` |
| Misconfiguration | Secrets only from environment; startup refuses weak/missing keys; security headers, no server banner, `no-store`, HSTS in production, container runs unprivileged/read-only, ops endpoints hidden | `Responses_carry_security_headers…`, smoke.sh |
| Audit tampering | Append-only in the app and (PostgreSQL) by trigger; ledger/payment events same | `Audit_events_cannot_be_edited_or_deleted`, `Ledger_entries_cannot_be_changed…` |
| Duplicate payments | Idempotency keys, unique provider reference, unique ledger line keys, concurrency tokens, over-payment checks, callback dedupe | Phase4Tests |
| Vulnerable components | CI `dotnet list package --vulnerable`, `npm audit`, Trivy, secret scan | CI |
| Logging | Correlation ids; no secrets/bodies/documents logged; audit metadata redacted by construction | review rule |

## Known gaps (accepted for pilot only if the owner signs them off)
- No external penetration test yet; no DAST run. Commission one before public launch.
- Access tokens are JWT bearer (30 min) kept in `sessionStorage` on the web; a strict CSP/XSS review of the SPA is pending. An OIDC identity provider (spec: supported provider or securely implemented first-party) is not yet chosen.
- Rate limiting is in-process (per instance). Behind several instances use the proxy or a shared store.
- Files are on a local volume, not private object storage; `IFileStore` is the seam.
- MFA is optional unless `Security__MfaRequiredPermissions` is set; the list of mandatory roles is undecided.
- Audit rows are not hash-chained; tamper-resistance relies on append-only enforcement and restricted DB access (the DB admin could still alter them). Export to write-once storage if required.
