# Changelog

## Unreleased

- Seeded weapon categories (rifles, pistols, submachine guns, machine guns, sniper rifles, launchers, mortars/crew-served) for the Weapon register and ammunition categories per calibre/type (5.56, 7.62x39, 7.62x51, 7.62x54R, 9 mm, 12.7, 14.5, rockets, mortar bombs, grenades) for the Ammunition ledger. Seeded as draft; approve under Logistics -> Categories.
- Demo mode: synthetic weapons and ammunition opening balances for the demo unit.
- Weapon register form: suggestions for weapon type and caliber.


## Unreleased: Police stations, Chief of Police / Station Commander, rank editing and swapping
- Police ranking is the same as the Army (18 ranks, stored as separate Police rows). Ranks are editable (code, category, names) and swappable (any two active ranks of a branch); audited, and refused when a reporting line would break.
- Police appointments CHIEF_OF_POLICE (regional Police command) and STATION_COMMANDER (station). The commander reports to the chief when the line is empty and the rank rule holds.
- Fixed a TypeScript error in Attendance.tsx that failed `npm run build`. Installable app (PWA) files carried over unchanged.

## Unreleased: Confirmed payroll and survivor-benefit policy (NOT YET RUN: see docs/PAYROLL_POLICY_IMPLEMENTATION.md)
- Survivor benefits are now a standing, indefinite monthly entitlement; they change or end only by a documented, separately approved decision. Case closure likewise.
- Full salary for the month of death (no proration); earlier unpaid salary is tracked as separately approved arrears.
- Suspended/jailed personnel are flagged in payroll and a review queue; pay is unchanged; decisions are recorded and approved by a different officer.
- Payment workflow for Sahal and bank transfer (prepare, authorise, execute, reconcile) with masked, encrypted recipient details. No provider integration.
- Policy settings: confirmed rules fixed, unconfirmed rules listed for the policy authority. New roles `payment_officer`, `payment_reconciler`; `payroll.pay` removed.
- Migrations payroll 0003 (hand-written, additive) and 0004. Tests added; nothing executed in the build environment.

## Unreleased: Security and integrity review, final report (requirements step 8)
- Review of the whole codebase as it stands; findings and fixes are in `docs/IMPLEMENTATION_REPORT_requirements_2026.md`.
- Fixed: the attendance viewset gained a list route (the route-inventory test requires one per registered viewset); migration constraint expressions now mirror
  the models exactly so `makemigrations --check` sees no drift; JSON arrays or scalars sent to the new endpoints are a clean 400 (`invalid_body`), not a server error.
- Added `docs/IMPLEMENTATION_REPORT_requirements_2026.md`: status per requirement, migrations, roles and permissions, tests, outstanding issues, decisions for the army.
- Not implemented: salary inheritance and payroll (no payroll module exists; decision needed).

## Unreleased: Periodic reports, posted by Guuto and Urur heads and seen by the regional command (requirements step 7, part 1)
- The unit report (`unit_situation_report`) is now the **daily, monthly, six-monthly and yearly report**: only whole periods are accepted (a day, a month,
  Jan-Jun or Jul-Dec, a year). Figures are still computed from saved records, frozen at submission, and follow submit -> review -> approve -> amend.
- New in the figures: **weapon accountability** (on the register, held by personnel at period end, issued, returned, reported lost or missing, newly
  registered, condition changes, held by someone no longer serving) and **stock reconciliation** (reconciliations completed, lines with a difference,
  discrepancies still open), next to attendance, personnel status and the ammunition ledger totals. Longer periods reconcile with the daily records
  because everything is calculated from the same underlying rows.
- Who posts: the head of every Urur and Guuto (`unit_commander`, which now also reads the weapon register of its unit, `weapons.view`).
- Who sees: new role `regional_commander` (Taliye Qaybeed, assigned at the regional command, MFA) reads the posted reports, attendance and personnel of its
  own region and nothing outside it. View only: it cannot post, review or approve. A commander's draft is visible only to its author; the regional command
  sees a report once it is posted.
- Assumptions to confirm with the army: who reviews and approves the posted reports (the regional command is view-only for now); whether a Guuto head
  should also see the reports of the Urur below it (it does, by scope); the standard periods; that commanders may read their unit's weapon register.
- Tests added to `attendance/tests/test_attendance.py`. Not run at time of writing (no Django here).

## Unreleased: Ammunition ledger (requirements step 5)
- Built on the existing append-only stock ledger (migration logistics 0003). Ammunition = stock categories whose code starts with `ammunition`
  (one category per type or calibre, for example `ammunition_762`; restricted, draft until approved by the restricted-approval authority).
  **Balances are always calculated from the saved movements**; nothing is typed in.
