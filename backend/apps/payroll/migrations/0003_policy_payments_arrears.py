"""Confirmed payroll and survivor policy: payment instructions (Sahal / bank), arrears, status-pay decisions, survivor-benefit
decisions (indefinite benefits), configurable policy settings. Purely additive: no table is dropped, no column is removed,
and every added column on an existing table is nullable or has a default, so existing rows are kept as they are."""
import uuid

import django.db.models.deletion
from django.db import migrations, models

Q = models.Q


def _id():
    return models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)


def _fk(to, null=False, rel="+", blank=False):
    return models.ForeignKey(to=to, null=null, blank=blank, on_delete=django.db.models.deletion.PROTECT, related_name=rel)


def _choices(*values):
    return [(v, v.replace("_", " ").title()) for v in values]


def _txt(n, blank=True):
    return models.CharField(max_length=n, blank=blank)


def _dec():
    return models.DecimalField(decimal_places=2, max_digits=14)


class Migration(migrations.Migration):
    dependencies = [("payroll", "0002_append_only_triggers"), ("personnel", "0008_attendance_support_category")]

    operations = [
        # ---- new columns on existing tables (all nullable / defaulted)
        migrations.AddField("payrollline", "status_flag", models.CharField(blank=True, default="", max_length=10)),
        migrations.AddField("payrollline", "death_month", models.BooleanField(default=False)),
        migrations.AddField("survivorcase", "closure_reason", _txt(500)),
        migrations.AddField("survivorcase", "closure_effective_date", models.DateField(blank=True, null=True)),
        migrations.AddField("survivorcase", "closure_ref", _txt(200)),
        # Rows that exist before this migration were created under the old rule (a total to be paid once): keep that meaning.
        migrations.AddField("benefitallocation", "basis_kind",
                            models.CharField(choices=_choices("per_period", "lump_sum"), default="lump_sum", max_length=10), preserve_default=False),
        migrations.AlterField("benefitallocation", "basis_kind",
                              models.CharField(choices=_choices("per_period", "lump_sum"), default="per_period", max_length=10)),
        migrations.AlterField("benefitallocation", "status", models.CharField(
            choices=_choices("proposed", "authorized", "cancelled", "suspended", "terminated"), default="proposed", max_length=10)),
        migrations.AddField("benefitallocation", "effective_from", models.DateField(blank=True, null=True)),
        migrations.AddField("benefitallocation", "held_from", models.DateField(blank=True, null=True)),
        migrations.AddField("benefitallocation", "ended_on", models.DateField(blank=True, null=True)),
        migrations.AddConstraint("benefitallocation", models.CheckConstraint(
            condition=Q(ended_on__isnull=True) | Q(status="terminated"), name="allocation_end_only_when_terminated")),
        migrations.AddField("survivorpayment", "period_year", models.PositiveSmallIntegerField(blank=True, null=True)),
        migrations.AddField("survivorpayment", "period_month", models.PositiveSmallIntegerField(blank=True, null=True)),

        # ---- policy settings
        migrations.CreateModel(name="PolicySetting", fields=[
            ("key", models.CharField(max_length=60, primary_key=True, serialize=False)), ("title", _txt(160, False)),
            ("description", _txt(500, False)),
            ("status", models.CharField(choices=_choices("confirmed", "unconfirmed"), default="unconfirmed", max_length=12)),
            ("value", _txt(300)), ("authority_ref", _txt(200)), ("confirmed_by_username", _txt(150)),
            ("confirmed_at", models.DateTimeField(blank=True, null=True))],
            options={"db_table": "payroll_policy_settings", "ordering": ["key"]}),

        # ---- suspended / jailed pay decisions
        migrations.CreateModel(name="StatusPayDecision", fields=[
            ("id", _id()), ("personnel", _fk("personnel.personnel", rel="pay_decisions")), ("status_at_decision", _txt(12, False)),
            ("kind", models.CharField(choices=_choices("retain_existing", "formal_decision"), max_length=20)),
            ("decision_text", _txt(500)), ("reason", _txt(500, False)), ("effective_date", models.DateField()),
            ("supporting_ref", _txt(200)),
            ("state", models.CharField(choices=_choices("recorded", "approved", "rejected"), default="recorded", max_length=10)),
            ("recorded_by_id", models.UUIDField(blank=True, null=True)), ("recorded_by_username", _txt(150)),
            ("recorded_at", models.DateTimeField(auto_now_add=True)),
            ("decided_by_id", models.UUIDField(blank=True, null=True)), ("decided_by_username", _txt(150)),
            ("decided_at", models.DateTimeField(blank=True, null=True)), ("decision_note", _txt(300))],
            options={"db_table": "payroll_status_decisions", "ordering": ["-recorded_at"]}),
        migrations.AddConstraint("statuspaydecision", models.CheckConstraint(
            condition=~Q(state="approved") | Q(decided_by_id__isnull=False), name="status_decision_approved_has_approver")),

        # ---- arrears
        migrations.CreateModel(name="ArrearsClaim", fields=[
            ("id", _id()), ("personnel", _fk("personnel.personnel", rel="arrears_claims")), ("periods", models.JSONField(default=list)),
            ("source_lines", models.JSONField(blank=True, default=list)), ("amount", _dec()), ("currency", _txt(3, False)),
            ("evidence_ref", _txt(200, False)), ("note", _txt(500)),
            ("status", models.CharField(choices=_choices("recorded", "verified", "approved", "rejected"), db_index=True, default="recorded", max_length=10)),
            ("recorded_by_id", models.UUIDField(blank=True, null=True)), ("recorded_by_username", _txt(150)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("verified_by_id", models.UUIDField(blank=True, null=True)), ("verified_by_username", _txt(150)),
            ("verified_at", models.DateTimeField(blank=True, null=True)),
            ("approved_by_id", models.UUIDField(blank=True, null=True)), ("approved_by_username", _txt(150)),
            ("approved_at", models.DateTimeField(blank=True, null=True)), ("decision_note", _txt(300))],
            options={"db_table": "payroll_arrears_claims", "ordering": ["-created_at"]}),
        migrations.AddConstraint("arrearsclaim", models.CheckConstraint(condition=Q(amount__gt=0), name="arrears_positive")),
        migrations.AddConstraint("arrearsclaim", models.CheckConstraint(
            condition=~Q(status="approved") | Q(approved_by_id__isnull=False), name="arrears_approved_has_approver")),

        # ---- survivor decisions and beneficiary history
        migrations.CreateModel(name="AllocationDecision", fields=[
            ("id", _id()), ("allocation", _fk("payroll.benefitallocation", rel="decisions")),
            ("kind", models.CharField(choices=_choices("change_amount", "suspend", "resume", "terminate"), max_length=14)),
            ("new_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
            ("previous_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
            ("reason", _txt(500, False)), ("effective_date", models.DateField()), ("supporting_ref", _txt(200, False)),
            ("state", models.CharField(choices=_choices("proposed", "approved", "rejected"), default="proposed", max_length=10)),
            ("proposed_by_id", models.UUIDField(blank=True, null=True)), ("proposed_by_username", _txt(150)),
            ("proposed_at", models.DateTimeField(auto_now_add=True)),
            ("decided_by_id", models.UUIDField(blank=True, null=True)), ("decided_by_username", _txt(150)),
            ("decided_at", models.DateTimeField(blank=True, null=True)), ("decision_note", _txt(300))],
            options={"db_table": "survivor_allocation_decisions", "ordering": ["proposed_at"]}),
        migrations.AddConstraint("allocationdecision", models.CheckConstraint(
            condition=~Q(state="approved") | Q(decided_by_id__isnull=False), name="allocation_decision_approved_has_approver")),
        migrations.CreateModel(name="BeneficiaryChange", fields=[
            ("id", _id()), ("beneficiary", _fk("payroll.beneficiary", rel="changes")), ("fields_changed", models.JSONField(default=list)),
            ("reason", _txt(300, False)), ("actor_id", models.UUIDField(blank=True, null=True)), ("actor_username", _txt(150)),
            ("created_at", models.DateTimeField(auto_now_add=True))],
            options={"db_table": "survivor_beneficiary_changes", "ordering": ["created_at"]}),

        # ---- payment instructions
        migrations.CreateModel(name="PaymentInstruction", fields=[
            ("id", _id()),
            ("kind", models.CharField(choices=_choices("salary", "arrears", "survivor"), max_length=10)),
            ("line", _fk("payroll.payrollline", null=True, blank=True, rel="instructions")),
            ("claim", _fk("payroll.arrearsclaim", null=True, blank=True, rel="instructions")),
            ("allocation", _fk("payroll.benefitallocation", null=True, blank=True, rel="instructions")),
            ("personnel", _fk("personnel.personnel", rel="payment_instructions")),
            ("beneficiary", _fk("payroll.beneficiary", null=True, blank=True, rel="instructions")),
            ("period_year", models.PositiveSmallIntegerField()), ("period_month", models.PositiveSmallIntegerField()),
            ("method", models.CharField(choices=[("sahal", "Sahal mobile money"), ("bank_transfer", "Bank transfer")], max_length=14)),
            ("recipient_name", _txt(150, False)), ("recipient_display", _txt(120, False)), ("recipient_details_enc", models.TextField()),
            ("amount", _dec()), ("currency", _txt(3, False)), ("transaction_reference", _txt(80)),
            ("status", models.CharField(choices=_choices("prepared", "authorized", "processing", "pending", "paid", "failed", "cancelled"),
                                        db_index=True, default="prepared", max_length=10)),
            ("failure_reason", _txt(300)), ("note", _txt(300)),
            ("retry_of", _fk("payroll.paymentinstruction", null=True, blank=True, rel="retries")),
            ("paid_on", models.DateField(blank=True, null=True)),
            ("recon_status", models.CharField(choices=_choices("unreconciled", "reconciled", "discrepancy"), db_index=True,
                                              default="unreconciled", max_length=12)),
            ("statement_ref", _txt(80)), ("statement_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
            ("statement_date", models.DateField(blank=True, null=True)), ("recon_note", _txt(300)),
            ("prepared_by_id", models.UUIDField(blank=True, null=True)), ("prepared_by_username", _txt(150)),
            ("authorized_by_id", models.UUIDField(blank=True, null=True)), ("authorized_by_username", _txt(150)),
            ("authorized_at", models.DateTimeField(blank=True, null=True)),
            ("executed_by_id", models.UUIDField(blank=True, null=True)), ("executed_by_username", _txt(150)),
            ("executed_at", models.DateTimeField(blank=True, null=True)),
            ("reconciled_by_id", models.UUIDField(blank=True, null=True)), ("reconciled_by_username", _txt(150)),
            ("reconciled_at", models.DateTimeField(blank=True, null=True)),
            ("version", models.PositiveIntegerField(default=1)), ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True))],
            options={"db_table": "payroll_payment_instructions", "ordering": ["-created_at"]}),
        migrations.AddConstraint("paymentinstruction", models.CheckConstraint(condition=Q(amount__gt=0), name="instruction_amount_positive")),
        migrations.AddConstraint("paymentinstruction", models.CheckConstraint(
            condition=Q(period_month__gte=1) & Q(period_month__lte=12), name="instruction_period_month")),
        migrations.AddConstraint("paymentinstruction", models.CheckConstraint(condition=(
            Q(kind="salary", line__isnull=False, claim__isnull=True, allocation__isnull=True)
            | Q(kind="arrears", line__isnull=True, claim__isnull=False, allocation__isnull=True)
            | Q(kind="survivor", line__isnull=True, claim__isnull=True, allocation__isnull=False)), name="instruction_one_target")),
        migrations.AddConstraint("paymentinstruction", models.CheckConstraint(
            condition=~Q(status="paid") | (~Q(transaction_reference="") & Q(paid_on__isnull=False)), name="instruction_paid_has_reference")),
        migrations.AddConstraint("paymentinstruction", models.UniqueConstraint(
            fields=["method", "transaction_reference"], condition=Q(status="paid") & ~Q(transaction_reference=""),
            name="instruction_reference_unique_when_paid")),
        migrations.CreateModel(name="PaymentEvent", fields=[
            ("id", _id()), ("instruction", _fk("payroll.paymentinstruction", rel="events")), ("action", _txt(20, False)),
            ("from_status", _txt(10)), ("to_status", _txt(10)), ("actor_id", models.UUIDField(blank=True, null=True)),
            ("actor_username", _txt(150)), ("comment", _txt(500)), ("created_at", models.DateTimeField(auto_now_add=True))],
            options={"db_table": "payroll_payment_events", "ordering": ["created_at"]}),
        migrations.CreateModel(name="ArrearsPayment", fields=[
            ("id", _id()), ("claim", _fk("payroll.arrearsclaim", rel="payments")), ("amount", _dec()), ("reference", _txt(80)),
            ("paid_on", models.DateField()), ("paid_by_id", models.UUIDField(blank=True, null=True)), ("paid_by_username", _txt(150)),
            ("instruction", _fk("payroll.paymentinstruction", null=True, blank=True)),
            ("created_at", models.DateTimeField(auto_now_add=True))],
            options={"db_table": "payroll_arrears_payments", "ordering": ["created_at"]}),
        migrations.AddConstraint("arrearspayment", models.CheckConstraint(condition=Q(amount__gt=0), name="arrears_payment_positive")),

        # ---- links from the existing ledgers to the instruction that produced them
        migrations.AddField("paymenttransaction", "instruction", _fk("payroll.paymentinstruction", null=True, blank=True)),
        migrations.AddField("survivorpayment", "instruction", _fk("payroll.paymentinstruction", null=True, blank=True)),
    ]
