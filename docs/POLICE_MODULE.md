# Puntland Police module (pilot, OFF by default)

Built inside the existing ARMY HQ stack (Django + React + Postgres). No technology was changed. Army data, ranks, roles and
screens are untouched; the original Army-only behaviour is exactly what you get while the switch is off.

## Switch
`POLICE_MODULE_ENABLED=1` (environment variable) turns the pilot on; unset or `0` turns it off.
* ON: seeds the Police rank catalogue (draft) and Police departments, and Police units are visible to personnel, report,
  training, logistics and analytics scopes.
* OFF: nothing Police-specific is seeded, and those scopes exclude every Police unit **on the server** (apps/accounts/scope.py).
  Existing Police records are kept in the database, only hidden.

## Ranks (same as the Army)
Police ranking is **the same as the Army's** (instruction of 2026-10-23): the 18 official Puntland Army ranks, same order, approved, stored as separate Police
rows (`PL-01`..`PL-18`) so the two lists can differ later. They are fully changeable on the Ranks page / API (names, category, code, order) and
**swappable**: `POST /api/v1/ranks/swap/ {"first": id, "second": id}` (permission `ranks.manage`) exchanges two ranks' positions of the same branch in one
step, refuses a swap that would put anyone at or above their own supervisor, and is audited (`rank.swap`). The Ranks page lists the most senior rank first and offers Edit (code, category, English and Somali names), Move up / Move down (swap with the neighbour) and **Swap with…** (swap with any other active rank of the same branch).
Renaming a rank voids its approval until it is re-approved. The earlier draft list from Article 23 of the 1972 law (`PP-01`..`PP-15`) is retired when still as
seeded (deleted if unreferenced, otherwise deactivated); `report_rank_remap` lists anyone still on a retired rank. No General Officer titles exist beyond the Army list.

## Departments and CID
Under each regional Police command: Personnel, Operations, Training, Finance and Logistics, CID, Public Relations, Traffic and
Safety (names to be confirmed; editable in the organization screens). **CID is a restricted unit inside Police.** Its records
(and those of units below it) are only reachable by a role assignment whose role carries `cid.access`; being in the Police
branch, being a branch admin, or holding any other permission is not enough. `cid_officer` is the supplied role.

## Access model
* **Army roles cannot reach Police records by default.** A Police unit is reachable only from (a) an assignment limited to the
  POLICE branch, or (b) a role holding `police.cross_access`. A regional or HQ role with no branch (e.g. the Army regional chief,
  `hq_reporting`) is therefore blocked from Police personnel, reports, training, logistics and analytics. Aggregate counts above
  the unit level are unaffected.
* **Exceptions:** the `command_authority` role, meant for the two highest command appointments (the President / Commander-in-Chief
  and the Commander of the Puntland Defense Forces). Access is by role, not by rank, so an administrator assigns the role to those two
  people. It is read-only, HQ-wide, covers Army and Police, and does **not** include CID (`cid.access` is separate).
  `super_admin` also has `police.cross_access` because it holds every permission; keep it to as few people as possible.
* Give Police staff branch-limited assignments (branch = POLICE).

## Demo accounts (only when the switch is on and demo seeding runs)
`bari.policeadmin`, `bari.policepers`, `bari.cid`; plus `president` and `commander` (command authority, always created) - same demo password as the other demo users.

## Cross-service search
`GET /api/v1/personnel/search/?q=` (page: Search all services). One database query over Army and Police together, returning
per-service counts and up to 50 matches. Needs the `search.cross_service` permission (given to `command_authority`, and to
`super_admin`), and the results use exactly the same scope as the personnel list, so Police gating and restricted CID units
apply: nobody can find a record here that the list would hide. Each search is audited (query length and total only, never the text).

## Personnel-file records (disciplinary history, service documents)
Permissions `disciplinary.view/manage` and `documents.view/manage`; held by `branch_admin`, `cid_officer` and `super_admin` only
(edit `EXTRA` in seed_reference_data to change). Same scope as personnel data, so Police and CID gating apply.
* **Disciplinary history:** encrypted, append-only (app guard + Postgres trigger). A correction is a new entry that points at the
  one it replaces; an entry can be corrected once, so corrections form a chain. Category list is a draft to confirm.
