# Role and permission catalogue

What each role in the system can do, taken from `seed_reference_data.py` (the definition the server applies when it is run).
A user's real power is the role **plus the scope** it is assigned over (a unit and everything below it, optionally one branch). The same role can mean a whole region for one person and one unit for another.

For the actual users, usernames and scopes in your database run:

`python manage.py access_report --format md --output access_report.md` (also `--format csv` for a spreadsheet).

25 roles, 71 permissions.

## Roles at a glance

| Role | Name | MFA | Can be assigned at | Permissions |
|---|---|---|---|---|
| `hq_admin` | Headquarters administrator | yes | headquarters | 16 |
| `hq_reporting` | Headquarters reporting user | no | headquarters | 11 |
| `regional_chief` | Regional chief | yes | region | 17 |
| `branch_admin` | Branch administrator | yes | region, branch_command (needs a branch) | 23 |
| `unit_admin` | Unit administrator | no | unit, branch_command, station | 11 |
| `reporting_officer` | Reporting officer | no | any level | 6 |
| `logistics_custodian` | Logistics custodian | no | any level | 6 |
| `training_admin` | Training administrator | no | any level | 6 |
| `restricted_custodian` | Restricted equipment custodian | yes | any level | 7 |
| `logistics_reviewer` | Institutional logistics reviewer | yes | headquarters | 4 |
| `structure_approver` | Structure approver | yes | headquarters | 3 |
| `cid_officer` | CID officer | yes | region, branch_command, unit (needs a branch) | 12 |
| `command_authority` | Command authority | yes | headquarters | 10 |
| `auditor` | Auditor | yes | headquarters | 3 |
| `super_admin` | Super administrator | yes | headquarters | 71 |
| `member` | Member (non-commanding) | no | any level | 4 |
| `unit_commander` | Unit commander (Taliye Guuto / Taliye Urur) | no | unit, station | 11 |
| `regional_commander` | Regional commander (Taliye Qaybeed) | yes | branch_command | 6 |
| `weapons_custodian` | Weapons custodian | yes | branch_command, unit | 8 |
| `payroll_officer` | Payroll officer | yes | headquarters | 9 |
| `payroll_approver` | Payroll approver | yes | headquarters | 10 |
| `payment_officer` | Payment execution officer | yes | headquarters | 6 |
| `payment_reconciler` | Payment reconciliation officer | yes | headquarters | 5 |
| `survivor_officer` | Survivor-benefit officer | yes | headquarters | 6 |
| `read_only` | Read-only user | no | any level | 5 |

## What each role can do

### Headquarters administrator (`hq_admin`)

MFA required: yes. Assigned at: headquarters.

- **Audit log:** `audit.view` Read audit events
- **Dashboard:** `dashboard.view` See the dashboard
- **Integrations:** `integrations.view` View integration clients and their call log (headquarters); `integrations.manage` Create, change, rotate and revoke integration clients (headquarters)
- **Logistics:** `logistics.configure` Create and edit inventory categories
- **Organization:** `org.view` View organization structure in scope; `org.manage` Change organization structure in scope; `org.structure_propose` Propose and submit changes to organizational levels and strength standards (headquarters)
- **Ranks:** `ranks.view` View rank catalogue; `ranks.manage` Edit rank catalogue entries; `ranks.approve` Approve rank catalogue entries
- **Reports:** `reports.configure` Configure request/report types
- **Roles:** `roles.assign` Assign and revoke scoped roles
- **Training:** `training.configure` Create and edit the course catalogue
- **Users and roles:** `users.view` View user accounts; `users.manage` Create, edit, disable user accounts

### Headquarters reporting user (`hq_reporting`)

MFA required: no. Assigned at: headquarters.

- **Analytics:** `analytics.view` Open analytics (each section still needs its own report/personnel/logistics/training permission)
- **Dashboard:** `dashboard.view` See the dashboard
- **Logistics:** `logistics.report` See logistics summaries in scope
- **Organization:** `org.view` View organization structure in scope
- **Personnel:** `personnel.view` View personnel records in scope; `personnel.export` Export personnel to CSV in scope (also needs PERSONNEL_EXPORT_ENABLED)
- **Ranks:** `ranks.view` View rank catalogue
- **Reports:** `reports.view` View requests/reports in scope; `reports.summary` See approved regional/headquarters summaries in scope; `reports.export` Export summaries (also needs REPORT_EXPORT_ENABLED)
- **Training:** `training.report` See training summaries in scope

