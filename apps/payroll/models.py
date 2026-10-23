"""Payroll and survivor benefits.

Nothing here invents money: salary scales, base amounts, allowances, deductions and survivor allocations are all entered by
authorized officers and approved by a different officer. Calculated, approved and paid amounts are separate columns/tables.
Finalised records are never edited: corrections are new adjustment/reversal lines, payments are append-only transactions.
"""
import uuid
from decimal import Decimal

from django.db import models
from django.db.models import Q

from apps.core.appendonly import AppendOnlyModel


class SalaryScale(models.Model):
    """An authorized salary scale/grade supplied by the institution (data, not code). No amounts are seeded."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    base_amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    authority_ref = models.CharField(max_length=200)  # the order/decree that approves this scale
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payroll_salary_scales"
        ordering = ["code"]
        constraints = [models.CheckConstraint(condition=Q(base_amount__gte=0), name="scale_amount_nonneg")]


class SalaryProfile(models.Model):
    """One approved salary position for one person from `effective_from`. Never edited once approved: a change is a new
    profile with a later effective date, so the full history stays. The profile in force for a period is the approved one with
    the latest effective_from on or before the period's end."""

    class Status(models.TextChoices):
        PENDING = "pending"
        APPROVED = "approved"
        REJECTED = "rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="salary_profiles")
    scale = models.ForeignKey(SalaryScale, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    base_amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    components = models.JSONField(default=list, blank=True)  # [{"kind": "allowance"|"deduction", "name": str, "amount": str}]
    effective_from = models.DateField()
    authority_ref = models.CharField(max_length=200)  # supporting documentation reference (order, letter number)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_by_id = models.UUIDField(null=True, blank=True)
    created_by_username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_by_id = models.UUIDField(null=True, blank=True)
    decided_by_username = models.CharField(max_length=150, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "payroll_salary_profiles"
        ordering = ["-effective_from", "-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(base_amount__gte=0), name="profile_amount_nonneg"),
            models.UniqueConstraint(fields=["personnel", "effective_from"], condition=~Q(status="rejected"),
                                    name="profile_one_per_person_date"),
            models.CheckConstraint(condition=~Q(status="approved") | Q(decided_by_id__isnull=False), name="profile_approved_has_approver"),
        ]


class PayrollPeriod(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()

    class Meta:
        db_table = "payroll_periods"
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(fields=["year", "month"], name="payroll_period_unique"),
            models.CheckConstraint(condition=Q(month__gte=1) & Q(month__lte=12), name="payroll_period_month"),
        ]


class PayrollRun(models.Model):
    class Kind(models.TextChoices):
        REGULAR = "regular"
        ADJUSTMENT = "adjustment"  # corrections/reversals; never a second regular run for the same period

    class Status(models.TextChoices):
        PREPARED = "prepared"
        SUBMITTED = "submitted"
        APPROVED = "approved"
        PAID = "paid"
        CANCELLED = "cancelled"  # only a prepared/submitted run can be cancelled; approved/paid runs are never removed

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    period = models.ForeignKey(PayrollPeriod, on_delete=models.PROTECT, related_name="runs")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.REGULAR)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PREPARED, db_index=True)
    exceptions = models.JSONField(default=list, blank=True)  # validation findings: who was left out or flagged, and why
    prepared_by_id = models.UUIDField(null=True, blank=True)
    prepared_by_username = models.CharField(max_length=150, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payroll_runs"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["period"], condition=Q(kind="regular") & ~Q(status="cancelled"),
                                    name="one_live_regular_run_per_period"),
        ]


