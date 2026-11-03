# Changelog

## Unreleased

- **Police and Navy fully removed; Karkaar region removed.** The Police retirement command (`retire_police`), the Police gate and
  `POLICE_MODULE_ENABLED` setting in the scope engine, the station unit level and the Police rank categories are gone. The restricted-unit
  permission `cid.access` is now `restricted.access` (re-synced to roles by `seed_reference_data`). Two choices-only migrations
  (`organization/0011`, `ranks/0006`) keep `makemigrations --check` clean. Old databases that still hold Police, Navy or Karkaar rows are
  no longer filtered: deactivate or delete those rows by hand before upgrading.

- **Stored sample labels renamed from DEMO to SAMPLE (no deletion).** New command `python manage.py rename_sample_data [--apply]` (dry run by default, idempotent) renames what the sample seed stored under the old labels: unit codes `*-ARMY-DEMO-A` -> `*-ARMY-SAMPLE-A`, service numbers `DEMO-0001` -> `SAMPLE-0001`, "Demo Person NN" names, asset identifiers and descriptions, weapon makes, custody authority references and sample account names. It runs at start-up before `seed_sample_data` (Dockerfile), so the seed finds the new labels and does not create duplicates; a row that would clash with an existing value is skipped and reported. Append-only records (stock and PPE movements, soldier rounds, history, audit) are never altered, so older entries there keep the old wording. The seed now writes the SAMPLE labels. New test `test_rename_sample_data.py`.
- **Code-level "demo" names renamed to "sample" / "preview" (existing Render deployment keeps working).** Command `seed_demo_data` is now `seed_sample_data`; environment variables are `ARMYHQ_SAMPLE_MODE`, `ARMYHQ_SAMPLE_PASSWORD` and `ARMYHQ_SAMPLE_RESET`, and **the old `ARMYHQ_DEMO_*` names still work** (the new name wins if both are set), so no change is needed in the Render dashboard. Frontend: `npm run build:preview`, `VITE_PREVIEW`, `.env.preview`, `src/preview/`, `DEMO_SCRIPT.md` is now `PRESENTATION_SCRIPT.md`, and the interface text keys are `preview.banner`, `dash.sampleBanner`, `dash.sampleTitle`, `common.sampleBuild`. Deliberately NOT renamed: the Render resource and database names in `render.yaml` (a Blueprint rename would create a new service and an empty database), and data already stored by the seeds (unit codes `*-ARMY-DEMO-A`, service numbers `DEMO-0001`, asset identifiers `DEMO-...`), which would need a data migration.
- **"Pilot" and "demo" wording removed from the product text.** The login and app footers, README, deployment guides and the dashboard/preview notices now describe a fully functional system deployed on Render (still on synthetic data until the Army approves real records). Deliberately unchanged because renaming them would break the running Render deployment or the code: environment variables (`ARMYHQ_DEMO_MODE`, `ARMYHQ_DEMO_PASSWORD`), the `seed_demo_data` command, `render.yaml` resource names (`armyhq-demo`, `armyhq-demo-db`), the `build:demo` script and `VITE_DEMO` flag, and past changelog entries.
- **Security tightening from the review (no migration).** (1) MFA is now required for the Unit administrator and Headquarters reporting user roles too (they can manage or export personnel data); the role flag is set by `seed_reference_data` at start-up, so existing accounts in those roles are asked to enrol an authenticator at their next sign-in. (2) The personnel photo response now carries `X-Content-Type-Options: nosniff`, like the other downloads. (3) Personnel creation and rank-change requests no longer accept a Police rank. Tests updated (`test_hardening`, `test_rank_list_no_police`).
- **Ranks page: retired ranks hidden by default, search and a count.** A "Show retired ranks" tick box (off by default, so only live ranks are listed), a search box (code or name, English or Somali) and a count of the ranks shown. Dashboard rank counts (draft/approved) no longer include Police ranks. Frontend and read-only API changes only; no migration.
- **Ranks: Police ranks removed from view (nothing deleted).** `GET /api/v1/ranks/` no longer returns ranks of the POLICE branch, so the Ranks page, the rank pickers in Personnel and Change requests, and the branch filter never show them. The six Police-only categories (general officer, senior officer, junior officer, inspector, nco, askari) are no longer offered in the Ranks category filter and editor; the model choices and migrations are unchanged. The rows stay in the database, switched off by `retire_police`; `retire_police --apply --purge` deletes the ones nothing refers to. New test `apps/ranks/tests/test_rank_list_no_police.py`.
- **Sidebar: Logistics and equipment cut from ten entries to six (frontend only; routes, data and permissions unchanged).** The menu now shows Logistics, Ammunition, Protective equipment, Weapons, Military vehicles and Food stores. Pages are grouped as tabs on the page itself: Ammunition (Ammunition ledger, Ammunition accountability), Weapons (Weapon register, Weapon inventory, Soldier holdings) and Military vehicles (Military vehicles, Equipment catalogue). Every tab keeps its own route and its own permission check; a menu entry appears if the user can open at least one of its tabs, and a tab bar is drawn only when more than one tab is visible. New labels `nav.hub.ammunition` and `nav.hub.weapons` (Somali wording should be reviewed). Tested and running on Render.
- **Register-vehicle form: nothing is asked twice.** Choosing a catalogue model now fills the category, make and model from it (shown read-only, with a hint); clearing the model frees them again. The separate "Vehicle type" box is gone because the category is the type; make and model share one "Make and model" field. Frontend only; the API and database are unchanged. Not run in the build environment.
- **Equipment Reference Catalogue: sourced specifications (no schema change).** New command `python manage.py load_reference_specs [--apply]` (dry run by default) fills the catalogue entries that have no specifications yet with published facts and the source each was read from (T-54/T-55, BTR-60, Fiat 6614, Renault GBC 180, M939, Toyota Land Cruiser J79, Toyota Hilux, Nissan Frontier, Ford F-350) and adds mounted-weapon reference entries (DShK 12.7 mm, ZU-23-2, M2 Browning .50, PK/PKM 7.62 mm; identification-level facts only) plus a "General-purpose machine guns" weapon category. Entries stay *unverified* until a second person with `equipment.verify` checks them against the cited source; edited entries are never overwritten; every change is audited. No photographs are loaded: public images carry their own licences, so HQ uploads them after checking the licence on the source page. Not run in the build environment: run `python manage.py test apps.equipment` first.
- **Equipment Reference Catalogue, vehicle reference models, photographs, specifications and mounted armament (additive; migrations `equipment/0001`, `vehicles/0007`).**
  - New app `equipment`, API `/api/v1/equipment/`: catalogue entries with name, classification, manufacturer, description, source, reference photographs (JPEG/PNG judged by content, encrypted at rest, withdrawn never deleted), reference specification lines and a verification status (`unverified` / `verified` / `needs_review`). Reference data only: it never says the Army holds anything. Vehicle models are classified by the **existing** vehicle categories; mounted weapons by new configurable categories (heavy machine guns, automatic cannons, anti-aircraft guns, recoilless rifles, integrated vehicle armament). Entries are switched off, never deleted; changing the facts or specifications of a verified entry returns it to unverified.
  - Seeded by `seed_reference_data` (created once, edits never overwritten): the nine reference vehicle models (T-54/T-55, BTR-60, Fiat 6614, Renault GBC 180, M939, Toyota Land Cruiser J79, Toyota Hilux, Nissan Frontier, Ford F-350), five new vehicle classifications (main battle tank, armoured personnel carrier, military transport truck, military cargo truck, utility pickup; new group `combat_vehicle`) and the five mounted-weapon categories. Ford F-350 reuses the existing "Utility vehicle" category. Every entry starts **unverified**, with no specifications and no photographs: none were invented. Somali names are blank until supplied. No vehicle record was created or changed.
  - Vehicles: optional `reference_model` (code or id) on register and edit (supplies the category only when none is given; never guessed from make/model text); list filter `reference_model`, search also matches the model name; analytics gain `by_model`. Vehicle profiles gain photographs (documents in the new `photograph` category: same encrypted store, scope, withdraw and audit), vehicle specifications (`POST /vehicles/{id}/specifications/`, one audited replacement) and mounted armament (`GET armament/`, `POST armament/add|{id}/remove/`): a catalogue weapon plus optional weapon-register serial; the serial must already exist in the weapon register inside the caller's `weapons.view` scope and is shown only to holders of it; the weapon register itself is never changed. Condition, assignments, maintenance history, documents, disposal workflow and RBAC are unchanged.
  - Permissions: `equipment.manage` (HQ administrator, super administrator) and `equipment.verify` (reserved for the super administrator; nobody can verify an entry they entered). Reading the catalogue needs `vehicles.view`, `weapons.view` or `equipment.manage`. Every create, edit, verification, specification and photograph change and every read is in the audit log.
  - Frontend: new page "Equipment catalogue" (Logistics and equipment) with search, type, classification and verification filters, entry profile with photographs, specifications and verification; Vehicles page gains a reference-model filter and column, register-form model picker, and profile sections for model, photographs, specifications and armament; fleet panel (dashboard and vehicles) shows vehicles by reference model with drill-down. Somali wording of the new labels is English for now and needs review.
  - Migrations were written by hand and the backend and frontend tests were written but **not run** in the build environment (no Django or node modules available): run `python manage.py makemigrations --check`, `migrate`, `test apps.equipment apps.vehicles apps.core` and the frontend `npm test` before relying on this.