* **Service documents:** PDF/JPEG/PNG up to 8 MB, type judged from the file's bytes, encrypted with a checksum verified on
  download. Never deleted: a wrong upload is withdrawn with a reason (hidden, kept for audit; the DB refuses DELETE).
* Audit actions: `disciplinary.view/add/correct`, `document.list/upload/download/withdraw` (ids and counts only, never text).

## Duplicate identity across services
Same name **and** phone as someone still serving in another service: blocked, no override (`duplicate_identity`). Same name+phone
with a retired record, or same name in another service where a phone cannot tell them apart: flagged, can be confirmed
(`possible_duplicate`). Applies on create, on name/phone edit and in CSV import. Responses never say which service holds the match.
Service numbers were already unique across all services. There is no national-ID field. Run
`python manage.py report_duplicate_identities` once after deploying to find existing duplicates (ids only).

## Combined report
`GET /api/v1/reports/combined/` (page: Combined report), permission `reports.combined` (command_authority, super_admin).
Aggregates only, audited (`report.combined_view`), same scope rules as other personnel data (CID left out without `cid.access`).

## Police structure as working units
`python manage.py apply_police_structure` (dry run by default; `--apply` to write; idempotent, additive, audited; does nothing while the switch is off)
creates, for Bari, Karkaar, Nugaal, Mudug and the new **Sanaag**: the regional Police command, the seven departments (CID restricted) and
**one Police station per command** (`BARI-POLICE-ST1` ...). Raise stations later with `--stations-per-command N` (1 to 20); nothing is ever deleted or
renamed. The Dockerfile start command runs it after `seed_reference_data`. Names are placeholders to confirm with the Police authorities and are
editable in the Organization screens. Army and Navy units are never touched.

**To make Police work end to end you must still** set `POLICE_MODULE_ENABLED=1` (Render dashboard, it is owned there). The Police ranks are already approved, so people can be assigned.

## Chief of Police and Station Leads
Two command appointments (seeded while the switch is on; plain English labels, no Somali wording was supplied): **Chief of Police** (`POLICE_CHIEF`) and **Station Lead** (`POLICE_STATION_LEAD`), one holder each. The Chief is held at a regional Police command (`<REGION>-POLICE`), the Station Lead at a station (`<REGION>-POLICE-ST1` ...), which sits directly under that command, so the order is Chief of Police -> Station Lead. The server refuses either title anywhere else (`appointment_unit_mismatch`) and a second holder (`appointment_exists`). Appoint from the person's page (Command appointments). Like every appointment it grants no access by itself: give the Chief the `regional_commander` role (view) and a Station Lead the `unit_commander` role (attendance, reports), both limited to the Police branch; `unit_commander` may now be held at a station.

## Chief of Police and Station Commander
Every region has a regional Police command (Bari, Karkaar, Nugaal, Mudug, Sanaag) and at least one station under it. Two command appointments sit on that chain, created
by `apply_police_structure --apply` and by `seed_reference_data` (Police switch on): **Chief of Police** (`CHIEF_OF_POLICE`, one holder per regional Police command) and
**Station Commander** (`STATION_COMMANDER`, one holder per station). They are ordinary appointment titles (editable data, Somali names left blank: none supplied),
appointed on the Appointments panel with `personnel.appointments_manage`. Rules: the Chief only on a Police command, the Station Commander only on a Police station,
both only for Police officers. Beneath the chief: when both are appointed the commander's reporting line is set to the chief, in either order, but only if the line is empty and the
chief strictly outranks the commander (never replaces a line set by hand). An appointment grants no access by itself.
Stations: `--stations-per-command N` raises the number of stations in every region.

## Police stations
Level `station`, only directly under a regional Police command; people can be assigned to it; `unit_admin` can be held at a station.
Create stations in the Organization screen. None are seeded for real use (names to be confirmed).

## Police sample data
`seed_test_personnel` (or `ARMYHQ_TEST_PERSONNEL` on Render) also adds Police test people (TST-5001...) across departments, CID and
two synthetic stations per region when the module is on: 2/5 of the Army count, or `ARMYHQ_TEST_POLICE_PERSONNEL`. Needs approved
Police ranks; `ARMYHQ_TEST_POLICE_DRAFT_RANKS=1` lets test people use draft ranks (demo only).

## Not built yet
Verified Somali labels; confirmed department and station names; General Officer ranks (none supplied).
