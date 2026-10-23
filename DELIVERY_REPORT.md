> **Superseded by `docs/PAYROLL_POLICY_IMPLEMENTATION.md`** for the confirmed payroll and survivor policy (payments, arrears, indefinite benefits).
> The status below describes the earlier slice; "one-off allocation caps" and "never paid via ordinary payroll" no longer apply.

# Delivery report: payroll, survivor benefits, read-auditing (backend slice)

**Status: written and syntax-checked only. NOT run.** Django and a database were not available in the build environment
(no network), so no migration, test or API call has been executed. Nothing below should be treated as verified until
`python manage.py migrate && python manage.py seed_reference_data && python manage.py test` passes on your side.

## What already existed (reused, not rebuilt)
- Report workflow: Submission -> under_review -> approved / returned / rejected, immutable revisions and approval actions,
  scoped `reports.review`, self-review ban. Attendance is approved through the periodic situation report (unchanged).
- Death workflow: report + confirmation by a different officer with evidence; status Died; history preserved.
- Weapon register scoped by `weapons.view` / `weapons.manage`; append-only custody and asset events.
- Append-only audit log readable only by global `audit.view`.
- There was NO payroll, salary or beneficiary module, and no finance ledger to integrate with.

## Added
**Read auditing** (`audit.services.record_read`): weapon list/detail/summary and attendance roll/records/summary now write
`weapon.read_*` / `attendance.read_*` events (user, resource, scope unit, count, timestamp; no serials or personal data).
Also `payroll.read_*` and `survivor.read_*`.

**`apps/payroll`** (migrations 0001 tables + constraints, 0002 append-only DB triggers on Postgres):
- Salary scales (no amounts seeded), salary profiles (effective-dated, never edited; proposer != approver; document ref required).
- Periods, runs, lines. Calculated net, approved net and paid (sum of transactions) are separate. One regular line per person
  per period (DB constraint) and one live regular run per period. Exceptions list records who was excluded and why.
- Approval: preparer != approver; approved/paid runs are final; corrections only via reversal/adjustment lines that reference
  the original. Payments are append-only, capped at the approved amount.
- Deceased soldiers: excluded from ordinary runs; payment against their old lines is refused; their history stays.
- Survivor cases open only for a confirmed death. Beneficiaries (wife/child, parent, sibling) need a different officer to verify.
  Priority is enforced: a lower class cannot be allocated while a higher class is pending or verified. Allocation amounts are typed
  by an officer and must cite a policy reference; a different officer authorises; payments are recorded separately from payroll;
  disputes block payment. Payee details are encrypted. No automatic calculation exists, by design.
- New roles: `payroll_officer`, `payroll_approver`, `survivor_officer` (HQ level, privileged/MFA). New permissions `payroll.*`, `survivor.*`.
- Regional chief gained `weapons.view` (scoped to its region).
- Dashboard: `payroll` block (counts only, only for holders of the permissions) and `returned_for_correction` in the reports block.
- Existing test `test_v2_compatibility` updated for the new roles/permission; new `payroll/tests/test_payroll.py`.

## Not done
- No frontend screens (payroll, beneficiaries, review UI, dashboard cards), no Somali/English strings, no responsive/browser testing.
- No dependency/vulnerability scan, no backup/restore drill, no pen-test of direct requests beyond the written tests.
- Headquarters report reviewer: no existing HQ role holds `reports.review`; not changed (see decisions).
- Weapon custody/ammunition write restrictions were not modified; existing behaviour assumed adequate but not re-audited.
- Salary-profile supporting documents are stored as a reference string, not an uploaded file.

## Decisions needed from army personnel
1. Allocation rules among wives/children/parents/siblings, amounts, duration of survivor pay: left manual; no formulas.
2. Treatment of suspended/jailed soldiers in payroll (currently included but flagged `status_needs_decision`).
3. Pay for the month of death and unpaid prior salary (currently never paid via ordinary payroll; review note required on the case).
4. Which HQ role may review reports and which HQ roles may view detailed weapon registers.
5. Currency, payroll authority names, and whether payroll/survivor work should be regional rather than HQ-only.
6. Whether a one-person-holds-two-roles setup is acceptable (code blocks self-approval regardless).
