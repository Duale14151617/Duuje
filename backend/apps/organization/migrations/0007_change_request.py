import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

U = settings.AUTH_USER_MODEL


class Migration(migrations.Migration):
    """Adds the change-request table (approval queue for hierarchy-affecting actions). No existing table is touched."""

    dependencies = [migrations.swappable_dependency(U), ("organization", "0006_station_level")]

    operations = [
        migrations.CreateModel(name="ChangeRequest", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("kind", models.CharField(choices=[("transfer", "Transfer")], db_index=True, max_length=20)),
            ("status", models.CharField(choices=[("pending", "Pending"), ("in_review", "In Review"), ("approved", "Approved"),
                                                 ("rejected", "Rejected"), ("withdrawn", "Withdrawn")],
                                        db_index=True, default="pending", max_length=10)),
            ("summary", models.CharField(max_length=300)),
            ("payload", models.JSONField(default=dict)),
            ("order_ref", models.CharField(max_length=150)),
            ("issuing_officer", models.CharField(max_length=150)),
            ("order_date", models.DateField()),
            ("proposed_by_username", models.CharField(blank=True, max_length=150)),
            ("review_started_at", models.DateTimeField(blank=True, null=True)),
            ("decided_by_username", models.CharField(blank=True, max_length=150)),
            ("decided_at", models.DateTimeField(blank=True, null=True)),
            ("decision_note", models.CharField(blank=True, max_length=500)),
            ("self_approved", models.BooleanField(default=False)),
            ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=U)),
            ("proposed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=U)),
            ("unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
        ], options={"db_table": "change_requests", "ordering": ["-created_at", "id"]}),
        migrations.AddConstraint(model_name="changerequest", constraint=models.CheckConstraint(
            condition=models.Q(("order_ref", ""), _negated=True) & models.Q(("issuing_officer", ""), _negated=True),
            name="change_request_order_present")),
    ]