- New movements: **opening** balance (only as the first entry of an empty line, once), **return** (cannot exceed what was issued), **recorded
  expenditure**, **loss** and **damage**, next to receipt, issue, authorized **adjustment** and paired unit transfers.
- Controls: receipts, issues and returns need a voucher / delivery-note number and the same voucher cannot be booked twice for the same kind of
  movement on a line (database constraint); expenditure, loss, damage and adjustments need a reason; loss, damage and adjustments need a documented
  authorization; an adjustment also needs the explicit `logistics.reconcile` authority; the direction of every movement follows from its kind (database
  check); a negative balance is refused (service and database); every row is append-only, so an adjustment adds a new row (who, why, on whose authority)
  and never overwrites the original. Reconciliation corrections now carry their reconciliation as the authorization.
- The general stock route refuses ammunition (`use_ammunition_ledger`); ammunition is posted only through `/logistics/ammunition/`.
- Statement (`GET /logistics/ammunition/{line}/statement/?from&to`): balance at start, each kind of movement, closing balance, an integrity check (stored
  running balances against the sum of the movements, and against the current quantity), reconciliation counts with their variance and the number of
  discrepancies still open, and the movements.
- The unit situation report now uses these totals: balance at start, opening recorded, receipts, returns, adjustments up and down, issues, expenditure,
  loss and damage, transfers out, remaining. (The earlier `ammo_other_out` figure is replaced by these keys; drafts made before this upgrade must be re-saved.)
- Screen: Ammunition ledger (lines, statement for a period, record a movement, movement history). English and Somali.
- Posting needs `logistics.manage` + `logistics.restricted` over the unit (restricted custodians, weapons custodians); unit commanders can read their
  unit's statement but not post.
- Assumptions to confirm with the army: ammunition is tracked per type or calibre, each its own category; which movements need a voucher or a
  documented authorization; that returns are capped by cumulative issues on the same line; who may adjust (reconcile authority only); whether
  expenditure needs its own document; the opening balance date. Rounds are whole numbers.
- Tests: `logistics/tests/test_ammunition.py`. Not run at time of writing (no Django here).

## Unreleased: Weapon register (requirements step 4)
- New `weapons` app (migration weapons 0001). Weapons are tracked **individually by unique serial number** on the existing restricted asset ledger
  (category `weapons`, restricted, seeded as a draft until the restricted-approval authority approves it). The serial is unique across the whole
  register, in any unit and any weapons category. **No quantity totals are stored:** counts per type, unit, status and condition are derived from
  the register. Quantity-based stock (for example ammunition) stays in the inventory ledger.
- Personal custody: `WeaponCustody` records which soldier holds which weapon, from issue to return: issue and return dates, issuing and receiving
  officer, condition out and in, the authorization reference (mandatory), notes, and the outcome (returned, lost or missing). Rows are never
  edited or deleted (database trigger); a return closes the row and a new issue opens a new one, so the full chain of custody stays.
- Rules: one holder at a time (database constraint); the person must be serving and in the unit holding the weapon; unserviceable weapons are not
  issued; a stale version is refused. While in custody the weapon shows as issued to the soldier's unit and the ordinary asset actions (transfer,
  retire ...) are refused, except reporting it lost or missing, which closes the custody. A weapon issued to a unit and then to a soldier returns
  to the unit state it had. The general asset route can no longer create weapons (they need their type and custody record).
- Access: new role `weapons_custodian` (privileged, MFA) with `weapons.view` / `weapons.manage` and the restricted-asset rights; nobody else
  (not hq_admin, not commanders, not members). The issue screen uses a minimal personnel lookup (name, service number, rank, unit), so the custodian
  needs no personnel permission. Condition changes, registration, issue and return are all audited (`weapon.register`, `weapon.issued`,
  `weapon.returned`, `weapon.condition`) and appear in the asset event history.
- Screen: Weapon register (summary, search and filters, register, issue, take back, condition, custody history). English and Somali.
- Assumptions to confirm with the army: the three condition values, who may issue and return (weapons custodians only for now; commanders can
  view nothing yet), whether a commander should see the weapons of their unit, whether unserviceable weapons may ever be issued, and what happens to
  weapons held by someone who dies or leaves (they are flagged in the summary, not returned automatically).
- Tests: `weapons/tests/test_weapons.py`. Not run at time of writing (no Django here).

