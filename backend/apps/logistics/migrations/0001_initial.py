import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q

U = settings.AUTH_USER_MODEL


def fk(to, null=False, blank=False, on_delete=django.db.models.deletion.PROTECT, related_name="+"):
    return models.ForeignKey(to=to, null=null, blank=blank, on_delete=on_delete, related_name=related_name)


def pk():
    return models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)


SET_NULL = django.db.models.deletion.SET_NULL
OU = "organization.organizationalunit"


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(U), ("organization", "0001_initial")]

    operations = [
        migrations.CreateModel(name="InventoryCategory", fields=[
            ("id", pk()),
            ("code", models.CharField(max_length=48, unique=True)),
            ("name_en", models.CharField(max_length=120)),
            ("name_so", models.CharField(blank=True, max_length=120)),
            ("kind", models.CharField(choices=[("stock", "Stock"), ("asset", "Asset")], max_length=8)),
            ("restricted", models.BooleanField(default=False)),
            ("approval_status", models.CharField(choices=[("draft", "Draft"), ("approved", "Approved")], default="draft", max_length=10)),
            ("approved_at", models.DateTimeField(blank=True, null=True)),
            ("active", models.BooleanField(default=True)),
            ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("approved_by", fk(U, True, True, SET_NULL)),
            ("created_by", fk(U, True, True, SET_NULL)),
        ], options={"db_table": "inventory_categories", "ordering": ["code"]}),
        migrations.CreateModel(name="StockLine", fields=[
            ("id", pk()),
            ("uom", models.CharField(default="units", max_length=16)),
            ("quantity", models.PositiveIntegerField(default=0)),
            ("reorder_level", models.PositiveIntegerField(default=0)),
            ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("category", fk("logistics.inventorycategory")),
            ("org_unit", fk(OU)),
        ], options={"db_table": "stock_lines", "ordering": ["category__code", "org_unit__path"]}),
        migrations.AddConstraint(model_name="stockline", constraint=models.UniqueConstraint(fields=("category", "org_unit"), name="stockline_unique_per_unit")),
        migrations.CreateModel(name="StockTransaction", fields=[
            ("id", pk()),
            ("kind", models.CharField(choices=[("receive", "Receive"), ("issue", "Issue"), ("adjust", "Adjust"), ("transfer_out", "Transfer Out"), ("transfer_in", "Transfer In")], max_length=12)),
            ("delta", models.IntegerField()),
            ("balance_after", models.PositiveIntegerField()),
            ("reason", models.CharField(blank=True, max_length=300)),
            ("group", models.UUIDField(blank=True, null=True)),
            ("actor_username", models.CharField(blank=True, max_length=150)),
            ("correlation_id", models.CharField(blank=True, max_length=64)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("actor", fk(U, True, False, SET_NULL)),
            ("counterpart_unit", fk(OU, True, True)),
            ("stock_line", fk("logistics.stockline", related_name="transactions")),
        ], options={"db_table": "stock_transactions", "ordering": ["-created_at", "-id"], "abstract": False}),
        migrations.AddConstraint(model_name="stocktransaction", constraint=models.CheckConstraint(condition=~Q(delta=0), name="stocktxn_nonzero_delta")),
        migrations.CreateModel(name="Asset", fields=[
            ("id", pk()),
            ("identifier", models.CharField(max_length=64)),
            ("description", models.CharField(blank=True, max_length=200)),
            ("status", models.CharField(choices=[("in_stock", "In Stock"), ("issued", "Issued"), ("maintenance", "Maintenance"), ("missing", "Missing"), ("lost", "Lost"), ("retired", "Retired")], default="in_stock", max_length=12)),
            ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("category", fk("logistics.inventorycategory")),
            ("custodian", fk(U, True, True, SET_NULL)),
            ("issued_to_unit", fk(OU, True, True)),
            ("org_unit", fk(OU)),
        ], options={"db_table": "assets", "ordering": ["category__code", "identifier"]}),
        migrations.AddConstraint(model_name="asset", constraint=models.UniqueConstraint(fields=("category", "identifier"), name="asset_identifier_unique")),
        migrations.AddConstraint(model_name="asset", constraint=models.CheckConstraint(
            condition=(Q(status="issued", issued_to_unit__isnull=False) | (~Q(status="issued") & Q(issued_to_unit__isnull=True))),
            name="asset_issue_consistent")),
        migrations.CreateModel(name="AssetEvent", fields=[
            ("id", pk()),
            ("kind", models.CharField(max_length=24)),
            ("from_status", models.CharField(blank=True, max_length=12)),
            ("to_status", models.CharField(blank=True, max_length=12)),
            ("note", models.CharField(blank=True, max_length=300)),
            ("actor_username", models.CharField(blank=True, max_length=150)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("actor", fk(U, True, False, SET_NULL)),
            ("asset", fk("logistics.asset", related_name="events")),
            ("from_unit", fk(OU, True, True)),
            ("to_unit", fk(OU, True, True)),
        ], options={"db_table": "asset_events", "ordering": ["-created_at", "-id"], "abstract": False}),
        migrations.CreateModel(name="Reconciliation", fields=[
            ("id", pk()),
            ("status", models.CharField(choices=[("open", "Open"), ("completed", "Completed"), ("cancelled", "Cancelled")], default="open", max_length=10)),
            ("includes_restricted", models.BooleanField(default=False)),
            ("notes", models.CharField(blank=True, max_length=300)),
            ("started_at", models.DateTimeField(auto_now_add=True)),
            ("completed_at", models.DateTimeField(blank=True, null=True)),
            ("version", models.PositiveIntegerField(default=1)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("completed_by", fk(U, True, True, SET_NULL)),
            ("org_unit", fk(OU)),
            ("started_by", fk(U, True, False, SET_NULL)),
        ], options={"db_table": "reconciliations", "ordering": ["-started_at", "id"]}),
        migrations.AddConstraint(model_name="reconciliation", constraint=models.UniqueConstraint(condition=Q(status="open"), fields=("org_unit",), name="recon_one_open_per_unit")),
        migrations.CreateModel(name="ReconciliationLine", fields=[
            ("id", pk()),
            ("label", models.CharField(max_length=200)),
            ("expected_quantity", models.PositiveIntegerField(blank=True, null=True)),
            ("counted_quantity", models.PositiveIntegerField(blank=True, null=True)),
            ("found", models.BooleanField(blank=True, null=True)),
            ("asset", fk("logistics.asset", True, True)),
            ("reconciliation", fk("logistics.reconciliation", on_delete=django.db.models.deletion.CASCADE, related_name="lines")),
            ("stock_line", fk("logistics.stockline", True, True)),
        ], options={"db_table": "reconciliation_lines", "ordering": ["label", "id"]}),
        migrations.AddConstraint(model_name="reconciliationline", constraint=models.CheckConstraint(
            condition=(Q(stock_line__isnull=False, asset__isnull=True) | Q(stock_line__isnull=True, asset__isnull=False)),
            name="reconline_one_target")),
    ]
