import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [("organization", "0001_initial"), ("logistics", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="InventoryCount",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("cyclic", "Cyclic"), ("change_of_command", "Change Of Command"), ("spot", "Spot")], default="cyclic", max_length=20)),
                ("status", models.CharField(choices=[("open", "Open"), ("submitted", "Submitted"), ("signed", "Signed"), ("cancelled", "Cancelled")], db_index=True, default="open", max_length=10)),
                ("note", models.CharField(blank=True, max_length=300)),
                ("opened_by_id", models.UUIDField(blank=True, null=True)),
                ("opened_by_username", models.CharField(blank=True, max_length=150)),
                ("opened_at", models.DateTimeField(auto_now_add=True)),
                ("submitted_by_id", models.UUIDField(blank=True, null=True)),
                ("submitted_by_username", models.CharField(blank=True, max_length=150)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("signed_by_id", models.UUIDField(blank=True, null=True)),
                ("signed_by_username", models.CharField(blank=True, max_length=150)),
                ("signed_at", models.DateTimeField(blank=True, null=True)),
                ("sign_note", models.CharField(blank=True, max_length=300)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
            ],
            options={"db_table": "inventory_counts", "ordering": ["-opened_at"]},
        ),
        migrations.CreateModel(
            name="InventoryLine",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("expected_identifier", models.CharField(blank=True, max_length=64)),
                ("expected_type", models.CharField(blank=True, max_length=120)),
                ("expected_holder", models.CharField(blank=True, max_length=200)),
                ("expected_status", models.CharField(blank=True, max_length=12)),
                ("result", models.CharField(choices=[("pending", "Pending"), ("verified", "Verified"), ("missing", "Missing"), ("mismatch", "Mismatch"), ("unlisted", "Unlisted")], default="pending", max_length=10)),
                ("observed_identifier", models.CharField(blank=True, max_length=64)),
                ("note", models.CharField(blank=True, max_length=300)),
                ("checked_at", models.DateTimeField(blank=True, null=True)),
                ("checked_by_username", models.CharField(blank=True, max_length=150)),
                ("asset", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="logistics.asset")),
                ("count", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="lines", to="inventories.inventorycount")),
            ],
            options={"db_table": "inventory_lines", "ordering": ["expected_identifier", "id"]},
        ),
        migrations.AddIndex(model_name="inventoryline", index=models.Index(fields=["count", "result"], name="inv_line_count_result_idx")),
    ]