### Regional chief (`regional_chief`)

MFA required: yes. Assigned at: region.

- **Analytics:** `analytics.view` Open analytics (each section still needs its own report/personnel/logistics/training permission)
- **Dashboard:** `dashboard.view` See the dashboard
- **Logistics:** `logistics.view` View stock and assets (non-restricted categories) in scope; `logistics.report` See logistics summaries in scope
- **Organization:** `org.view` View organization structure in scope
- **Personnel:** `personnel.view` View personnel records in scope; `personnel.manage` Create/edit personnel, transfers, rank and status changes in scope; `personnel.export` Export personnel to CSV in scope (also needs PERSONNEL_EXPORT_ENABLED); `personnel.record_death` Report a death and attach supporting evidence for personnel in scope (does not change status by itself)
- **Ranks:** `ranks.view` View rank catalogue
- **Reports:** `reports.view` View requests/reports in scope; `reports.review` Review, approve, reject or return reports in scope; `reports.summary` See approved regional/headquarters summaries in scope; `reports.export` Export summaries (also needs REPORT_EXPORT_ENABLED)
- **Training:** `training.view` View training records in scope; `training.report` See training summaries in scope
- **Weapons:** `weapons.view` View the weapon register (serial numbers, custody, condition, history) for units in scope

### Branch administrator (`branch_admin`)

MFA required: yes. Assigned at: region, branch_command; must be limited to one branch.

- **Analytics:** `analytics.view` Open analytics (each section still needs its own report/personnel/logistics/training permission)
- **Dashboard:** `dashboard.view` See the dashboard
- **Disciplinary:** `disciplinary.view` View a person's disciplinary history in scope (encrypted, every view is audited); `disciplinary.manage` Add disciplinary entries and corrections in scope (entries are append-only)
- **Documents:** `documents.view` List and download service documents on personnel files in scope (every access is audited); `documents.manage` Upload and withdraw service documents on personnel files in scope
- **Logistics:** `logistics.view` View stock and assets (non-restricted categories) in scope; `logistics.report` See logistics summaries in scope
- **Organization:** `org.view` View organization structure in scope; `org.manage` Change organization structure in scope
- **Personnel:** `personnel.view` View personnel records in scope; `personnel.manage` Create/edit personnel, transfers, rank and status changes in scope; `personnel.import` Import personnel from CSV in scope; `personnel.record_death` Report a death and attach supporting evidence for personnel in scope (does not change status by itself); `personnel.confirm_death` Confirm a reported death, which sets the status to Died (must be a different officer from the reporter); `personnel.appointments_manage` Appoint and end command appointments (Taliye Qaybeed, Taliye Urur ...) for units in scope; never grants access by itself
- **Ranks:** `ranks.view` View rank catalogue
- **Reports:** `reports.view` View requests/reports in scope; `reports.submit` Prepare and submit requests/reports in scope; `reports.review` Review, approve, reject or return reports in scope; `reports.summary` See approved regional/headquarters summaries in scope
- **Training:** `training.view` View training records in scope; `training.report` See training summaries in scope

### Unit administrator (`unit_admin`)

MFA required: no. Assigned at: unit, branch_command, station.

- **Dashboard:** `dashboard.view` See the dashboard
- **Logistics:** `logistics.view` View stock and assets (non-restricted categories) in scope
- **Organization:** `org.view` View organization structure in scope; `org.manage` Change organization structure in scope
- **Personnel:** `personnel.view` View personnel records in scope; `personnel.manage` Create/edit personnel, transfers, rank and status changes in scope; `personnel.record_death` Report a death and attach supporting evidence for personnel in scope (does not change status by itself)
- **Ranks:** `ranks.view` View rank catalogue
- **Reports:** `reports.view` View requests/reports in scope; `reports.submit` Prepare and submit requests/reports in scope
- **Training:** `training.view` View training records in scope

