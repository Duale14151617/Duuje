# Impact assessment — Version 2.0 (institutional expansion)

Base: 1.4.0 (reported working by the project owner; not independently verified by the author of 2.0).
Rule applied: *add only expansions that are safe to ship switched off or are read-only, keep every 1.x contract.*

## 1. What the 2.0 brief lists, and what was done

| Candidate expansion | Decision | Why |
|---|---|---|
| Additional configurable organizational levels | **Done for the subordinate levels; the four top-level categories are unchanged.** The Qayb…Unug levels (names, order, parent links, strength standards) were already data from the 1.4 merge; 2.0 adds the **approval gate** (propose → submit → a different person approves and applies), an impact report, a new `structure_approver` role, and a scoped unit **tree**. See `STRUCTURE_APPROVAL.md`. | The four categories (HQ, region, branch command, unit) are built into roles, the scope engine and DB constraints; making them configurable needs a design review. Subordinate levels need no scope change because access follows the unit path. **Behaviour change:** direct edits of unit types are now refused unless `STRUCTURE_CHANGES_REQUIRE_APPROVAL=0`. |
| Stronger reporting analytics | **Done.** New `analytics` app: personnel, reports, logistics and training aggregates with date/unit filters. Read-only, no exports. | Reuses the permissions that already govern each data set; adds no new data access (see §3). |
| Approved integrations | **Done, inbound and read-only, OFF by default.** New `integrations` app: scoped, expiring, revocable keys that can read aggregate analytics only. | Documented API, scoped credentials, audit logging, failure handling are all required by the brief. **Outbound** calls/webhooks were deliberately not built (no approved destinations; SSRF and data-egress risk). |
| Optional controlled offline access | **Not implemented.** See `OFFLINE_DECISION.md`. | The brief makes it conditional on a documented need; none exists. |

Nothing in 2.0 is a tactical, intelligence, live-tracking, targeting or mapping feature.

## 2. What changes for whom
- **Users:** new menu items appear only if their role allows: *Analytics* (`analytics.view`), *Unit tree* (`org.view`), *Integrations* (`integrations.view`, and only meaningful when the feature is on). Existing screens are unchanged.
- **Roles:** new role **Structure approver** (`org.structure_approve`, MFA, no data access); `hq_admin` gains `org.structure_propose` but cannot approve. `analytics.view` is added to `hq_reporting`, `regional_chief`, `branch_admin`. `hq_admin` receives `integrations.view/manage` but **no** analytics (administrators still hold no data permissions). No permission was removed from any role.
- **Operators:** new env settings (all safe defaults), 2 new tables, one new cron-able command (`integration_report`).
- **Integrators (external systems):** nothing, until the institution approves an integration and an HQ administrator who holds the underlying data permissions creates a key.

## 3. Data and privacy impact
- No new personal data is collected or stored. Analytics are computed on demand from existing tables.
- Every analytics query is limited by the same scope rule as the owning module: users by their role assignments, integration keys by one unit subtree.
- Aggregates only; restricted logistics equipment is excluded entirely; integration keys see **approved** report content only (no workflow-state metrics).
- Small-number control for integrations: cells below `INTEGRATION_MIN_CELL` (default 5) are withheld, and totals/neighbouring cells are withheld where subtraction would reveal them. This is **not** differential privacy (see `SECURITY_REVIEW_v2.0.md`, risk R3).
- New stored data: integration client records (name, scope, unit, expiry, **hash** of the key) and a call log (time, endpoint, status, source address). No keys, no response data.

## 4. Operational impact
- Migrations are additive (three new tables, one trigger; the only migration in an existing app is `organization.0004`, which creates the proposals table). Nothing existing is altered. See `MIGRATION_PLAN_v2.0.md`.
- `integration_calls` is append-only (like the audit table), so it grows without a purge job; the institution needs a retention decision before enabling integrations.
- Analytics queries run live. Cost grows with data volume; not load-tested.

## 5. Approvals needed before the optional parts are used
1. Written approval of each integration: the receiving system, its owner, the sections and the unit it may read.
2. Named custodian for each key; rotation and revocation process.
3. Decision on call-log retention and on the small-cell threshold.
4. Confirmation that role grants of `analytics.view` match policy.
5. Independent security review of the new surfaces (list in `SECURITY_REVIEW_v2.0.md`).
6. Somali text for the new screens reviewed by a qualified translator (the new strings are a draft).

## 6. Not claimed
No production-readiness, security certification or institutional authorization is claimed. Real personnel data still requires the approvals in the roadmap's governance checklist.