- **Vehicle ownership and plates (migration `vehicles/0006`).** Every vehicle is now either *state property* (plate starts with `GD`, e.g. `GD-123`) or *private* (plate starts with `PL`, e.g. `PL-123`). New field `ownership` (`state` | `private`, default `state`) on register and edit; a registered plate that does not start with the prefix of its ownership is refused (`plate_prefix`), and changing ownership requires a plate with the new prefix. Vehicles with no plate or an unknown plate are not affected, and plates already stored are not rewritten. The list accepts `ownership=state|private`; the Vehicles page has an ownership filter and column, and the register form fixes the `GD-` / `PL-` prefix from the choice. Run `python manage.py migrate` and `test apps.vehicles` before relying on it (not run in the build environment).
- **Fleet, equipment and PPE enhancement (additive; existing APIs, permissions and screens kept).**
  - Vehicles: every category now has a classification group (utility, personnel transport, general transport trucks, protected transport, other; migration `vehicles/0005`, seeded categories mapped). New `GET /vehicles/analytics/` (scoped, optional `org_unit`): totals, group/category/condition/status distribution, under maintenance, awaiting or due inspection (30-day window), overdue maintenance, availability, and maintenance spend only for holders of `vehicles.cost`. The list accepts `group`, `condition`, `needs_inspection=1` and `under_maintenance=1`. Vehicles page: new filters and a fleet analytics panel with bars, tooltips and drill-down links.
  - Asset lifecycle (migration `logistics/0006`): assets gain manufacturer, model, condition, acquisition cost and currency, acquired date, procurement reference, last and next inspection, and a replacement link. New actions `POST /logistics/assets/{id}/details|inspect|replace/`; replacing registers a successor in the same unit and retires the old asset, linked, nothing duplicated or deleted, every step in the asset history. Stock receipts record `unit_cost`, `currency` and the delivery reference (procurement spend). Prices show only to users who may see logistics reports.
  - Protective equipment (new app `ppe`, migration `ppe/0001`): categories whose code starts with `ppe` (helmets, body armour, protective clothing, accessories, other; seeded as draft, approve under Logistics). Unit quantity and procurement stay in the logistics stock ledger; a separate append-only ledger records issue, return, damaged, lost and retired per person (issue and return are mirrored one-to-one in the unit ledger under the same voucher), plus replacements and inspections. Logistics itself still holds no link to individual personnel. Endpoints under `/api/v1/ppe/`; new page "Protective equipment".
  - Dashboard: `fleet` and `equipment` blocks (assets, condition, inspections, pending category approvals, PPE inventory and procurement) computed in the database with a fixed number of grouped queries, shown as a "Fleet and equipment" section with drill-down links.
  - Scale (10,000+ personnel): personnel indexes (`personnel/0010`: unit + status, status, name), asset indexes, PPE ledger indexes; the logistics summary and training summary no longer loop over up to 10,000 rows in Python (grouped queries, no cap); the weapons holdings report now says when its 5,000-person cap truncated the result.
  - Somali wording of the new labels should be reviewed. Backend tests were written but could not be run in the build environment: run `python manage.py makemigrations --check`, `migrate` and `test` before relying on this.
