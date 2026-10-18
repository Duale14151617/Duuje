# Puntland Police module (pilot, OFF by default)

Built inside the existing ARMY HQ stack (Django + React + Postgres). No technology was changed. Army data, ranks, roles and
screens are untouched; the original Army-only behaviour is exactly what you get while the switch is off.

## Switch
`POLICE_MODULE_ENABLED=1` (environment variable) turns the pilot on; unset or `0` turns it off.
* ON: seeds the Police rank catalogue (draft) and Police departments, and Police units are visible to personnel, report,
  training, logistics and analytics scopes.
* OFF: nothing Police-specific is seeded, and those scopes exclude every Police unit **on the server** (apps/accounts/scope.py).
  Existing Police records are kept in the database, only hidden.

## Ranks (historical baseline, needs confirmation)
Source: Article 23 "Order of Precedence", Law No. 2 of 23 Dec 1972. 15 ranks in 5 classes, plus a "General Officers" class
with **no ranks** because none were supplied. All are seeded as **draft**: nobody can be assigned a draft rank, so an authorised
administrator must review and approve each rank against current Puntland Police rules first (Ranks page).
Somali labels are not verified (English is stored in both fields). "Cadet Officer" sits in the NCO class as supplied.
Police ranks are a separate catalogue from Army ranks even where names overlap (e.g. Captain, Colonel).

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

## Police stations
Level `station`, only directly under a regional Police command; people can be assigned to it; `unit_admin` can be held at a station.
Create stations in the Organization screen. None are seeded for real use (names to be confirmed).

## Police sample data
`seed_test_personnel` (or `ARMYHQ_TEST_PERSONNEL` on Render) also adds Police test people (TST-5001...) across departments, CID and
two synthetic stations per region when the module is on: 2/5 of the Army count, or `ARMYHQ_TEST_POLICE_PERSONNEL`. Needs approved
Police ranks; `ARMYHQ_TEST_POLICE_DRAFT_RANKS=1` lets test people use draft ranks (demo only).

## Not built yet
Verified Somali labels; confirmed department and station names; General Officer ranks (none supplied).
