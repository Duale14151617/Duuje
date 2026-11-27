import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import append_only_trigger

CONDITIONS = [("new", "New"), ("good", "Good"), ("fair", "Fair"), ("poor", "Poor"), ("unserviceable", "Unserviceable")]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("logistics", "0006_asset_lifecycle"),
        ("personnel", "0009_unit_tasks"),
    ]

    operations = [
        migrations.CreateModel(
            name="PpeMovement",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("issue", "Issue"), ("return", "Return"), ("damaged", "Damaged"), ("lost", "Lost"), ("retired", "Retired")], max_length=10)),
                ("delta", models.IntegerField()),
                ("size", models.CharField(blank=True, max_length=20)),
                ("serial", models.CharField(blank=True, max_length=64)),
                ("condition", models.CharField(choices=CONDITIONS, default="new", max_length=16)),
                ("reference", models.CharField(blank=True, max_length=60)),
                ("authority_ref", models.CharField(blank=True, max_length=150)),
                ("note", models.CharField(blank=True, max_length=300)),
                ("group", models.UUIDField(blank=True, null=True)),
                ("actor_id", models.UUIDField(blank=True, null=True)),
                ("actor_username", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ppe_ledger", to="personnel.personnel")),
                ("stock_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ppe_movements", to="logistics.stockline")),
                ("store_transaction", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="ppe_movements", to="logistics.stocktransaction")),
            ],
            options={"db_table": "ppe_movements", "ordering": ["-created_at", "-id"]},
        ),
        migrations.CreateModel(
            name="PpeInspection",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("inspected_on", models.DateField()),
                ("condition", models.CharField(choices=CONDITIONS, max_length=16)),
                ("next_due", models.DateField(blank=True, null=True)),
                ("note", models.CharField(blank=True, max_length=300)),
                ("actor_id", models.UUIDField(blank=True, null=True)),
                ("actor_username", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ppe_inspections", to="personnel.personnel")),
                ("stock_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ppe_inspections", to="logistics.stockline")),
            ],
            options={"db_table": "ppe_inspections", "ordering": ["-inspected_on", "-created_at"]},
        ),
        migrations.AddIndex(model_name="ppemovement", index=models.Index(fields=["personnel", "stock_line"], name="ppe_move_person_line")),
        migrations.AddIndex(model_name="ppemovement", index=models.Index(fields=["stock_line", "kind"], name="ppe_move_line_kind")),
        migrations.AddIndex(model_name="ppemovement", index=models.Index(fields=["created_at"], name="ppe_move_created")),
        migrations.AddIndex(model_name="ppeinspection", index=models.Index(fields=["personnel", "stock_line", "-inspected_on"], name="ppe_insp_person_line")),
        migrations.AddConstraint(model_name="ppemovement", constraint=models.CheckConstraint(condition=~models.Q(delta=0), name="ppe_move_nonzero")),
        migrations.AddConstraint(model_name="ppemovement", constraint=models.CheckConstraint(
            condition=models.Q(kind="issue", delta__gt=0) | models.Q(kind__in=["return", "damaged", "lost", "retired"], delta__lt=0),
            name="ppe_move_sign_by_kind")),
        migrations.AddConstraint(model_name="ppemovement", constraint=models.UniqueConstraint(
            condition=models.Q(store_transaction__isnull=False), fields=("store_transaction",), name="ppe_move_one_per_store_txn")),
        migrations.AddConstraint(model_name="ppemovement", constraint=models.CheckConstraint(
            condition=models.Q(kind__in=["issue", "return"]) | models.Q(store_transaction__isnull=True), name="ppe_move_writeoff_not_in_store")),
        append_only_trigger("ppe_movements"),
        append_only_trigger("ppe_inspections"),
    ]