### Reporting officer (`reporting_officer`)

MFA required: no. Assigned at: any level.

- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope
- **Personnel:** `personnel.view` View personnel records in scope
- **Ranks:** `ranks.view` View rank catalogue
- **Reports:** `reports.view` View requests/reports in scope; `reports.submit` Prepare and submit requests/reports in scope

### Logistics custodian (`logistics_custodian`)

MFA required: no. Assigned at: any level.

- **Dashboard:** `dashboard.view` See the dashboard
- **Logistics:** `logistics.view` View stock and assets (non-restricted categories) in scope; `logistics.manage` Receive/issue/transfer stock and manage assets in scope; `logistics.reconcile` Run stock and asset reconciliations in scope; `logistics.report` See logistics summaries in scope
- **Organization:** `org.view` View organization structure in scope

### Training administrator (`training_admin`)

MFA required: no. Assigned at: any level.

- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope
- **Training:** `training.view` View training records in scope; `training.manage` Enrol people and update training records in scope; `training.report` See training summaries in scope; `training.configure` Create and edit the course catalogue

### Restricted equipment custodian (`restricted_custodian`)

MFA required: yes. Assigned at: any level.

- **Dashboard:** `dashboard.view` See the dashboard
- **Logistics:** `logistics.view` View stock and assets (non-restricted categories) in scope; `logistics.manage` Receive/issue/transfer stock and manage assets in scope; `logistics.restricted` Separately view/manage RESTRICTED equipment categories in scope; `logistics.reconcile` Run stock and asset reconciliations in scope; `logistics.report` See logistics summaries in scope
- **Organization:** `org.view` View organization structure in scope

### Institutional logistics reviewer (`logistics_reviewer`)

MFA required: yes. Assigned at: headquarters.

- **Dashboard:** `dashboard.view` See the dashboard
- **Logistics:** `logistics.approve` Approve (institutionally review) inventory categories; `logistics.restricted_approve` Approve RESTRICTED inventory categories
- **Organization:** `org.view` View organization structure in scope

### Structure approver (`structure_approver`)

MFA required: yes. Assigned at: headquarters.

- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope; `org.structure_approve` Approve or reject proposed structure changes (headquarters); cannot approve one's own proposal

### CID officer (`cid_officer`)

MFA required: yes. Assigned at: region, branch_command, unit; must be limited to one branch.

- **CID:** `cid.access` Reach personnel records inside restricted units. Never implied by any other permission
- **Dashboard:** `dashboard.view` See the dashboard
- **Disciplinary:** `disciplinary.view` View a person's disciplinary history in scope (encrypted, every view is audited); `disciplinary.manage` Add disciplinary entries and corrections in scope (entries are append-only)
- **Documents:** `documents.view` List and download service documents on personnel files in scope (every access is audited); `documents.manage` Upload and withdraw service documents on personnel files in scope
- **Organization:** `org.view` View organization structure in scope
- **Personnel:** `personnel.view` View personnel records in scope; `personnel.manage` Create/edit personnel, transfers, rank and status changes in scope
- **Ranks:** `ranks.view` View rank catalogue
- **Reports:** `reports.view` View requests/reports in scope; `reports.submit` Prepare and submit requests/reports in scope

### Command authority (`command_authority`)

MFA required: yes. Assigned at: headquarters.

- **Analytics:** `analytics.view` Open analytics (each section still needs its own report/personnel/logistics/training permission)
- **Cross-service search:** `search.cross_service` Search personnel across all services (Army and Navy) within the records the user is otherwise allowed to see
- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope
- **Personnel:** `personnel.view` View personnel records in scope
- **Ranks:** `ranks.view` View rank catalogue
- **Reports:** `reports.view` View requests/reports in scope; `reports.summary` See approved regional/headquarters summaries in scope; `reports.combined` See combined Army and Navy summaries (headquarters-wide; command authority). Aggregates only

### Auditor (`auditor`)

MFA required: yes. Assigned at: headquarters.

- **Audit log:** `audit.view` Read audit events
- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope

### Super administrator (`super_admin`)

MFA required: yes. Assigned at: headquarters.

