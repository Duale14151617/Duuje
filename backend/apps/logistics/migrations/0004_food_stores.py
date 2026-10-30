import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q

U = settings.AUTH_USER_MODEL


class Migration(migrations.Migration):
    """Food suppliers, expiry batches and store-to-unit allocations. Adds tables only; no existing table is changed."""

    dependencies = [
        migrations.swappable_dependency(U),
        ("organization", "0006_station_level"),
        ("logistics", "0003_ammunition_ledger"),
    ]

    operations = [
        migrations.CreateModel(name="Supplier", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("name", models.CharField(max_length=150, unique=True)),
            ("phone", models.CharField(blank=True, max_length=30)),
            ("address", models.CharField(blank=True, max_length=200)),
            ("notes", models.CharField(blank=True, max_length=300)),
            ("active", models.BooleanField(default=True)),
            ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"db_table": "food_suppliers", "ordering": ["name"]}),
        migrations.CreateModel(name="FoodBatch", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("batch_ref", models.CharField(blank=True, max_length=60)),
            ("quantity", models.PositiveIntegerField()),
            ("remaining", models.PositiveIntegerField()),
            ("received_on", models.DateField()),
            ("expires_on", models.DateField(blank=True, null=True)),
            ("source", models.CharField(choices=[("receipt", "Receipt"), ("allocation", "Allocation")], default="receipt", max_length=10)),
            ("delivery_note_ref", models.CharField(blank=True, max_length=60)),
            ("authority_ref", models.CharField(blank=True, max_length=150)),
            ("created_by_username", models.CharField(blank=True, max_length=150)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=U)),
            ("stock_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="batches", to="logistics.stockline")),
            ("supplier", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="logistics.supplier")),
            ("txn", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="logistics.stocktransaction")),
        ], options={"db_table": "food_batches", "ordering": ["expires_on", "received_on", "created_at"]}),
        migrations.AddConstraint(model_name="foodbatch", constraint=models.CheckConstraint(
            condition=Q(quantity__gt=0) & Q(remaining__lte=F("quantity")), name="foodbatch_quantities")),
        migrations.AddConstraint(model_name="foodbatch", constraint=models.UniqueConstraint(
            fields=["supplier", "delivery_note_ref"], condition=Q(source="receipt"), name="foodbatch_one_receipt_per_delivery_note")),
        migrations.CreateModel(name="FoodAllocation", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("quantity", models.PositiveIntegerField()),
            ("status", models.CharField(choices=[("issued", "Issued"), ("delivered", "Delivered"), ("cancelled", "Cancelled")],
                                        db_index=True, default="issued", max_length=10)),
            ("order_ref", models.CharField(max_length=150)),
            ("issuing_officer", models.CharField(max_length=150)),
            ("order_date", models.DateField()),
            ("issue_note_ref", models.CharField(max_length=60)),
            ("group", models.UUIDField(default=uuid.uuid4, editable=False)),
            ("consumed", models.JSONField(default=list)),
            ("issued_by_username", models.CharField(blank=True, max_length=150)),
            ("issued_at", models.DateTimeField(auto_now_add=True)),
            ("delivered_at", models.DateTimeField(blank=True, null=True)),
            ("received_by_name", models.CharField(blank=True, max_length=150)),
            ("receipt_note_ref", models.CharField(blank=True, max_length=60)),
            ("acknowledged_by_username", models.CharField(blank=True, max_length=150)),
            ("cancel_reason", models.CharField(blank=True, max_length=300)),
            ("cancelled_at", models.DateTimeField(blank=True, null=True)),
            ("version", models.PositiveIntegerField(default=1)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("acknowledged_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=U)),
            ("from_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="logistics.stockline")),
            ("issued_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=U)),
            ("to_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
        ], options={"db_table": "food_allocations", "ordering": ["-issued_at", "id"]}),
        migrations.AddConstraint(model_name="foodallocation", constraint=models.CheckConstraint(
            condition=Q(quantity__gt=0), name="foodalloc_positive")),
        migrations.AddConstraint(model_name="foodallocation", constraint=models.CheckConstraint(
            condition=~Q(order_ref="") & ~Q(issuing_officer="") & ~Q(issue_note_ref=""), name="foodalloc_order_present")),
    ]