class PayrollLine(models.Model):
    """calculated_net = what the system computed; approved_net = what an approver authorised; paid = sum of transactions."""

    class Kind(models.TextChoices):
        REGULAR = "regular"
        ADJUSTMENT = "adjustment"
        REVERSAL = "reversal"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="lines")
    period = models.ForeignKey(PayrollPeriod, on_delete=models.PROTECT, related_name="+")
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="payroll_lines")
    profile = models.ForeignKey(SalaryProfile, null=True, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.REGULAR)
    adjusts = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="corrections")
    reason = models.CharField(max_length=300, blank=True)
    currency = models.CharField(max_length=3)
    base = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    allowances = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    deductions = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    gross = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0"))
    calculated_net = models.DecimalField(max_digits=14, decimal_places=2)
    approved_net = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    # Snapshot of the person at preparation, so history survives later transfers/status changes.
    org_unit = models.ForeignKey("organization.OrganizationalUnit", on_delete=models.PROTECT, related_name="+")
    service_number = models.CharField(max_length=32, blank=True)
    # Review flag copied from the personnel status at preparation ("suspended"/"jailed"/""). It NEVER changes the amount.
    status_flag = models.CharField(max_length=10, blank=True, default="")
    # True when this is the full, unprorated salary for the month in which the soldier died.
    death_month = models.BooleanField(default=False)

    class Meta:
        db_table = "payroll_lines"
        ordering = ["personnel_id", "kind"]
        constraints = [
            models.UniqueConstraint(fields=["period", "personnel"], condition=Q(kind="regular"), name="one_regular_line_per_person_period"),
            models.CheckConstraint(condition=Q(kind="regular") | Q(adjusts__isnull=False), name="correction_references_original"),
        ]