- **Analytics:** `analytics.view` Open analytics (each section still needs its own report/personnel/logistics/training permission)
- **Arrears:** `arrears.manage` Record and verify arrears claims (earlier unpaid salary), kept apart from payroll and survivor benefits; `arrears.approve` Approve arrears claims (never one you recorded or verified)
- **Attendance:** `attendance.view` View attendance and absence records and summaries for personnel in scope; `attendance.record` Record and amend daily attendance for personnel in scope (never changes personnel status)
- **Audit log:** `audit.view` Read audit events
- **CID:** `cid.access` Reach personnel records inside restricted units. Never implied by any other permission
- **Cross-service search:** `search.cross_service` Search personnel across all services (Army and Navy) within the records the user is otherwise allowed to see
- **Dashboard:** `dashboard.view` See the dashboard
- **Disciplinary:** `disciplinary.view` View a person's disciplinary history in scope (encrypted, every view is audited); `disciplinary.manage` Add disciplinary entries and corrections in scope (entries are append-only)
- **Documents:** `documents.view` List and download service documents on personnel files in scope (every access is audited); `documents.manage` Upload and withdraw service documents on personnel files in scope
- **Integrations:** `integrations.view` View integration clients and their call log (headquarters); `integrations.manage` Create, change, rotate and revoke integration clients (headquarters)
- **Logistics:** `logistics.view` View stock and assets (non-restricted categories) in scope; `logistics.manage` Receive/issue/transfer stock and manage assets in scope; `logistics.restricted` Separately view/manage RESTRICTED equipment categories in scope; `logistics.reconcile` Run stock and asset reconciliations in scope; `logistics.report` See logistics summaries in scope; `logistics.configure` Create and edit inventory categories; `logistics.approve` Approve (institutionally review) inventory categories; `logistics.restricted_approve` Approve RESTRICTED inventory categories
- **Organization:** `org.view` View organization structure in scope; `org.manage` Change organization structure in scope; `org.structure_propose` Propose and submit changes to organizational levels and strength standards (headquarters); `org.structure_approve` Approve or reject proposed structure changes (headquarters); cannot approve one's own proposal
- **Payments:** `payment.prepare` Prepare Sahal / bank-transfer payment instructions against approved amounts; `payment.authorize` Authorize a prepared payment (never one you prepared); `payment.execute` Send an authorized payment outside the system and record its outcome (never one you authorized); `payment.reconcile` Reconcile paid payments with provider or bank statements (never one you executed); `payment.details` See the full recipient details (mobile number, bank account) of a payment; every reveal is audited
- **Payroll:** `payroll.view` View salary profiles, payroll runs and payment status (headquarters finance); `payroll.manage` Propose salary profiles; prepare, submit and adjust payroll runs; `payroll.approve` Approve salary profiles and payroll runs (never your own work); `payroll.review` Record pay decisions for suspended and jailed personnel (a record only: never changes pay by itself); `payroll.decide` Approve or reject pay decisions for suspended and jailed personnel (never your own entry); `payroll.policy_confirm` Confirm or later revise a payroll or survivor policy value, with authority reference and reason (policy authority)
- **Personnel:** `personnel.view` View personnel records in scope; `personnel.view_team` View your own personnel record and your direct subordinates' records (read-only, within the assignment's scope); `personnel.appointments_manage` Appoint and end command appointments (Taliye Qaybeed, Taliye Urur ...) for units in scope; never grants access by itself; `personnel.record_death` Report a death and attach supporting evidence for personnel in scope (does not change status by itself); `personnel.confirm_death` Confirm a reported death, which sets the status to Died (must be a different officer from the reporter); `personnel.manage` Create/edit personnel, transfers, rank and status changes in scope; `personnel.import` Import personnel from CSV in scope; `personnel.export` Export personnel to CSV in scope (also needs PERSONNEL_EXPORT_ENABLED)
- **Ranks:** `ranks.view` View rank catalogue; `ranks.manage` Edit rank catalogue entries; `ranks.approve` Approve rank catalogue entries
- **Reports:** `reports.view` View requests/reports in scope; `reports.submit` Prepare and submit requests/reports in scope; `reports.review` Review, approve, reject or return reports in scope; `reports.summary` See approved regional/headquarters summaries in scope; `reports.export` Export summaries (also needs REPORT_EXPORT_ENABLED); `reports.configure` Configure request/report types; `reports.combined` See combined Army and Navy summaries (headquarters-wide; command authority). Aggregates only
- **Roles:** `roles.assign` Assign and revoke scoped roles
- **Survivor benefits:** `survivor.view` View survivor-benefit cases and beneficiaries; `survivor.manage` Open survivor cases, register beneficiaries, propose allocations, raise disputes; `survivor.verify` Verify or reject beneficiaries and mark a case verified; `survivor.approve` Authorize survivor allocations and close cases (never your own proposal)
- **System:** `system.full_access` Maintenance override: reach every part of the system even where a module switch (for example a module switch being off) would hide it. Super administrator only; every action stays in the audit log
- **Training:** `training.view` View training records in scope; `training.manage` Enrol people and update training records in scope; `training.report` See training summaries in scope; `training.configure` Create and edit the course catalogue
- **Users and roles:** `users.view` View user accounts; `users.manage` Create, edit, disable user accounts
- **Weapons:** `weapons.view` View the weapon register (serial numbers, custody, condition, history) for units in scope; `weapons.manage` Register weapons, issue them to personnel, take them back and record condition for units in scope

