# Payroll and survivor-benefit policy: implementation status

**Nothing in this change has been executed.** The build environment had no Django, no database and no network, so no migration,
test or API call was run. Everything below is *written and syntax/name-checked only*. Run on your side before trusting it:

    cd backend
    python manage.py makemigrations --check      # migration 0003 was hand-written: this must report no drift
    python manage.py migrate && python manage.py seed_reference_data
    python manage.py test
    ops/migration_roundtrip.sh                    # existing-install check (see "Migration safety")

## Implemented (code written, tests written, NOT yet run)

| Requirement | Where | Tests |
|---|---|---|
| Died status keeps personnel, payroll and service history | existing death workflow; payroll lines are PROTECTed, never deleted | `DeceasedRetainedTests` |
| Priority wife+children > parents > siblings, enforced at registration and verification | `services.add_beneficiary`, `decide_beneficiary`, `eligible_tier` | `SurvivorPriorityTests` |
| Several beneficiaries in one class: verification by a different officer, amounts typed by an officer citing a decision, authorised by a third officer | existing verify/propose/authorize flow | `SurvivorPriorityTests`, `IndefiniteBenefitTests` |
| Survivor benefits indefinite: no end-date, duration, expiry or scheduled job | `BenefitAllocation.basis_kind=per_period`; `ended_on`/`held_from` set only by an approved `AllocationDecision`; DB check `allocation_end_only_when_terminated` | `IndefiniteBenefitTests` |
| Change/suspend/resume/terminate only by documented decision (reason, effective date, supporting ref, proposer, different approver, audit) | `AllocationDecision`, `/survivor-cases/{id}/decision/` | `IndefiniteBenefitTests` |
| Case closure only by documented decision, and only after every live benefit has been ended by its own decision | `services.close_case` | `IndefiniteBenefitTests` |
| Full salary for the month of death, no proration | `prepare_run` (`death_month`), `deceased_payable_line` | `MonthOfDeathTests` |
| Earlier unpaid salary tracked separately as arrears (record, verify, approve by three different people; own payment ledger; never mixed with runs or survivor payments; nothing forfeited) | `ArrearsClaim`, `ArrearsPayment`, `review.py` | `ArrearsTests` |
| Suspended/jailed flagged; deduction only from an approved Finance decision (see policy answers); decision record with reason, effective date, approver, document | `PayrollLine.status_flag`, `StatusPayDecision`, `/payroll/personnel/` | `SuspendedJailedTests` |
| Sahal and bank transfer: method, recipient, amount, currency, period, reference, status, approvals, reconciliation | `PaymentInstruction`, `PaymentEvent`, `payments.py`, `/payroll/payments/` | `PaymentMethodTests`, `PaymentWorkflowTests` |
| Separated duties: prepare, authorise, execute, reconcile (four permissions; service also blocks the same person) | roles `payroll_officer`, `payroll_approver`, `payment_officer`, `payment_reconciler` | `PaymentWorkflowTests`, `AccessControlTests` |
| Recipient details encrypted, masked, revealed only with `payment.details`, every reveal audited, never in audit metadata | `payments.reveal_details` | `PaymentWorkflowTests` |
| Beneficiary edits with reason; field names only in history and audit; record reads audited | `BeneficiaryChange`, `record_read` | `BeneficiaryChangeTests` |
| Unconfirmed rules kept configurable and listed for the policy authority | `PolicySetting`, `/payroll/policy/` (`payroll.policy_confirm`, super_admin only by default) | `PolicyConfigTests` |

The old direct "pay" endpoints were removed: every payment now goes through the instruction workflow.

## Requires external payment-provider integration (NOT implemented)
- **Sahal and every bank.** No API is integrated and none is claimed. The system does not send money. An authorised officer sends the
  payment outside the system and records the transaction reference; a different officer reconciles it against the Sahal/bank statement.
  `GET /payroll/payments/methods/` reports `integration: none` for both methods.
- Automatic statement import / matching: not built; reconciliation is typed in by the reconciler.

## Policy answers received (2026-10-23) and what the code does with them
All seven items are now confirmed in `/payroll/policy/`. **Every value is changeable later** with `POST /payroll/policy/{key}/revise/`
(`payroll.policy_confirm`, super_admin only by default; needs `value`, `authority_ref`, `reason`; old and new value go to the audit log;
lines already prepared are never rewritten).

| Item | Answer | Behaviour in code |
|---|---|---|
| Suspended/jailed pay | Paid, minus 5%, 10% or 20% by severity; **Finance decides the severity** | **Implemented.** A pay decision (`formal_decision`) carries `deduction_percent`, only a tier in `suspended_jailed_deduction_tiers` (editable). Once a second officer approves it, `prepare_run` deducts that % **of gross (confirmed)** from lines whose effective date has passed. No approved decision = no deduction, case stays flagged. |
| Division among beneficiaries | Priority order decides who is paid; Sharia law divides within the paid class | **Order enforced; division recorded only.** No share formula: each amount is typed citing the decision and authorized by a different officer. |
| Eligibility | Wife and children, then parents, then siblings | **Order enforced.** No age/marital rule applied automatically. |
| Priority after a higher class ceases | Same order: next class becomes eligible | **Enforced** by `eligible_tier`; each change needs a documented decision. |
| Recipient of death-month salary and arrears | Verified beneficiaries by priority order, Sharia division | **Order enforced;** only a verified beneficiary of the survivor case is paid. |
| Arrears limits | Finance decides | **Recorded only.** Every claim is verified and approved individually; nothing expires. |
| Currency | USD | **Recorded only.** Currency is still typed per profile/allocation and not forced to USD. |

### Open points to resolve
- Deduction base: **gross pay** (base + allowances), confirmed 2026-10-23. Nothing open.
- Sharia shares inside a class (e.g. several wives, sons and daughters) are not computed by the system.

## Not done
- Frontend screens now exist for payments, arrears and pay decisions (Payroll page tabs, English and draft Somali). Still **no screen** for the policy settings (`/payroll/policy/` is API only, apart from the deduction tiers read by the decision form), and no screen for entering salary components.
- No export of payroll or beneficiary data exists, by design (nothing to authorise).
- Payroll is headquarters-level ("global" grants) and covers Army and Police personnel alike; whether Police payroll must be separate is undecided.
- Negative (reversal) lines cannot be paid or collected through the payment workflow; recoveries are not modelled.
- Supporting documents are stored as reference strings, not uploaded files.

## Migration safety
- `0003` is additive: new tables; new columns on existing tables are nullable or defaulted. Existing `survivor_allocations` rows are given
  `basis_kind=lump_sum` (their original meaning, a total paid once); only new allocations default to the standing monthly entitlement.
- `0005` adds `deduction_percent` (default 0) and fills in rows still unconfirmed (rows an officer already confirmed are untouched).
- `0004` seeds policy rows (idempotent) and adds append-only DB triggers (PostgreSQL) for the new history tables.
- `0003` was written by hand; run `makemigrations --check` first. Verify on a copy of a real database *and* a clean one.

## Roles added or changed
`payroll_officer` (prepares; no longer pays), `payroll_approver` (+ decides pay decisions, authorises payments, approves arrears),
new `payment_officer` (executes, sees recipient details), new `payment_reconciler`. `payroll.pay` was removed. `payroll.policy_confirm` is held only by `super_admin`.
