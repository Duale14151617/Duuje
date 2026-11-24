import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import no_delete_trigger

KIND = [("licence", "Vehicle licence"), ("road_tax", "Road tax"), ("fine", "Traffic fine"), ("fee", "Fee / permit")]
STATUS = [("submitted", "Waiting to be counted"), ("confirmed", "Counted and confirmed")]


class Migration(migrations.Migration):
    initial = True
    dependencies = [("organization", "0012_departments_and_formation_roles"), ("personnel", "0012_strength_snapshot")]

    operations = [
        migrations.CreateModel(name="TaxCounter", fields=[("name", models.CharField(max_length=20, primary_key=True, serialize=False)), ("last", models.PositiveIntegerField(default=0))], options={"db_table": "tax_counters"}),
        migrations.CreateModel(
            name="TaxType",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=40, unique=True)),
                ("name_en", models.CharField(max_length=120)),
                ("name_so", models.CharField(blank=True, max_length=120)),
                ("kind", models.CharField(choices=KIND, default="fee", max_length=10)),
                ("default_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("currency", models.CharField(default="USD", max_length=3)),
                ("recurring", models.BooleanField(default=False)),
                ("period_months", models.PositiveSmallIntegerField(default=12)),
                ("active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=100)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "tax_types", "ordering": ["sort_order", "code"]},
        ),
        migrations.CreateModel(
            name="TaxVehicle",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("plate", models.CharField(max_length=20)),
                ("plate_key", models.CharField(editable=False, max_length=20, unique=True)),
                ("owner_name", models.CharField(max_length=200)),
                ("owner_phone", models.CharField(blank=True, max_length=40)),
                ("id_ref", models.CharField(blank=True, max_length=80)),
                ("vehicle_kind", models.CharField(blank=True, max_length=60)),
                ("make_model", models.CharField(blank=True, max_length=120)),
                ("active", models.BooleanField(default=True)),
                ("notes", models.CharField(blank=True, max_length=300)),
                ("created_by_username", models.CharField(blank=True, max_length=150)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tax_vehicles", to="organization.organizationalunit")),
            ],
            options={"db_table": "tax_vehicles", "ordering": ["plate_key"]},
        ),
        migrations.CreateModel(
            name="TaxHandover",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("number", models.CharField(max_length=20, unique=True)),
                ("currency", models.CharField(max_length=3)),
                ("expected_amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("payments_count", models.PositiveIntegerField()),
                ("handed_by_username", models.CharField(max_length=150)),
                ("handed_at", models.DateTimeField(auto_now_add=True)),
                ("status", models.CharField(choices=STATUS, default="submitted", max_length=10)),
                ("counted_amount", models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
                ("confirmed_by_username", models.CharField(blank=True, max_length=150)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("note", models.CharField(blank=True, max_length=300)),
                ("version", models.PositiveIntegerField(default=1)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tax_handovers", to="organization.organizationalunit")),
            ],
            options={"db_table": "tax_handovers", "ordering": ["-handed_at"]},
        ),
        migrations.CreateModel(
            name="TaxPayment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("receipt_no", models.CharField(max_length=40)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("currency", models.CharField(max_length=3)),
                ("paid_on", models.DateField()),
                ("period_from", models.DateField(blank=True, null=True)),
                ("period_to", models.DateField(blank=True, null=True)),
                ("reference", models.CharField(blank=True, max_length=150)),
                ("collected_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("voided_by_username", models.CharField(blank=True, max_length=150)),
                ("voided_reason", models.CharField(blank=True, max_length=300)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("collected_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="tax_collections", to="personnel.personnel")),
                ("handover", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="tax.taxhandover")),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="tax_payments", to="organization.organizationalunit")),
                ("tax_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="tax.taxtype")),
                ("vehicle", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payments", to="tax.taxvehicle")),
            ],
            options={"db_table": "tax_payments", "ordering": ["-paid_on", "-created_at"]},
        ),
        migrations.AddConstraint(model_name="taxtype", constraint=models.CheckConstraint(condition=models.Q(("default_amount__isnull", True), ("default_amount__gt", 0), _connector="OR"), name="taxtype_amount_positive")),
        migrations.AddConstraint(model_name="taxhandover", constraint=models.CheckConstraint(condition=models.Q(("expected_amount__gte", 0)), name="taxho_expected_nonneg")),
        migrations.AddIndex(model_name="taxpayment", index=models.Index(fields=["vehicle", "tax_type", "-period_to"], name="taxpay_cover_idx")),
        migrations.AddIndex(model_name="taxpayment", index=models.Index(fields=["org_unit", "handover"], name="taxpay_unit_ho_idx")),
        migrations.AddConstraint(model_name="taxpayment", constraint=models.UniqueConstraint(condition=models.Q(("voided_at__isnull", True)), fields=("org_unit", "receipt_no"), name="taxpay_receipt_unique_live")),
        migrations.AddConstraint(model_name="taxpayment", constraint=models.CheckConstraint(condition=models.Q(("amount__gt", 0)), name="taxpay_amount_positive")),
        migrations.AddConstraint(model_name="taxpayment", constraint=models.CheckConstraint(condition=models.Q(("period_from__isnull", True), ("period_to__isnull", True), ("period_to__gte", models.F("period_from")), _connector="OR"), name="taxpay_period_order")),
        no_delete_trigger("tax_types"),
        no_delete_trigger("tax_vehicles"),
        no_delete_trigger("tax_handovers"),
        no_delete_trigger("tax_payments"),
    ]