## Unreleased: Attendance, absence reporting and the unit situation report (requirements step 3)
- New `attendance` app (migration attendance 0001, personnel 0008). Daily attendance per soldier: present / absent / on leave, absence reason
  (editable catalogue, a document can be made mandatory per reason), note, reporting officer and timestamp. **Separate from personnel status:**
  an absence never changes a status. Records are never edited or deleted; an amendment writes a new record that supersedes the old one with a
  mandatory reason, and the old one stays (database trigger blocks deletes). All entries are checked first, nothing is saved if one is wrong.
- Who: new role `unit_commander` (Taliye Guuto / Taliye Urur), assigned per unit and linkable to the command appointment so access ends with it.
  Permissions `attendance.view`, `attendance.record` (a Guuto commander covers the Urur below). Commanders may attach attendance-support
  documents (that category only) to files in their unit.
- Summaries: daily, monthly, six-monthly and yearly totals, calculated from saved records.
- Unit situation report (report type `unit_situation_report`): personnel status counts (active, on leave, suspended, jailed, died), attendance for
  the period, ammunition received / issued / reduced / remaining from the stock ledger. Figures are computed from saved records when the draft is
  created, edited and submitted (typing figures in is refused), frozen in the revision, then follow the normal submit -> review -> approve flow with
  separation of duties. Approved reports do not change when attendance is later amended. Excluded from consolidated totals (nested units would double count).
- Ammunition: new restricted stock category `ammunition` (draft until approved by the existing restricted-approval authority); any category whose code
  starts with `ammunition` is counted. Reporting it needs `logistics.restricted` + `logistics.view` over the unit, otherwise the report is refused.
- Screens: Attendance page (daily roll with amend, summaries, situation report preview and creation). English and Somali.
- Assumptions to confirm with the army: the three starting absence reasons, whether any reason needs a document, whether back-dated attendance should
  be limited, who may amend, personnel status in a report is as at the time it is made (not reconstructed for a past date), and the ammunition
  figures use only the current ledger (opening balance, returns, expenditure, loss and damage arrive with the ammunition ledger step).
- Tests: `attendance/tests/test_attendance.py`. Not run at time of writing (no Django here).

## Unreleased: Army organizational structure and command appointments (requirements step 2)
- **Army only.** The Police and Navy structures are not read or changed. Death and statuses (step 1) still apply to all personnel.
- Structure as data: `manage.py apply_army_structure` (dry run by default, `--apply` to write, idempotent, audited). It creates the Army
  headquarters **Taliska Guud** (an Army command directly under the system HQ), the seven directorates (Hogganka Ciidanka, Maaliyadda,
  Taakulada, Howlgelinta, Isgaarsiinta, Caafimaadka, Gaadiidka), turns the Army regional commands into **Qaybta Mudug & Cayn, Nugaal & Sool,
  Bari, Sanaag** (new region Sanaag), and adds Urur office unit types (Howlgelin, Xafiiska Ururka, Maamulka Lacagta, Saadka, Xubinta
  Caafimaadka). Karkaar is within Bari: `KARKAAR-ARMY` is retired only when nothing serving is left in it, otherwise the command reports
  what to transfer first. Demo deployments apply it automatically from `seed_demo_data`; a real deployment runs it deliberately.
- Placement: only the Army may have a command directly under the headquarters; a Qayb may be a regional command (branch-command level).
  One existing test that asserted the old rule was updated.
- Command appointments (`AppointmentType`, `CommandAppointment`, migration personnel 0007): Taliye Qaybeed, Taliye Guuto, Taliye Urur,
  Abaanduule, each tied to a unit type, with effective dates and an authority reference. Separate from rank, assignment and role: an
  appointment never grants access. It can be linked to the person's own role assignment so that ending it revokes that access; retirement,
  discharge and a confirmed death end all appointments. Rows are never deleted (database trigger). Permission `personnel.appointments_manage`
  (branch_admin, super_admin). Audit: `personnel.appointment_created`, `personnel.appointment_ended`, `personnel.appointments_ended`.
- Screens: Command appointments panel on the personnel page; Organization screen accepts the new placement and types. English and Somali.
- Assumptions to confirm with the army: English labels are working translations; Taliye Qaybeed / Taliye Urur / Abaanduule are appointments, not
  units; Taliye Guuto follows the same pattern; Abaanduule is kept non-exclusive; the template's Gaas level is left in place; who may
  appoint (branch administrators only for now); suspension or jailing does not suspend an appointment.
- Tests: `organization/tests/test_army_structure.py`, `personnel/tests/test_appointments.py`. Not run at time of writing (no Django here).