### Member (non-commanding) (`member`)

MFA required: no. Assigned at: any level.

- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope
- **Personnel:** `personnel.view_team` View your own personnel record and your direct subordinates' records (read-only, within the assignment's scope)
- **Ranks:** `ranks.view` View rank catalogue

### Unit commander (Taliye Guuto / Taliye Urur) (`unit_commander`)

MFA required: no. Assigned at: unit, station.

- **Attendance:** `attendance.view` View attendance and absence records and summaries for personnel in scope; `attendance.record` Record and amend daily attendance for personnel in scope (never changes personnel status)
- **Dashboard:** `dashboard.view` See the dashboard
- **Logistics:** `logistics.view` View stock and assets (non-restricted categories) in scope; `logistics.restricted` Separately view/manage RESTRICTED equipment categories in scope
- **Organization:** `org.view` View organization structure in scope
- **Personnel:** `personnel.view` View personnel records in scope
- **Ranks:** `ranks.view` View rank catalogue
- **Reports:** `reports.view` View requests/reports in scope; `reports.submit` Prepare and submit requests/reports in scope
- **Weapons:** `weapons.view` View the weapon register (serial numbers, custody, condition, history) for units in scope

### Regional commander (Taliye Qaybeed) (`regional_commander`)

MFA required: yes. Assigned at: branch_command.

- **Attendance:** `attendance.view` View attendance and absence records and summaries for personnel in scope
- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope
- **Personnel:** `personnel.view` View personnel records in scope
- **Ranks:** `ranks.view` View rank catalogue
- **Reports:** `reports.view` View requests/reports in scope

### Weapons custodian (`weapons_custodian`)

MFA required: yes. Assigned at: branch_command, unit.

- **Dashboard:** `dashboard.view` See the dashboard
- **Logistics:** `logistics.view` View stock and assets (non-restricted categories) in scope; `logistics.manage` Receive/issue/transfer stock and manage assets in scope; `logistics.restricted` Separately view/manage RESTRICTED equipment categories in scope
- **Organization:** `org.view` View organization structure in scope
- **Ranks:** `ranks.view` View rank catalogue
- **Weapons:** `weapons.view` View the weapon register (serial numbers, custody, condition, history) for units in scope; `weapons.manage` Register weapons, issue them to personnel, take them back and record condition for units in scope

### Payroll officer (`payroll_officer`)

MFA required: yes. Assigned at: headquarters.

- **Arrears:** `arrears.manage` Record and verify arrears claims (earlier unpaid salary), kept apart from payroll and survivor benefits
- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope
- **Payments:** `payment.prepare` Prepare Sahal / bank-transfer payment instructions against approved amounts
- **Payroll:** `payroll.view` View salary profiles, payroll runs and payment status (headquarters finance); `payroll.manage` Propose salary profiles; prepare, submit and adjust payroll runs; `payroll.review` Record pay decisions for suspended and jailed personnel (a record only: never changes pay by itself)
- **Ranks:** `ranks.view` View rank catalogue
- **Survivor benefits:** `survivor.view` View survivor-benefit cases and beneficiaries

