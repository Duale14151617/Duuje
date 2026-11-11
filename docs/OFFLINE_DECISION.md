# Offline access — decision record (2.0)

**Decision: not implemented in 2.0.**
The 2.0 brief allows controlled offline access only "if a documented need exists". No documented need (who, where, which workflows, connectivity data) was supplied, and offline caching of personnel or logistics data materially enlarges the attack surface (lost or seized devices). Building it speculatively would have been the wrong trade.

## If a need is documented later, the brief already fixes the design constraints
- The server stays authoritative; the client never decides authorization.
- Cache only the minimum fields needed for the documented workflow; encrypt at rest on the device; expire and wipe the cache (time limit and on sign-out/revocation).
- Queue writes as idempotent operations with client-generated operation IDs; detect version conflicts (the existing `version` field and 409 behaviour already support this) and never overwrite silently.
- Re-authorize every queued operation on synchronization, against the user's *current* role and scope; reject what is no longer allowed.
- High-impact actions (report approval, role changes, stock write-offs, status changes) require an online confirmation.
- Remote wipe via session revocation (`auth_epoch`) must make the cache unusable.
- Needs a threat model for device loss, a retention decision, and an impact assessment before any code.

Nothing in 2.0 blocks this: `version` fields, append-only histories and the session epoch were designed with it in mind.