## Unreleased: Personnel statuses and death record (requirements step 1)
- Jailed, Died and the death record apply to **all** personnel (every service).
- Statuses: added **Jailed** and **Died** (Active, On Leave, Suspended, Jailed, Died). Retired and Discharged are kept. Died cannot be typed in
  as a status, on create, import or change-status: it is set only by a confirmed death record.
- Death record (`DeathRecord`, migration personnel 0006): report (date of death) -> supporting evidence (document category `death_evidence`,
  encrypted like every service document) -> confirmation by a *different* authorized officer. Confirmation sets Died, writes the status history
  entry effective on the date of death, and closes the person's login (kept linked). A mistaken report can be withdrawn with a reason before
  confirmation. Rows can never be deleted (app guard + PostgreSQL trigger). Nothing is deleted: profile, rank/unit/status history, documents,
  reporting links and audit trail all stay.
- A deceased person's file is closed to edits, transfers, rank and status changes and cannot be named as a supervisor; evidence for a confirmed
  death cannot be withdrawn; the deceased no longer count toward unit strength.
- Permissions: `personnel.record_death` (unit_admin, regional_chief, branch_admin; may also attach death evidence only) and
  `personnel.confirm_death` (branch_admin, super_admin). Audit: `personnel.death_reported`, `personnel.death_confirmed`, `personnel.death_withdrawn`.
- Screen: Death record panel on the personnel page; new status labels in English and Somali.
- Assumptions to confirm with the army: confirmation by a second officer, at least one supporting document before confirmation, who may report
  and who may confirm, and that a confirmed death cannot be reversed in the application.
- Tests: `personnel/tests/test_death_record.py`. Not run at time of writing (no Django in the authoring environment).

## Unreleased: Member role and reporting lines
- New `member` role (permission `personnel.view_team`): a non-commanding member reads their own record and the records of people who report
  to them, read-only, inside the assignment's scope and the Police / CID gates. No export, import, search, reports or sensitive records.
- `Personnel.supervisor` (reporting line) and `Personnel.account` (login belonging to the person). Migration personnel 0005.
- Rules in one place (`personnel/services.py`: `check_supervisor`, `outranks`): same service, strictly senior, reachable by the editor, no loops.
  Seniority is `Rank.sort_order` (higher = more senior); retired ranks (inactive, parked at 1000+) are never compared. Rank changes and rank
  `sort_order` edits that would break a reporting line are refused.
- Screens: reporting-line panel on the person page (supervisor picker fed by `GET /personnel/{id}/supervisor-candidates/`, login link),
  "only people without a supervisor" list filter, and bulk CSV page `/personnel/reporting-lines` (check, then apply all-or-nothing; blank cell =
  unchanged, `clear` = remove) backed by `POST /personnel/reporting-lines/`.
- Audit: `personnel.view_subordinate`, `personnel.reporting_lines`, `personnel.reporting_lines_preview`.
- Demo seed: `bari.member` login (Demo Person 03) with a small reporting line. Tests: `personnel/tests/test_member_team_access.py`.
  Not run at time of writing (no Django in the authoring environment): run the backend suite and `npm test` before deploying.

## Unreleased: Police module completion, batch 1
- Disciplinary history and service documents on personnel files (encrypted, audited, append-only / never deleted).
- Cross-service duplicate-identity check (block / flag) and `report_duplicate_identities` command.
- Combined Army + Police report (`reports.combined`).
- Police stations (`station` level) under regional Police commands.
- Police sample data in `seed_test_personnel`.
- Migrations: personnel 0004, organization 0006. Backend tests unrun at time of writing: run the suite before deploying.

