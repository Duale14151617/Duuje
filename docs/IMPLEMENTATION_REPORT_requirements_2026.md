# Implementation report: Army requirements from the meeting with army personnel

Scope: extend the existing system, do not rebuild it. Everything below was built on the existing authentication, RBAC with organizational
scope, audit (`record()`), append-only ledgers, workflows and document store. Synthetic data only.

**Read this first.** Nothing in this report has been executed. The authoring environment had no Django, no database and no network, so the new tests
were written and read through but never run, the migrations were hand-written (not generated), and the screens were syntax-checked only. The first
real verification is CI (`makemigrations --check`, `manage.py test`, `npm test`). Expect some small fixes there. Deployment steps are at the end.

## 1. Status against the requirements

| # | Requirement | Status |
|---|---|---|
| 1 | Five personnel statuses, deceased kept permanently | **Implemented** (Jailed and Died added; Retired and Discharged kept) |
| 2 | Deceased soldier salary inheritance (beneficiaries, payroll) | **NOT implemented.** There is no payroll module in this codebase and no salary data. Blocked on a decision (section 6) |
| 3 | Army organizational structure | **Implemented** as data with a dry-run command; names and reporting lines still need army confirmation |
| 4 | Rank, appointment, assignment, role kept separate; scoped RBAC | **Implemented** (appointments, regional commander, unit commander, member role, access ends with the appointment) |
| 5 | Attendance and absence reporting | **Implemented** (see gaps) |
| 6 | Weapon accountability | **Implemented** |
| 7 | Ammunition ledger | **Implemented** |
| 8 | Reporting and dashboards | **Reports implemented**; dashboards not extended |
| 9 | Security and data integrity | **Reviewed, hardened where found** (section 5) |
| 10 | UI and localization | **Implemented**, Somali needs a native review, not browser-tested |
| 11 | Implementation and testing | Tests written, **not run** |

## 2. What was built

**Statuses and death (all personnel, every service).** `Jailed` and `Died` join Active, On Leave and Suspended. `Died` can only be set by a confirmed
death record: an officer reports the date of death, supporting evidence is attached (encrypted document category `death_evidence`), and a *different*
officer confirms. Confirmation writes the status history effective on the date of death, closes the person's login (the link is kept) and ends their
command appointments. A mistaken report can be withdrawn before confirmation. Death records are never deleted (application guard and database trigger).
A deceased person's file is closed to edits, transfers and rank changes, cannot be a supervisor, and no longer counts in unit strength. Profile,
history, documents and audit trail all stay.

**Member role and reporting lines.** A non-commanding member sees their own record and their direct subordinates only, read-only and audited
(`personnel.view_subordinate`). Supervisor and login link are fields on the personnel record, with one shared rulebook (same service, strictly senior, in
the editor's reach, no loop, retired ranks never compared) and a bulk CSV tool.

**Army structure (Army only, Police and Navy untouched).** `manage.py apply_army_structure` (dry run by default, idempotent, audited): Taliska Guud as an
Army command under the system HQ, seven directorates (Hogganka Ciidanka, Maaliyadda, Taakulada, Howlgelinta, Isgaarsiinta, Caafimaadka, Gaadiidka), the
regional commands Qaybta Mudug & Cayn, Nugaal & Sool, Bari, Sanaag (new region Sanaag; Karkaar is within Bari and is retired only when empty), and Urur office
unit types. For **each of the four regional commands** (Mudug & Cayn, Nugaal & Sool, Bari, Sanaag) it also creates one Guuto (brigade, e.g. `BARI-ARMY-G1`) and one Urur (battalion, e.g. `BARI-ARMY-G1-U1`) each, and every Urur gets its five battalion sections as real units (`...-U1-OPS` Operations/Howlgelin, `-ADMIN` Administrative Office, `-FIN` Finance, `-SUPPLY` Logistics and Supply, `-MED` Medical Unit). Taliye Urur (commander) and Abaanduule (executive officer) are appointed on the Urur unit itself. To add more later run
`apply_army_structure --apply --guuto-per-command N --urur-per-guuto M` (1 to 20; additive, never deletes or renames) or use the normal unit tools.

**Command appointments.** Taliye Qaybeed, Taliye Guuto, Taliye Urur, Abaanduule (confirmed 2026-10-23 as the Battalion Executive Officer / Second-in-Command; non-exclusive until the army says a Urur has only one), with effective dates and an authority reference; separate from rank,
assignment and role; an appointment never grants access, but can be linked to the person's own role assignment so ending it (or retirement, discharge or
death) revokes that access. Rows are never deleted.

**Attendance.** Daily present / absent / on leave per soldier with reason, note, optional supporting document, reporting officer and timestamp. Attendance
never changes personnel status. Records are never edited: an amendment writes a new record superseding the old one, with a mandatory reason. Daily,
monthly, six-monthly and yearly summaries are calculated from the records.

**Weapon register.** Individually tracked by unique serial number on the restricted asset ledger; counts are derived, never stored. Personal custody
(issue, return, condition out and in, mandatory authorization reference, outcome returned / lost / missing) is append-only; one holder at a time;
ordinary asset actions are blocked while a weapon is in custody.

**Ammunition ledger.** Opening balance, receipts, issues, returns, recorded expenditure, losses, damage and authorized adjustments, plus paired transfers.
Balances come from the movements. Vouchers stop double entry (database constraint), losses, damage and adjustments need a documented authorization,
adjustments also need the reconcile authority, negative balances are refused, rows are append-only. The statement shows the opening balance, each kind of
movement, the closing balance, an integrity check and reconciliation discrepancies.