class PaymentTransaction(AppendOnlyModel):
    """Money actually paid (positive) or paid back/reversed (negative). Append-only: a wrong entry is offset, never edited."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    line = models.ForeignKey(PayrollLine, on_delete=models.PROTECT, related_name="transactions")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=80, blank=True)  # finance system / bank transaction reference, when available
    paid_on = models.DateField()
    paid_by_id = models.UUIDField(null=True, blank=True)
    paid_by_username = models.CharField(max_length=150, blank=True)
    note = models.CharField(max_length=300, blank=True)
    instruction = models.ForeignKey("payroll.PaymentInstruction", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payroll_transactions"
        ordering = ["created_at"]
        constraints = [models.CheckConstraint(condition=~Q(amount=0), name="payment_nonzero")]


class PayrollAction(AppendOnlyModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run = models.ForeignKey(PayrollRun, on_delete=models.PROTECT, related_name="actions")
    action = models.CharField(max_length=16)
    from_status = models.CharField(max_length=10, blank=True)
    to_status = models.CharField(max_length=10)
    actor_id = models.UUIDField(null=True, blank=True)
    actor_username = models.CharField(max_length=150, blank=True)
    comment = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payroll_run_actions"
        ordering = ["created_at"]


# ---------------------------------------------------------------- survivor benefits

class SurvivorCase(models.Model):
    """Opened only for a CONFIRMED death. Holds the review of outstanding salary and the dispute state. Separate from the
    deceased's payroll history, which is never touched."""

    class Status(models.TextChoices):
        OPEN = "open"
        VERIFIED = "verified"   # beneficiaries verified and outstanding salary reviewed
        DISPUTED = "disputed"   # no allocation can be authorised or paid while disputed
        CLOSED = "closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="survivor_cases")
    death_record = models.ForeignKey("personnel.DeathRecord", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN, db_index=True)
    outstanding_review = models.CharField(max_length=1000, blank=True)  # review of unpaid salary / other amounts due
    dispute_note = models.CharField(max_length=500, blank=True)
    opened_by_id = models.UUIDField(null=True, blank=True)
    opened_by_username = models.CharField(max_length=150, blank=True)
    verified_by_id = models.UUIDField(null=True, blank=True)
    verified_by_username = models.CharField(max_length=150, blank=True)
    closed_by_username = models.CharField(max_length=150, blank=True)
    # A case is closed only by a documented decision (never by time passing).
    closure_reason = models.CharField(max_length=500, blank=True)
    closure_effective_date = models.DateField(null=True, blank=True)
    closure_ref = models.CharField(max_length=200, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "survivor_cases"
        ordering = ["-created_at"]
        constraints = [models.UniqueConstraint(fields=["personnel"], condition=~Q(status="closed"), name="one_open_survivor_case")]


class Beneficiary(models.Model):
    class Relationship(models.TextChoices):
        WIFE = "wife"
        CHILD = "child"
        PARENT = "parent"
        SIBLING = "sibling"

    class State(models.TextChoices):
        PENDING = "pending"
        VERIFIED = "verified"
        REJECTED = "rejected"

    TIER = {"wife": 1, "child": 1, "parent": 2, "sibling": 3}  # 1 wife+children, 2 parents, 3 siblings

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(SurvivorCase, on_delete=models.PROTECT, related_name="beneficiaries")
    full_name = models.CharField(max_length=150)
    relationship = models.CharField(max_length=8, choices=Relationship.choices)
    identity_ref = models.CharField(max_length=80)           # identity document reference
    evidence_ref = models.CharField(max_length=200)          # relationship-proof document reference
    payment_details_enc = models.TextField(blank=True)       # encrypted: payee account / collection details
    state = models.CharField(max_length=10, choices=State.choices, default=State.PENDING)
    decided_by_id = models.UUIDField(null=True, blank=True)
    decided_by_username = models.CharField(max_length=150, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)
    created_by_username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "survivor_beneficiaries"
        ordering = ["created_at"]

    @property
    def tier(self):
        return self.TIER[self.relationship]


class BenefitAllocation(models.Model):
    """An amount an authorized officer allocates to one beneficiary. The amount is typed by an officer under confirmed army
    policy (basis_ref); the system never derives it. Proposed by one officer, authorised by a different one."""

    class Status(models.TextChoices):
        PROPOSED = "proposed"
        AUTHORIZED = "authorized"
        CANCELLED = "cancelled"    # a proposal that was never authorised
        SUSPENDED = "suspended"    # only by an approved AllocationDecision
        TERMINATED = "terminated"  # only by an approved AllocationDecision; history stays

    class Basis(models.TextChoices):
        PER_PERIOD = "per_period"  # standing monthly entitlement: INDEFINITE, no end date unless a documented decision sets one
        LUMP_SUM = "lump_sum"      # a one-off total (kept for rows created before the indefinite policy)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    beneficiary = models.ForeignKey(Beneficiary, on_delete=models.PROTECT, related_name="allocations")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    basis_ref = models.CharField(max_length=200)  # the confirmed policy/order this amount follows
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PROPOSED)
    proposed_by_id = models.UUIDField(null=True, blank=True)
    proposed_by_username = models.CharField(max_length=150, blank=True)
    authorized_by_id = models.UUIDField(null=True, blank=True)
    authorized_by_username = models.CharField(max_length=150, blank=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    basis_kind = models.CharField(max_length=10, choices=Basis.choices, default=Basis.PER_PERIOD)
    effective_from = models.DateField(null=True, blank=True)
    # Set ONLY when an approved AllocationDecision terminates/suspends the benefit. There is deliberately no preset end date,
    # no duration and no scheduled job that fills these in.
    held_from = models.DateField(null=True, blank=True)
    ended_on = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "survivor_allocations"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="allocation_positive"),
            models.CheckConstraint(condition=~Q(status="authorized") | Q(authorized_by_id__isnull=False), name="allocation_authorized_has_approver"),
            models.CheckConstraint(condition=Q(ended_on__isnull=True) | Q(status="terminated"), name="allocation_end_only_when_terminated"),
        ]