## 2.1.2 - Midnight Navy + Gold theme (frontend, colours only)
Replaced the olive/gold palette with Midnight Navy + Muted Gold in the existing token system (`frontend/src/styles.css`), for both light and dark
themes. Colours only: no markup, layout, routing, API, permission, translation or business-logic change; the theme toggle is unchanged. Adds a
brand-token layer, a darker `--gold-strong` for functional gold on light surfaces, a stronger input/secondary-button border (`--control-border`),
semantic info tokens, chart tokens, button hover states and an opt-in `.gold` button. The favicon and the browser `theme-color` now match the
navy header. Version numbers were not changed. See `docs/CHANGE_REPORT_theme_midnight_navy_gold.md` (includes what was and was not verified).
## 2.1.2 (frontend only)
Netlify-ready frontend without the backend: `frontend/netlify.toml`, `npm run build:netlify` (`scripts/netlify-dist.mjs` writes `_redirects`
with an optional `API_ORIGIN` proxy and the SPA fallback, and `_headers` with a strict CSP whose inline-script hash is computed at build time),
`docs/NETLIFY.md`. The API client now treats an HTML or proxy-error response as "server unreachable" instead of silently accepting it as data
(previously a static host with no API made sign-in appear to do nothing); the login page shows that message when the server cannot be reached.
Added the standalone demo build (`npm run build:demo`: built-in sample API in `src/demo/mock.ts`, `.env.demo`, banner; Netlify default). Added client tests, favicon, `robots.txt`/noindex, `.nvmrc`. Fixed the example nginx CSP, which blocked the inline theme script and React's
inline `style` attributes. No backend or API changes.
## 2.1.1 (frontend only)
Ported the demo build's interface into the source: olive/gold palette, KPI dashboard (cards, "Needs attention" list, per-area panels,
activity meter), icon sign-out button, and an optional demo banner (`VITE_DEMO=1`, off by default). Added browser-side PDF export
(`src/lib/pdf.ts`, no new dependencies) for Personnel, Requests and reports, Summaries, Audit log and the Dashboard; the first three
follow the same permission and feature switches as the CSV exports. Personnel import gained a CSV template, instant client-side checks that
mirror the server limits, drag and drop, step indicator and a downloadable problem list. No backend or API changes.
## 2.0.0
Governed structure changes: `StructureChange` proposals with impact report, `org.structure_propose` / `org.structure_approve`, role `structure_approver`, `organization.0004`, page *Structure changes*; direct unit-type edits now need `STRUCTURE_CHANGES_REQUIRE_APPROVAL=0`.
(Hardening within 2.0: keys cannot use `?unit=` unless `INTEGRATION_ALLOW_UNIT_FILTER=1`; `integration_report` flags keys whose creator lost access.)
Institutional expansion, additive only. New `analytics` app (scoped aggregates), new `integrations` app (read-only bearer-key API,
off by default, hashed keys, expiry, rotation, revocation, small-cell withholding, per-key and per-address throttling, append-only
call log, audit), scoped unit tree, permissions `analytics.view` / `integrations.view` / `integrations.manage`, `integration_report`
command, frontend pages and Somali/English strings, compatibility tests against 1.4. Not built: configurable structural levels,
outbound integrations, offline access. See `docs/IMPACT_ASSESSMENT_v2.0.md` and `docs/CHANGE_REPORT_v2.0.0.md`.
## 1.4.0 (addendum merged from 1.3.1)
The 16 official Puntland Army ranks replace the provisional US-style list; organizational template (Taliska Guud ... Unug)
with reference strengths and approved exceptions, specialist designations (Sahan, Sanco) and expected-relationship rules,
Structure page, searchable unit picker, audit events for the new admin operations, and the fix for 404/403 from
`get_object()` ending in a 500. No other 1.4 behaviour changed. See `docs/CHANGE_REPORT_v1.4.0_merge.md`.
## 1.4.0
Security and reliability hardening only (see docs/SECURITY.md): throttle-bypass fix, TOTP replay protection, absolute
session lifetime, one-time password recovery, database append-only triggers, request limits and security headers, log
redaction, `check --deploy` rules, health endpoints, audit-of-audit-reads, backup/restore/migration scripts, runbook,
CI, authorization sweep + cross-region canary tests, migration/performance tests, accessibility e2e scaffolding.
## 1.3.0
Logistics (categories with institutional review, stock lines with an append-only ledger, serialized assets with
unit-level issue/return and custodianship, reconciliation, restricted-equipment workflow, summaries) and Training
(course catalogue, personnel training records with status rules, minimal roster lookup, summaries). Dashboard blocks.
Fixed a latent 1.0 migration mismatch (audit migration listed a manager).
## 1.2.0
Requests, reports and approvals: configurable types, draft/submitted/under-review/approved/rejected/returned/amended
states, immutable revisions, approval history with comments, separation of duties, scoped regional and headquarters
summaries (approved content only), in-app notifications, controlled summary export (off by default), dashboard blocks.
## 1.1.0
Personnel management: records, scoped search/filter/pagination, duplicate detection, effective-dated rank/unit/status
history, transfer and status workflows, safe CSV import (preview then commit), controlled CSV export (off by default).
Also: field-error codes fixed for hand-raised validation errors (affected 1.0 auth/version errors); malformed UUID
filters now return 400.
## 1.0.0
Initial foundation release. See docs/CHANGE_REPORT_v1.0.md.
