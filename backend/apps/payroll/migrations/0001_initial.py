import uuid
from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


def _fk(to, name, null=False, rel="+", **kw):
    return models.ForeignKey(to=to, null=null, on_delete=django.db.models.deletion.PROTECT, related_name=rel, **kw)


def _id():
    return models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)


class Migration(migrations.Migration):
    initial = True
    dependencies = [("personnel", "0008_attendance_support_category"), ("organization", "0006_station_level")]

    operations = [
        migrations.CreateModel(name="SalaryScale", fields=[
            ("id", _id()), ("code", models.CharField(max_length=40, unique=True)), ("name", models.CharField(max_length=120)),
            ("base_amount", models.DecimalField(decimal_places=2, max_digits=14)), ("currency", models.CharField(max_length=3)),
            ("authority_ref", models.CharField(max_length=200)), ("active", models.BooleanField(default=True)),
            ("created_at", models.DateTimeField(auto_now_add=True))],
            options={"db_table": "payroll_salary_scales", "ordering": ["code"]}),
        migrations.AddConstraint("salaryscale", models.CheckConstraint(condition=models.Q(base_amount__gte=0), name="scale_amount_nonneg")),
        migrations.CreateModel(name="SalaryProfile", fields=[
            ("id", _id()), ("personnel", _fk("personnel.personnel", "personnel", rel="salary_profiles")),
            ("scale", _fk("payroll.salaryscale", "scale", null=True, blank=True)),
            ("base_amount", models.DecimalField(decimal_places=2, max_digits=14)), ("currency", models.CharField(max_length=3)),
            ("components", models.JSONField(blank=True, default=list)), ("effective_from", models.DateField()),
            ("authority_ref", models.CharField(max_length=200)),
            ("status", models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")], default="pending", max_length=10)),
            ("created_by_id", models.UUIDField(blank=True, null=True)), ("created_by_username", models.CharField(blank=True, max_length=150)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("decided_by_id", models.UUIDField(blank=True, null=True)),
            ("decided_by_username", models.CharField(blank=True, max_length=150)), ("decided_at", models.DateTimeField(blank=True, null=True)),
            ("decision_note", models.CharField(blank=True, max_length=300))],
            options={"db_table": "payroll_salary_profiles", "ordering": ["-effective_from", "-created_at"]}),
        migrations.AddConstraint("salaryprofile", models.CheckConstraint(condition=models.Q(base_amount__gte=0), name="profile_amount_nonneg")),
        migrations.AddConstraint("salaryprofile", models.UniqueConstraint(fields=["personnel", "effective_from"], condition=~models.Q(status="rejected"), name="profile_one_per_person_date")),
        migrations.AddConstraint("salaryprofile", models.CheckConstraint(condition=~models.Q(status="approved") | models.Q(decided_by_id__isnull=False), name="profile_approved_has_approver")),
        migrations.CreateModel(name="PayrollPeriod", fields=[
            ("id", _id()), ("year", models.PositiveSmallIntegerField()), ("month", models.PositiveSmallIntegerField())],
            options={"db_table": "payroll_periods", "ordering": ["-year", "-month"]}),
        migrations.AddConstraint("payrollperiod", models.UniqueConstraint(fields=["year", "month"], name="payroll_period_unique")),
        migrations.AddConstraint("payrollperiod", models.CheckConstraint(condition=models.Q(month__gte=1) & models.Q(month__lte=12), name="payroll_period_month")),
        migrations.CreateModel(name="PayrollRun", fields=[
            ("id", _id()), ("period", _fk("payroll.payrollperiod", "period", rel="runs")),
            ("kind", models.CharField(choices=[("regular", "Regular"), ("adjustment", "Adjustment")], default="regular", max_length=10)),
            ("status", models.CharField(choices=[("prepared", "Prepared"), ("submitted", "Submitted"), ("approved", "Approved"), ("paid", "Paid"), ("cancelled", "Cancelled")], db_index=True, default="prepared", max_length=10)),
            ("exceptions", models.JSONField(blank=True, default=list)), ("prepared_by_id", models.UUIDField(blank=True, null=True)),
            ("prepared_by_username", models.CharField(blank=True, max_length=150)), ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True))],
            options={"db_table": "payroll_runs", "ordering": ["-created_at"]}),
        migrations.AddConstraint("payrollrun", models.UniqueConstraint(fields=["period"], condition=models.Q(kind="regular") & ~models.Q(status="cancelled"), name="one_live_regular_run_per_period")),
        migrations.CreateModel(name="PayrollLine", fields=[
            ("id", _id()), ("run", _fk("payroll.payrollrun", "run", rel="lines")), ("period", _fk("payroll.payrollperiod", "period")),
            ("personnel", _fk("personnel.personnel", "personnel", rel="payroll_lines")),
            ("profile", _fk("payroll.salaryprofile", "profile", null=True)),
            ("kind", models.CharField(choices=[("regular", "Regular"), ("adjustment", "Adjustment"), ("reversal", "Reversal")], default="regular", max_length=10)),
            ("adjusts", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="corrections", to="payroll.payrollline")),
            ("reason", models.CharField(blank=True, max_length=300)), ("currency", models.CharField(max_length=3)),
            ("base", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14)),
            ("allowances", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14)),
            ("deductions", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14)),
            ("gross", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=14)),
            ("calculated_net", models.DecimalField(decimal_places=2, max_digits=14)),
            ("approved_net", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
            ("org_unit", _fk("organization.organizationalunit", "org_unit")), ("service_number", models.CharField(blank=True, max_length=32))],
            options={"db_table": "payroll_lines", "ordering": ["personnel_id", "kind"]}),
        migrations.AddConstraint("payrollline", models.UniqueConstraint(fields=["period", "personnel"], condition=models.Q(kind="regular"), name="one_regular_line_per_person_period")),
        migrations.AddConstraint("payrollline", models.CheckConstraint(condition=models.Q(kind="regular") | models.Q(adjusts__isnull=False), name="correction_references_original")),
        migrations.CreateModel(name="PaymentTransaction", fields=[
            ("id", _id()), ("line", _fk("payroll.payrollline", "line", rel="transactions")),
            ("amount", models.DecimalField(decimal_places=2, max_digits=14)), ("reference", models.CharField(blank=True, max_length=80)),
            ("paid_on", models.DateField()), ("paid_by_id", models.UUIDField(blank=True, null=True)),
            ("paid_by_username", models.CharField(blank=True, max_length=150)), ("note", models.CharField(blank=True, max_length=300)),
            ("created_at", models.DateTimeField(auto_now_add=True))],
            options={"db_table": "payroll_transactions", "ordering": ["created_at"]}),
        migrations.AddConstraint("paymenttransaction", models.CheckConstraint(condition=~models.Q(amount=0), name="payment_nonzero")),
        migrations.CreateModel(name="PayrollAction", fields=[
            ("id", _id()), ("run", _fk("payroll.payrollrun", "run", rel="actions")), ("action", models.CharField(max_length=16)),
            ("from_status", models.CharField(blank=True, max_length=10)), ("to_status", models.CharField(max_length=10)),
            ("actor_id", models.UUIDField(blank=True, null=True)), ("actor_username", models.CharField(blank=True, max_length=150)),
            ("comment", models.CharField(blank=True, max_length=500)), ("created_at", models.DateTimeField(auto_now_add=True))],
            options={"db_table": "payroll_run_actions", "ordering": ["created_at"]}),
        migrations.CreateModel(name="SurvivorCase", fields=[
            ("id", _id()), ("personnel", _fk("personnel.personnel", "personnel", rel="survivor_cases")),
            ("death_record", _fk("personnel.deathrecord", "death_record")),
            ("status", models.CharField(choices=[("open", "Open"), ("verified", "Verified"), ("disputed", "Disputed"), ("closed", "Closed")], db_index=True, default="open", max_length=10)),
            ("outstanding_review", models.CharField(blank=True, max_length=1000)), ("dispute_note", models.CharField(blank=True, max_length=500)),
            ("opened_by_id", models.UUIDField(blank=True, null=True)), ("opened_by_username", models.CharField(blank=True, max_length=150)),
            ("verified_by_id", models.UUIDField(blank=True, null=True)), ("verified_by_username", models.CharField(blank=True, max_length=150)),
            ("closed_by_username", models.CharField(blank=True, max_length=150)), ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True))],
            options={"db_table": "survivor_cases", "ordering": ["-created_at"]}),
        migrations.AddConstraint("survivorcase", models.UniqueConstraint(fields=["personnel"], condition=~models.Q(status="closed"), name="one_open_survivor_case")),
        migrations.CreateModel(name="Beneficiary", fields=[
            ("id", _id()), ("case", _fk("payroll.survivorcase", "case", rel="beneficiaries")),
            ("full_name", models.CharField(max_length=150)),
            ("relationship", models.CharField(choices=[("wife", "Wife"), ("child", "Child"), ("parent", "Parent"), ("sibling", "Sibling")], max_length=8)),
            ("identity_ref", models.CharField(max_length=80)), ("evidence_ref", models.CharField(max_length=200)),
            ("payment_details_enc", models.TextField(blank=True)),
            ("state", models.CharField(choices=[("pending", "Pending"), ("verified", "Verified"), ("rejected", "Rejected")], default="pending", max_length=10)),
            ("decided_by_id", models.UUIDField(blank=True, null=True)), ("decided_by_username", models.CharField(blank=True, max_length=150)),
            ("decided_at", models.DateTimeField(blank=True, null=True)), ("decision_note", models.CharField(blank=True, max_length=300)),
            ("created_by_username", models.CharField(blank=True, max_length=150)), ("created_at", models.DateTimeField(auto_now_add=True))],
            options={"db_table": "survivor_beneficiaries", "ordering": ["created_at"]}),
        migrations.CreateModel(name="BenefitAllocation", fields=[
            ("id", _id()), ("beneficiary", _fk("payroll.beneficiary", "beneficiary", rel="allocations")),
            ("amount", models.DecimalField(decimal_places=2, max_digits=14)), ("currency", models.CharField(max_length=3)),
            ("basis_ref", models.CharField(max_length=200)),
            ("status", models.CharField(choices=[("proposed", "Proposed"), ("authorized", "Authorized"), ("cancelled", "Cancelled")], default="proposed", max_length=10)),
            ("proposed_by_id", models.UUIDField(blank=True, null=True)), ("proposed_by_username", models.CharField(blank=True, max_length=150)),
            ("authorized_by_id", models.UUIDField(blank=True, null=True)), ("authorized_by_username", models.CharField(blank=True, max_length=150)),
            ("authorized_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True))],
            options={"db_table": "survivor_allocations", "ordering": ["created_at"]}),
        migrations.AddConstraint("benefitallocation", models.CheckConstraint(condition=models.Q(amount__gt=0), name="allocation_positive")),
        migrations.AddConstraint("benefitallocation", models.CheckConstraint(condition=~models.Q(status="authorized") | models.Q(authorized_by_id__isnull=False), name="allocation_authorized_has_approver")),
        migrations.CreateModel(name="SurvivorPayment", fields=[
            ("id", _id()), ("allocation", _fk("payroll.benefitallocation", "allocation", rel="payments")),
            ("amount", models.DecimalField(decimal_places=2, max_digits=14)), ("reference", models.CharField(blank=True, max_length=80)),
            ("paid_on", models.DateField()), ("paid_by_id", models.UUIDField(blank=True, null=True)),
            ("paid_by_username", models.CharField(blank=True, max_length=150)), ("note", models.CharField(blank=True, max_length=300)),
            ("created_at", models.DateTimeField(auto_now_add=True))],
            options={"db_table": "survivor_payments", "ordering": ["created_at"]}),
        migrations.AddConstraint("survivorpayment", models.CheckConstraint(condition=~models.Q(amount=0), name="survivor_payment_nonzero")),
    ]