class SurvivorPayment(AppendOnlyModel):
    """A payment to a beneficiary against an authorised allocation. Separate from the soldier's payroll transactions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    allocation = models.ForeignKey(BenefitAllocation, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=80, blank=True)
    paid_on = models.DateField()
    paid_by_id = models.UUIDField(null=True, blank=True)
    paid_by_username = models.CharField(max_length=150, blank=True)
    note = models.CharField(max_length=300, blank=True)
    period_year = models.PositiveSmallIntegerField(null=True, blank=True)   # the month this payment is for (standing benefits)
    period_month = models.PositiveSmallIntegerField(null=True, blank=True)
    instruction = models.ForeignKey("payroll.PaymentInstruction", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "survivor_payments"
        ordering = ["created_at"]
        constraints = [models.CheckConstraint(condition=~Q(amount=0), name="survivor_payment_nonzero")]


# ---------------------------------------------------------------- configurable policy

class PolicySetting(models.Model):
    """A rule the institution has or has not confirmed. Values are changeable later by the policy authority through `revise`
    (authority reference and reason required; old and new value are audited)."""

    class Status(models.TextChoices):
        CONFIRMED = "confirmed"
        UNCONFIRMED = "unconfirmed"

    key = models.CharField(max_length=60, primary_key=True)
    title = models.CharField(max_length=160)
    description = models.CharField(max_length=500)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.UNCONFIRMED)
    value = models.CharField(max_length=300, blank=True)
    authority_ref = models.CharField(max_length=200, blank=True)
    confirmed_by_username = models.CharField(max_length=150, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "payroll_policy_settings"
        ordering = ["key"]


# ---------------------------------------------------------------- suspended / jailed review

class StatusPayDecision(models.Model):
    """A documented decision on the pay of a suspended or jailed soldier. It is a RECORD: nothing here changes a salary by
    itself. Any actual change goes through the normal salary-profile / adjustment approvals. Rows are never deleted."""

    class Kind(models.TextChoices):
        RETAIN_EXISTING = "retain_existing"   # keep the existing payroll treatment (the default until an official rule exists)
        FORMAL_DECISION = "formal_decision"   # an authority's decision, described in decision_text, with supporting document

    class State(models.TextChoices):
        RECORDED = "recorded"
        APPROVED = "approved"
        REJECTED = "rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="pay_decisions")
    status_at_decision = models.CharField(max_length=12)
    kind = models.CharField(max_length=20, choices=Kind.choices)
    decision_text = models.CharField(max_length=500, blank=True)
    deduction_percent = models.PositiveSmallIntegerField(default=0)  # tier chosen by Finance; must be one of the policy tiers (or 0)
    reason = models.CharField(max_length=500)
    effective_date = models.DateField()
    supporting_ref = models.CharField(max_length=200, blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.RECORDED)
    recorded_by_id = models.UUIDField(null=True, blank=True)
    recorded_by_username = models.CharField(max_length=150, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)
    decided_by_id = models.UUIDField(null=True, blank=True)
    decided_by_username = models.CharField(max_length=150, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "payroll_status_decisions"
        ordering = ["-recorded_at"]
        constraints = [models.CheckConstraint(condition=~Q(state="approved") | Q(decided_by_id__isnull=False),
                                              name="status_decision_approved_has_approver")]


# ---------------------------------------------------------------- arrears

class ArrearsClaim(models.Model):
    """Unpaid salary from earlier periods, tracked on its own: never merged into a run or a survivor benefit and never
    forfeited automatically. The amount is typed from the source documents, verified, then approved by different officers."""

    class Status(models.TextChoices):
        RECORDED = "recorded"
        VERIFIED = "verified"
        APPROVED = "approved"
        REJECTED = "rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="arrears_claims")
    periods = models.JSONField(default=list)               # ["2026-01", "2026-02"]: the unpaid months being claimed
    source_lines = models.JSONField(default=list, blank=True)  # payroll line ids this relates to, when known
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    evidence_ref = models.CharField(max_length=200)
    note = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RECORDED, db_index=True)
    recorded_by_id = models.UUIDField(null=True, blank=True)
    recorded_by_username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_by_id = models.UUIDField(null=True, blank=True)
    verified_by_username = models.CharField(max_length=150, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    approved_by_id = models.UUIDField(null=True, blank=True)
    approved_by_username = models.CharField(max_length=150, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "payroll_arrears_claims"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="arrears_positive"),
            models.CheckConstraint(condition=~Q(status="approved") | Q(approved_by_id__isnull=False), name="arrears_approved_has_approver"),
        ]


class ArrearsPayment(AppendOnlyModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    claim = models.ForeignKey(ArrearsClaim, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=80, blank=True)
    paid_on = models.DateField()
    paid_by_id = models.UUIDField(null=True, blank=True)
    paid_by_username = models.CharField(max_length=150, blank=True)
    instruction = models.ForeignKey("payroll.PaymentInstruction", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payroll_arrears_payments"
        ordering = ["created_at"]
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="arrears_payment_positive")]


# ---------------------------------------------------------------- survivor benefit decisions and beneficiary history

class AllocationDecision(models.Model):
    """The ONLY way a survivor benefit is changed, suspended, resumed or terminated: a documented decision with a reason,
    an effective date, a proposer and a different approver. Nothing ends a benefit because time has passed."""

    class Kind(models.TextChoices):
        CHANGE_AMOUNT = "change_amount"
        SUSPEND = "suspend"
        RESUME = "resume"
        TERMINATE = "terminate"

    class State(models.TextChoices):
        PROPOSED = "proposed"
        APPROVED = "approved"
        REJECTED = "rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    allocation = models.ForeignKey(BenefitAllocation, on_delete=models.PROTECT, related_name="decisions")
    kind = models.CharField(max_length=14, choices=Kind.choices)
    new_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    previous_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    reason = models.CharField(max_length=500)
    effective_date = models.DateField()
    supporting_ref = models.CharField(max_length=200)
    state = models.CharField(max_length=10, choices=State.choices, default=State.PROPOSED)
    proposed_by_id = models.UUIDField(null=True, blank=True)
    proposed_by_username = models.CharField(max_length=150, blank=True)
    proposed_at = models.DateTimeField(auto_now_add=True)
    decided_by_id = models.UUIDField(null=True, blank=True)
    decided_by_username = models.CharField(max_length=150, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.CharField(max_length=300, blank=True)

    class Meta:
        db_table = "survivor_allocation_decisions"
        ordering = ["proposed_at"]
        constraints = [models.CheckConstraint(condition=~Q(state="approved") | Q(decided_by_id__isnull=False),
                                              name="allocation_decision_approved_has_approver")]


class BeneficiaryChange(AppendOnlyModel):
    """History of edits to a beneficiary record. Field NAMES only: the old and new values never enter this table or the audit log."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    beneficiary = models.ForeignKey(Beneficiary, on_delete=models.PROTECT, related_name="changes")
    fields_changed = models.JSONField(default=list)
    reason = models.CharField(max_length=300)
    actor_id = models.UUIDField(null=True, blank=True)
    actor_username = models.CharField(max_length=150, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "survivor_beneficiary_changes"
        ordering = ["created_at"]


# ---------------------------------------------------------------- payment instructions (Sahal / bank transfer)

class PaymentInstruction(models.Model):
    """One payment to one recipient by one method. The system RECORDS and controls the workflow; it does not move money.
    No Sahal or bank API is integrated: an authorised officer sends the payment outside the system and records the result
    (transaction reference), and a different officer reconciles it against the provider or bank statement."""

    class Method(models.TextChoices):
        SAHAL = "sahal", "Sahal mobile money"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"

    class Kind(models.TextChoices):
        SALARY = "salary"      # an approved payroll line (including the full month-of-death salary)
        ARREARS = "arrears"    # an approved arrears claim
        SURVIVOR = "survivor"  # an authorised survivor allocation

    class Status(models.TextChoices):
        PREPARED = "prepared"
        AUTHORIZED = "authorized"
        PROCESSING = "processing"   # the executing officer has started the external payment
        PENDING = "pending"         # sent but not yet confirmed by the provider/bank
        PAID = "paid"
        FAILED = "failed"
        CANCELLED = "cancelled"

    class Recon(models.TextChoices):
        UNRECONCILED = "unreconciled"
        RECONCILED = "reconciled"
        DISCREPANCY = "discrepancy"

    OPEN = ("prepared", "authorized", "processing", "pending")  # reserves money against its target but is not yet in the ledger

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    line = models.ForeignKey(PayrollLine, null=True, blank=True, on_delete=models.PROTECT, related_name="instructions")
    claim = models.ForeignKey(ArrearsClaim, null=True, blank=True, on_delete=models.PROTECT, related_name="instructions")
    allocation = models.ForeignKey(BenefitAllocation, null=True, blank=True, on_delete=models.PROTECT, related_name="instructions")
    personnel = models.ForeignKey("personnel.Personnel", on_delete=models.PROTECT, related_name="payment_instructions")
    beneficiary = models.ForeignKey(Beneficiary, null=True, blank=True, on_delete=models.PROTECT, related_name="instructions")
    period_year = models.PositiveSmallIntegerField()
    period_month = models.PositiveSmallIntegerField()
    method = models.CharField(max_length=14, choices=Method.choices)
    recipient_name = models.CharField(max_length=150)
    recipient_display = models.CharField(max_length=120)       # masked, safe to show to anyone who may view payments
    recipient_details_enc = models.TextField()                 # encrypted JSON: mobile number, or bank name + account number
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=3)
    transaction_reference = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PREPARED, db_index=True)
    failure_reason = models.CharField(max_length=300, blank=True)
    note = models.CharField(max_length=300, blank=True)
    retry_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="retries")
    paid_on = models.DateField(null=True, blank=True)
    recon_status = models.CharField(max_length=12, choices=Recon.choices, default=Recon.UNRECONCILED, db_index=True)
    statement_ref = models.CharField(max_length=80, blank=True)
    statement_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    statement_date = models.DateField(null=True, blank=True)
    recon_note = models.CharField(max_length=300, blank=True)
    prepared_by_id = models.UUIDField(null=True, blank=True)
    prepared_by_username = models.CharField(max_length=150, blank=True)
    authorized_by_id = models.UUIDField(null=True, blank=True)
    authorized_by_username = models.CharField(max_length=150, blank=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    executed_by_id = models.UUIDField(null=True, blank=True)
    executed_by_username = models.CharField(max_length=150, blank=True)
    executed_at = models.DateTimeField(null=True, blank=True)
    reconciled_by_id = models.UUIDField(null=True, blank=True)
    reconciled_by_username = models.CharField(max_length=150, blank=True)
    reconciled_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payroll_payment_instructions"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="instruction_amount_positive"),
            models.CheckConstraint(condition=Q(period_month__gte=1) & Q(period_month__lte=12), name="instruction_period_month"),
            models.CheckConstraint(condition=(
                Q(kind="salary", line__isnull=False, claim__isnull=True, allocation__isnull=True)
                | Q(kind="arrears", line__isnull=True, claim__isnull=False, allocation__isnull=True)
                | Q(kind="survivor", line__isnull=True, claim__isnull=True, allocation__isnull=False)), name="instruction_one_target"),
            models.CheckConstraint(condition=~Q(status="paid") | (~Q(transaction_reference="") & Q(paid_on__isnull=False)),
                                   name="instruction_paid_has_reference"),
            models.UniqueConstraint(fields=["method", "transaction_reference"],
                                    condition=Q(status="paid") & ~Q(transaction_reference=""), name="instruction_reference_unique_when_paid"),
        ]


class PaymentEvent(AppendOnlyModel):
    """Every step of a payment instruction: who, what, from which status to which. Never edited or deleted."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instruction = models.ForeignKey(PaymentInstruction, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=20)
    from_status = models.CharField(max_length=10, blank=True)
    to_status = models.CharField(max_length=10, blank=True)
    actor_id = models.UUIDField(null=True, blank=True)
    actor_username = models.CharField(max_length=150, blank=True)
    comment = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "payroll_payment_events"
        ordering = ["created_at"]