**Periodic reports.** The head of every Urur and Guuto posts a daily, monthly, six-monthly or yearly report whose figures are computed from the records
(personnel status, attendance, ammunition, weapon accountability, stock reconciliation and open discrepancies), frozen at submission, then
submit -> review -> approve -> amend with separation of duties. The regional command (Taliye Qaybeed) sees posted reports of its own region, view only.

## 3. Database migrations (apply in this order, all additive)

- `personnel 0005` supervisor and account link; `0006` Jailed / Died, death record (+ delete trigger); `0007` command appointments (+ trigger);
  `0008` attendance-support document category
- `attendance 0001` absence reasons, attendance records (+ trigger)
- `weapons 0001` weapon details, custody (+ trigger)
- `logistics 0003` new stock movement kinds, voucher and authorization columns, direction and uniqueness constraints

No existing column is dropped or rewritten. Run a database backup (`ops/backup.sh`) before applying on real data.

## 4. Roles and permissions

| Role (new) | Scope | Holds |
|---|---|---|
| `member` | any | own record + direct subordinates, read-only (`personnel.view_team`) |
| `unit_commander` (Taliye Guuto / Urur) | unit | personnel view, attendance view and record, reports view and submit, restricted stock read, weapons view |
| `regional_commander` (Taliye Qaybeed, MFA) | branch command | personnel view, attendance view, reports view |
| `weapons_custodian` (MFA) | branch command / unit | weapons view and manage, restricted-asset rights |

New permissions: `personnel.view_team`, `personnel.record_death`, `personnel.confirm_death`, `personnel.appointments_manage`, `attendance.view`,
`attendance.record`, `weapons.view`, `weapons.manage`. Existing roles gained only: unit administrators and regional chiefs may *report* a death, branch
administrators may also confirm it and manage appointments. Headquarters administrators gain none of the new sensitive permissions.

## 5. Security and integrity review

Reused and confirmed (not changed): `__Host-` session and CSRF cookies in production, idle session timeout, MFA for privileged roles, deny-by-default
route tests, encrypted service documents, correlation-id audit, `ops/backup.sh` and `ops/restore_test.sh` (they dump the whole database, so every new table is
covered; the restore test has not been re-run after these changes).

Found and fixed during this review: (1) the attendance viewset had no list route, which the existing route-inventory test would have rejected; (2) hand-written
migration constraints did not mirror the models exactly, which would have failed `makemigrations --check`; (3) JSON arrays or scalars sent to the new endpoints
could have caused a server error, now a clean 400; (4) two bypasses closed: weapons can no longer be created through the general asset route, and ammunition can no
longer be posted through the general stock route.

Built-in controls: every new table refuses deletes at the database; amendments add rows instead of overwriting; unknown and out-of-scope ids read alike;
authorization comes before validation; reads of a subordinate's file are audited; approved reports and ledgers are never silently changed.

Not done or not verified: no dependency or vulnerability scan; no load or concurrency test beyond database constraints; reads of the weapon register and of
attendance are not audited (changes are); the new write endpoints rely on the default throttles; no browser, accessibility or phone-layout testing.

## 6. Decisions needed from the army (assumptions, not confirmed policy)

1. **Payroll and inheritance (blocking).** Is there an existing payroll system or data to connect to, or should a minimal payroll record be built? The priority
   order (wife and children, then parents, then siblings) and the rule for dividing amounts must be confirmed by the army before anything is coded.
2. **Structure.** English labels are working translations. Are Taliye Qaybeed, Taliye Urur and Abaanduule appointments rather than units? What is Abaanduule? **Answered 2026-10-23: the Battalion (Urur) Executive Officer / Second-in-Command.**
   Is Taliye Guuto the right title? What happens to the Gaas level the template still has? Who heads each directorate?
3. **Death.** Confirmation by a second officer, at least one document before confirmation, who may report and confirm, and that a confirmed death is not reversible
   in the application.
4. **Attendance.** The three starting absence reasons, whether any needs a document, whether back-dating should be limited, who may amend.
5. **Weapons.** The three condition values, whether commanders may see the register, whether an unserviceable weapon may ever be issued, and what happens to weapons
   held by someone who dies or leaves (flagged, not returned automatically).
6. **Ammunition.** Per type or calibre as separate categories, which movements need a voucher or authorization, returns capped by issues, who may adjust.
7. **Reports.** Who reviews and approves the posted reports (the regional command is view-only), and whether the standard periods are enough.
8. **Appointments.** Who may appoint, and whether suspension or jail should pause an appointment.
9. **Somali.** All new Somali text needs review by a native speaker, especially military terms and the rank categories.

## 7. Not implemented

Salary inheritance and any payroll (requirement 2); dashboard widgets for the new data; a per-record review and approval status for attendance (approval happens
through the periodic report); reversal of a confirmed death; automatic return of weapons on death or discharge; Guuto and Urur unit data (created by authorized users).

## 8. Tests

Written, not run: `personnel/tests/test_member_team_access.py`, `test_death_record.py`, `test_appointments.py`; `organization/tests/test_army_structure.py`;
`attendance/tests/test_attendance.py`; `weapons/tests/test_weapons.py`; `logistics/tests/test_ammunition.py`. Updated: `test_v2_compatibility.py` (new roles and the
documented permission gains) and one assertion in `organization/tests/test_structure.py` that the new structure contradicts.

## 9. Deploying

1. Take a backup (`ops/backup.sh`). 2. Merge to a branch, let CI run, fix what it reports. 3. Deploy: the start command already runs `migrate` and `seed_reference_data`.
4. Review the structure: `python manage.py apply_army_structure` (dry run), then `--apply`. 5. Have the restricted-approval authority approve the `weapons` and
`ammunition` categories. 6. Assign roles per unit (unit commander, regional commander, weapons custodian), linking each to the command appointment. 7. Link logins to personnel
records and fill in supervisors (bulk CSV page). 8. Have a Somali speaker review the translations.