- **Interface refresh (frontend only; backend, database, routes and permissions unchanged).** Universal search in the top bar (Ctrl/Cmd+K or `/`) over personnel, units, vehicles, reports, training and logistics, using each module's existing scoped list endpoint. Shared `DataTable` and `FilterBar` (sticky headers, sorting, numbered paging, column show/hide and resize remembered per table, removable filter chips, no-match empty states, stacked cards on phones) used by Personnel, Vehicles, Reports, Training, Logistics stock and assets, Users, Audit log, Summary and Analytics. Personnel profile organised in tabs (personal information, service record, assignments, attendance, training, administrative history). Dashboard reorganised: operational overview first (strength, attendance, pending approvals, logistics warnings, security alerts); regional chart with sorting, exact active/inactive/total counts, hover and focus detail, region labels linking to the permitted personnel list, and an empty state; activity chart with day readout and series switches; audit exceptions; administrative workload (reports awaiting review, outstanding tasks, training progress); security and system health tiles (MFA, accounts, denied requests, failed sign-ins); sized for 1366, 1920 and 2560 wide screens. The personnel list and audit log now read `unit`, `status`, `action` and `outcome` from the address. Somali wording of the new labels should be reviewed.
- **Dashboard polish (desktop-first).** The activity chart is redrawn for desktop widths: failed or denied events get their own red column beside the events column (always at least 4px tall) with their count above it, event counts and weekdays are 12px, there is a labelled y-axis with gridlines, and today is bold. A 7 / 30 day switch fetches `GET /api/v1/dashboard/activity/?days=7|30` (needs `audit.view`; any other value falls back to 7). The region chart legend shows totals, and a not-active segment never shrinks below 3px. The sidebar is grouped into foldable sections (Units and structure, People and training, Pay and welfare, Reports and tasks, Logistics and equipment, Administration); a section opens when you arrive at one of its pages, folds are remembered per browser, and the icon rail shows every page with thin dividers. The "active" KPI shows a ring, zero values are muted, and each item under "Needs attention" has an explicit Review action (security items use the error colour). On phones the chart is drawn on a narrower canvas so its text stays readable, the issue count moves under the date, the range switch fills its row, and the new controls have 44px touch targets; the drawer's focus trap skips folded sections. The Somali wording of the new labels should be reviewed.
- **Police removed (Army-only build).** The Police module's code, tests and documents were moved to `police-archive/` (nothing was lost; its README explains how to restore it). The `POLICE` branch and the regional Police commands are no longer created by `seed_reference_data`; the Institutions page no longer lists the Police and PMPF emblems; the Police demo accounts, appointments, rank catalogue and sample people are gone; the `cid_officer` role and the `police.cross_access` permission are no longer seeded. New command `retire_police` switches an existing database's Police branch, units, ranks and appointment titles off without deleting anything (the Dockerfile runs it at start-up), and branch lists hide inactive branches. `POLICE_MODULE_ENABLED` is now fixed at False and only acts as a safety net in `apps/accounts/scope.py`. Database migrations were left as they are, so existing databases upgrade normally.
- Payments and arrears screens (stages 3 and 4 of the payroll screens): the Payroll page now has three more tabs.
  - **Payments**: prepare a payment against an approved salary line, an approved arrears claim or an authorized survivor benefit (Sahal or bank transfer, recipient details, amount, retry after a failure); then authorize, start sending, record as paid (reference and date), mark waiting, record a failure, cancel, and check against the statement. Each step is offered only to the role that holds it, and the server still refuses the same person doing two steps. Full recipient details are shown only to `payment.details` holders and every reveal is audited. A notice states that no Sahal or bank connection exists and money is sent outside the system.
  - **Arrears**: record a claim (with the member's unpaid approved lines offered as starting evidence), verify, approve or reject (three different people), see paid and outstanding, and prepare a payment for an approved claim. A deceased member's arrears and death-month salary are paid only to a verified beneficiary chosen on the form.
  - **Pay decisions**: the suspended and jailed review queue, each member's pay picture, recording a decision (keep existing pay, or a formal decision with wording, document and a deduction of 5, 10 or 20 per cent as set in the policy), and approving or rejecting it by a different officer.
  - English and Somali text (Somali is a draft for review) and messages for every new server rule. Backend: payment and arrears list rows now include the member's name and service number (additive, no migration). Not covered: salary components (allowances, deductions) still cannot be entered on screen; profiles use the base amount.
- Payroll screens (stage 2): new page "Payroll" (`/payroll`, menu entry for `payroll.view`) with monthly runs (prepare, review lines and the members left out with reasons, submit, cancel, send back, approve, and correct a line by reversal or adjustment) and salary profiles (propose, approve, reject). The payroll chain stays as the server enforces it: the preparer cannot approve. New `GET /payroll/profiles/people/` lets payroll officers find a living member by name or service number (basic fields only); salary profile list now includes the member's name. Shared `ActionForm` component. Payments (stage 3) and arrears and pay decisions (stage 4) follow.
- Survivor benefits screens (stage 1 of the payroll screens): new page "Survivor benefits" (`/survivors`, menu entry for `survivor.view`) to open a case for a confirmed death, register and verify beneficiaries, propose and authorize allocations, propose and approve changes/suspension/termination, raise disputes and close cases, with the server's rules (priority classes, a different person at each step) shown as messages in English and Somali. New `GET /survivor-cases/deceased/` lists confirmed deaths without an open case. Payroll runs, salary profiles, payments and arrears screens follow in later stages.
- Access report: `python manage.py access_report [--format md|csv|json] [--output FILE] [--active-only]` lists every user with username, roles, scope (unit, level, branch, validity, status), the areas and permissions they hold, and review points (expiring assignments, privileged roles without MFA, whole-system access, users with no effective role). Read-only, never includes secrets, output file is owner-readable only, and each run is audited (`access.report`). `docs/ROLE_CATALOGUE.md` lists what each role can do.
- Super administrator maintenance override: new permission `system.full_access` (super_admin only, never given to hq_admin) so module switches such as the Police pilot being off no longer hide data from super_admin. super_admin already held every other permission HQ-wide. Separation of duties, MFA, the audit log and append-only records are unchanged.
- Seeded weapon categories (rifles, pistols, submachine guns, machine guns, sniper rifles, launchers, mortars/crew-served) for the Weapon register and ammunition categories per calibre/type (5.56, 7.62x39, 7.62x51, 7.62x54R, 9 mm, 12.7, 14.5, rockets, mortar bombs, grenades) for the Ammunition ledger. Seeded as draft; approve under Logistics -> Categories.
- Demo mode: synthetic weapons and ammunition opening balances for the demo unit.
- Weapon register form: suggestions for weapon type and caliber.
- Soldier holdings: rounds can be issued to a soldier from the unit's ammunition store (booked in the unit ledger under the same voucher), returned, or written off as expended or lost, in a new append-only ledger (`soldier_rounds`, migration `weapons/0002`).
- New "Soldier holdings" page and `GET /weapons/holdings/`: for a superior, per soldier, the weapons held (serials) and the rounds left per ammunition type with issued, returned, expended and lost.
- Ammunition accountability: every soldier issue/return row is now linked one-to-one to the unit-ledger movement it mirrors (`soldier_rounds.store_transaction`, migration `weapons/0003`; existing rows are linked by line, kind and voucher). Expended and lost rows can never carry a store movement (database check). Rounds issued to a soldier can only be returned to the store through that soldier's holdings, so they cannot count twice.
- New `GET /weapons/disposition/` and "Ammunition accountability" page: physical store stock shown apart from rounds held by soldiers, issued against returned, expended, lost and still held, with movement-by-movement consistency checks between the two ledgers and a per-soldier breakdown. New `GET /weapons/rounds_history/` and a movement history on each soldier (balance after each movement, voucher, authorization, reason, who). The unit ammunition statement is unchanged and now points to this view.


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
- **Army only.** The Police structure is not read or changed. Death and statuses (step 1) still apply to all personnel.
- Structure as data: `manage.py apply_army_structure` (dry run by default, `--apply` to write, idempotent, audited). It creates the Army
  headquarters **Taliska Guud** (an Army command directly under the system HQ), the seven directorates (Hogganka Ciidanka, Maaliyadda,
  Taakulada, Howlgelinta, Isgaarsiinta, Caafimaadka, Gaadiidka), turns the Army regional commands into **Qaybta Mudug & Cayn, Nugaal & Sool,
  Bari, Sanaag** (new region Sanaag), and adds Urur office unit types (Howlgelin, Xafiiska Ururka, Maamulka Lacagta, Saadka, Xubinta
  Caafimaadka). Demo deployments apply it automatically from `seed_demo_data`; a real deployment runs it deliberately.
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