### Payroll approver (`payroll_approver`)

MFA required: yes. Assigned at: headquarters.

- **Arrears:** `arrears.approve` Approve arrears claims (never one you recorded or verified)
- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope
- **Payments:** `payment.authorize` Authorize a prepared payment (never one you prepared)
- **Payroll:** `payroll.view` View salary profiles, payroll runs and payment status (headquarters finance); `payroll.approve` Approve salary profiles and payroll runs (never your own work); `payroll.decide` Approve or reject pay decisions for suspended and jailed personnel (never your own entry)
- **Ranks:** `ranks.view` View rank catalogue
- **Survivor benefits:** `survivor.view` View survivor-benefit cases and beneficiaries; `survivor.approve` Authorize survivor allocations and close cases (never your own proposal)

### Payment execution officer (`payment_officer`)

MFA required: yes. Assigned at: headquarters.

- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope
- **Payments:** `payment.execute` Send an authorized payment outside the system and record its outcome (never one you authorized); `payment.details` See the full recipient details (mobile number, bank account) of a payment; every reveal is audited
- **Payroll:** `payroll.view` View salary profiles, payroll runs and payment status (headquarters finance)
- **Ranks:** `ranks.view` View rank catalogue

### Payment reconciliation officer (`payment_reconciler`)

MFA required: yes. Assigned at: headquarters.

- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope
- **Payments:** `payment.reconcile` Reconcile paid payments with provider or bank statements (never one you executed)
- **Payroll:** `payroll.view` View salary profiles, payroll runs and payment status (headquarters finance)
- **Ranks:** `ranks.view` View rank catalogue

### Survivor-benefit officer (`survivor_officer`)

MFA required: yes. Assigned at: headquarters.

- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope
- **Ranks:** `ranks.view` View rank catalogue
- **Survivor benefits:** `survivor.view` View survivor-benefit cases and beneficiaries; `survivor.manage` Open survivor cases, register beneficiaries, propose allocations, raise disputes; `survivor.verify` Verify or reject beneficiaries and mark a case verified

### Read-only user (`read_only`)

MFA required: no. Assigned at: any level.

- **Dashboard:** `dashboard.view` See the dashboard
- **Organization:** `org.view` View organization structure in scope
- **Personnel:** `personnel.view` View personnel records in scope
- **Ranks:** `ranks.view` View rank catalogue
- **Reports:** `reports.view` View requests/reports in scope

## Permission dictionary

