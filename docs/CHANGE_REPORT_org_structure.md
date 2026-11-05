# Change report: Organizational Structure and Unit Management upgrade

Extends the existing Units module. Nothing was replaced: the unit tree, placement rules, appointments, scope engine, audit log, personnel records and all existing data are unchanged. **No unit, commander, deputy or person is created by this change.**

## What was added
| Area | Addition |
|---|---|
| Hierarchy | `UnitType.formation_role` (ghq / regional / brigade / battalion). Defaults tag the existing types Taliska Guud, Qayb, Guuto, Urur; editable under **Structure settings**. `GET organization/units/chart/` returns the expandable chart with strength per formation. |
| Departments | `Department` catalogue (names only) seeded with Command and Administration, Human Resources, Medical Services, Finance, Logistics, Communications, Training. `UnitDepartment` = a department established in a unit. `apply_army_structure --apply` establishes the seven at General Headquarters (`ARMY-HQ`); administrators can establish or retire them in any unit they manage. |
| Leadership | `AppointmentType.role` (commander, deputy, administrative, department head, department deputy) and `CommandAppointment.department`. New types: `TALIYE_GUUD`, `UNIT_DEPUTY`, `ADMIN_LEAD`, `DEPT_HEAD`, `DEPT_DEPUTY`. Existing types are classed (Taliye = commander, Abaanduule = deputy). Same rules as before: authority reference, one exclusive holder, ending revokes linked access. |
| Personnel | `Personnel.department` (optional; existing records stay empty). Filter `?department=`, `?no_department=1`, `?direct=1`, sort `?ordering=name|rank|service_number|status|department|unit` (prefix `-` to reverse). Department changes write personnel history and the audit log. |
| Profiles | `GET organization/units/{id}/profile/` (identification, parent, commander/deputy/administration, departments with head and deputy, medical and finance staff, sub-units, total/active/inactive, rank and department distribution) and `.../departments/{dept}/` (head, deputy, staff, assigned personnel). Both are audited reads. |
| Analytics | `GET organization/analytics/[?unit=]`: totals, active/inactive, strength by regional command / brigade / battalion, department staffing, leadership summary and vacancies, rank distribution. Aggregates only. |
| Screens | Units hub (chart, analytics, finder), unit profile (overview, leadership, departments, personnel directory), department profile, Structure settings, department on the personnel list, form and file, department offices in the appointments panel. English and Somali. |

## Permissions and security
* `orgprofile.configure` (new): department catalogue and formation roles. Held by `hq_admin` and `super_admin`.
* `departments.view_restricted` (new): see **named** staff of restricted departments (Finance and Medical by default; flag is editable). Without it, profiles show counts only and the personnel list/detail hide those people (own record and direct reports stay visible). Held by `hq_admin` and `super_admin`.
* Everything else reuses existing permissions and scope: `org.view`, `org.manage`, `personnel.view`, `personnel.manage`, `personnel.appointments_manage`, `analytics.view`. Restricted (confidential) units keep their existing gate. Names need `personnel.view`; callers who may only count see numbers.
* Salary and payment data are not exposed by any new endpoint. Phone numbers and personal profile data are not part of unit or directory views.
* Audit actions: `org_unit.profile_view`, `org_unit.department_view`, `org_analytics.view`, `department.create/update`, `unit_department.establish/update/retire`, `unit_type.formation_role`, `org.departments_established`, plus the existing personnel and appointment events.

## Later additions
* **Automatic departments:** a post-save rule (`organization/signals.py`) establishes the seven standard departments in every new or re-typed headquarters, region, regional command, brigade and battalion. It only fills what is missing, so a retired department stays retired. Ordinary sub-units are not included.
* **Bulk assignment:** `POST personnel/bulk-department/` (`{ids, department}`; `department: null` clears it) for up to 200 people. Each person is checked for scope and status; others are skipped and counted. One audit event plus a history row per person. UI: tick people in a unit's Personnel directory.
* **CSV import:** optional `department_code` column (e.g. `MEDICAL`); unknown codes fail the preview with `department_unknown`. Files without the column work as before. The export format is unchanged.
* **Department leadership:** appoint or end a department head/deputy directly on the department page.

## Definitions
Active = status `active`. Inactive = every other status. Total = all records in scope. The status breakdown is always shown beside them. (The older unit overview endpoint still reports *serving* strength and is unchanged.)

## Migrations
`organization/0012_departments_and_formation_roles`, `personnel/0011_department_and_appointment_roles`. Additive; the appointment uniqueness rule is split in two so department heads in different departments do not clash.

## Not done / to confirm
* Nothing in this delivery was executed: the build environment had no Django, PostgreSQL or npm packages. Run `python manage.py makemigrations --check`, `python manage.py test` and `npm run typecheck && npm test` before deploying.
* Somali strings are working translations.
* The Netlify preview mock has no data for the new endpoints.
* Existing records have no department until an administrator assigns one; the unit profile shows them as "No department".
