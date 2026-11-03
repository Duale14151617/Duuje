# Configurable organizational structure and its approval gate (2.0)

## What the structure is
- **Four fixed top-level categories:** Headquarters, Region, Branch command, Unit. These are unchanged. Roles, scope checks and database constraints depend on them, and nothing in 2.0 alters them.
- **Configurable subordinate levels** (the "unit types"): Taliska Guud, Qayb, Gaas, Guuto, Urur, Horin, Koox, Unug are *data*, not code. Each has an editable code, English/Somali names, **order** (`tier`), **parent level** (`parent_type`), **standard number per parent** (`standard_per_parent`) and **strength standard** (`reference_min`/`reference_max`). New levels can be added and old ones deactivated. Units nest to any depth, and access is derived from the unit's position (path), so every level, existing or new, is automatically inside the right scope.
- **Hard rules** (always enforced): a level must be deeper than its parent level; max ≥ min; a level in use by active units cannot be deactivated; an active level cannot sit under an inactive one; no existing unit may end up under an equal or deeper level; Taliska Guud is for branch commands, all other levels for units.
- **Soft checks** (reported on the *Structure* page, never blocking): strength vs standard, number of children per parent, designated Sahan/Sanco units.

## The approval gate
`STRUCTURE_CHANGES_REQUIRE_APPROVAL` is **on by default**. Direct edits of unit types (`POST/PATCH /organization/unit-types/`) are refused with `409 approval_required`; reading is unchanged. Changes go through a proposal (*Structure changes* page, `/api/v1/organization/structure-changes/`):

1. **Draft:** a user with `org.structure_propose` (HQ administrators) edits the levels in the form; only differences are stored as operations (`create`/`update`, plain data validated on save). The server shows an **impact report** (errors, levels created/updated, existing units affected) without writing anything.
2. **Submit:** only the proposer, only when the report has no errors.
3. **Decision:** a *different* person with `org.structure_approve` (new role **Structure approver**, privileged, MFA, no data access) approves or rejects. Self-approval is always refused (`self_approval_forbidden`) and cannot be configured away. Rejection needs a reason.
4. **Approve = apply:** the proposal is re-checked against the *current* catalogue (it may have changed since submission) and applied in one transaction; if anything fails, nothing is written. Versioned, audited (`structure_change.*`, `unit_type.create/update` with `via: structure_change`).

Nothing in a draft or submitted proposal affects live structure. Existing units, paths, roles and role assignments are never rewritten by a level change.

## What is NOT covered by the gate (be aware)
- **Designation rules** (Sahan/Sanco relationships), **designations** and per-unit **strength exceptions** remain direct HQ edits: they are checked-not-enforced information, not the level structure.
- **Role definitions** (which permissions a role holds) are system-defined in `seed_reference_data` and change only by a code release, which is itself the review point. There is no per-role "allowed levels" setting for the subordinate levels; roles assigned at a unit already cover its whole subtree whatever its type. If the approved structure needs roles tied to specific level types (for example "only assignable at a Qayb"), that is a further, separately approved change.
- **Re-parenting an existing unit** is still not supported.
- The four top-level categories cannot be made configurable without a design review.

## Before approving the first real change
Have the institution confirm the target structure in writing (level names, order, parents, strength standards, Somali names). Use *Structure changes* so the decision, proposer and approver are on record. The 1.3.1 template values were supplied as official but the Somali names equal the English ones until verified wording is supplied.

## Rollback
A level change is data. To undo, propose the reverse change (it goes through the same approval). For emergencies, set `STRUCTURE_CHANGES_REQUIRE_APPROVAL=0` temporarily (audited as normal edits) or restore the pre-change backup. `migrate organization 0003` drops the proposals table (while 2.0 code is deployed).