| Permission | Meaning |
|---|---|
| `analytics.view` | Open analytics (each section still needs its own report/personnel/logistics/training permission) |
| `arrears.approve` | Approve arrears claims (never one you recorded or verified) |
| `arrears.manage` | Record and verify arrears claims (earlier unpaid salary), kept apart from payroll and survivor benefits |
| `attendance.record` | Record and amend daily attendance for personnel in scope (never changes personnel status) |
| `attendance.view` | View attendance and absence records and summaries for personnel in scope |
| `audit.view` | Read audit events |
| `cid.access` | Reach personnel records inside restricted units. Never implied by any other permission |
| `dashboard.view` | See the dashboard |
| `disciplinary.manage` | Add disciplinary entries and corrections in scope (entries are append-only) |
| `disciplinary.view` | View a person's disciplinary history in scope (encrypted, every view is audited) |
| `documents.manage` | Upload and withdraw service documents on personnel files in scope |
| `documents.view` | List and download service documents on personnel files in scope (every access is audited) |
| `integrations.manage` | Create, change, rotate and revoke integration clients (headquarters) |
| `integrations.view` | View integration clients and their call log (headquarters) |
| `logistics.approve` | Approve (institutionally review) inventory categories |
| `logistics.configure` | Create and edit inventory categories |
| `logistics.manage` | Receive/issue/transfer stock and manage assets in scope |
| `logistics.reconcile` | Run stock and asset reconciliations in scope |
| `logistics.report` | See logistics summaries in scope |
| `logistics.restricted` | Separately view/manage RESTRICTED equipment categories in scope |
| `logistics.restricted_approve` | Approve RESTRICTED inventory categories |
| `logistics.view` | View stock and assets (non-restricted categories) in scope |
| `org.manage` | Change organization structure in scope |
| `org.structure_approve` | Approve or reject proposed structure changes (headquarters); cannot approve one's own proposal |
| `org.structure_propose` | Propose and submit changes to organizational levels and strength standards (headquarters) |
| `org.view` | View organization structure in scope |
| `payment.authorize` | Authorize a prepared payment (never one you prepared) |
| `payment.details` | See the full recipient details (mobile number, bank account) of a payment; every reveal is audited |
| `payment.execute` | Send an authorized payment outside the system and record its outcome (never one you authorized) |
| `payment.prepare` | Prepare Sahal / bank-transfer payment instructions against approved amounts |
| `payment.reconcile` | Reconcile paid payments with provider or bank statements (never one you executed) |
| `payroll.approve` | Approve salary profiles and payroll runs (never your own work) |
| `payroll.decide` | Approve or reject pay decisions for suspended and jailed personnel (never your own entry) |
| `payroll.manage` | Propose salary profiles; prepare, submit and adjust payroll runs |
| `payroll.policy_confirm` | Confirm or later revise a payroll or survivor policy value, with authority reference and reason (policy authority) |
| `payroll.review` | Record pay decisions for suspended and jailed personnel (a record only: never changes pay by itself) |
| `payroll.view` | View salary profiles, payroll runs and payment status (headquarters finance) |
| `personnel.appointments_manage` | Appoint and end command appointments (Taliye Qaybeed, Taliye Urur ...) for units in scope; never grants access by itself |
| `personnel.confirm_death` | Confirm a reported death, which sets the status to Died (must be a different officer from the reporter) |
| `personnel.export` | Export personnel to CSV in scope (also needs PERSONNEL_EXPORT_ENABLED) |
| `personnel.import` | Import personnel from CSV in scope |
| `personnel.manage` | Create/edit personnel, transfers, rank and status changes in scope |
| `personnel.record_death` | Report a death and attach supporting evidence for personnel in scope (does not change status by itself) |
| `personnel.view` | View personnel records in scope |
| `personnel.view_team` | View your own personnel record and your direct subordinates' records (read-only, within the assignment's scope) |
| `ranks.approve` | Approve rank catalogue entries |
| `ranks.manage` | Edit rank catalogue entries |
| `ranks.view` | View rank catalogue |
| `reports.combined` | See combined Army and Navy summaries (headquarters-wide; command authority). Aggregates only |
| `reports.configure` | Configure request/report types |
| `reports.export` | Export summaries (also needs REPORT_EXPORT_ENABLED) |
| `reports.review` | Review, approve, reject or return reports in scope |
| `reports.submit` | Prepare and submit requests/reports in scope |
| `reports.summary` | See approved regional/headquarters summaries in scope |
| `reports.view` | View requests/reports in scope |
| `roles.assign` | Assign and revoke scoped roles |
| `search.cross_service` | Search personnel across all services (Army and Navy) within the records the user is otherwise allowed to see |
| `survivor.approve` | Authorize survivor allocations and close cases (never your own proposal) |
| `survivor.manage` | Open survivor cases, register beneficiaries, propose allocations, raise disputes |
| `survivor.verify` | Verify or reject beneficiaries and mark a case verified |
| `survivor.view` | View survivor-benefit cases and beneficiaries |
| `system.full_access` | Maintenance override: reach every part of the system even where a module switch (for example a module switch being off) would hide it. Super administrator only; every action stays in the audit log |
| `training.configure` | Create and edit the course catalogue |
| `training.manage` | Enrol people and update training records in scope |
| `training.report` | See training summaries in scope |
| `training.view` | View training records in scope |
| `users.manage` | Create, edit, disable user accounts |
| `users.view` | View user accounts |
| `weapons.manage` | Register weapons, issue them to personnel, take them back and record condition for units in scope |
| `weapons.view` | View the weapon register (serial numbers, custody, condition, history) for units in scope |