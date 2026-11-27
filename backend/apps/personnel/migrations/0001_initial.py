import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organization", "0001_initial"),
        ("ranks", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Personnel",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("service_number", models.CharField(blank=True, max_length=32, null=True)),
                ("full_name", models.CharField(max_length=150)),
                ("phone", models.CharField(blank=True, max_length=24)),
                ("name_key", models.CharField(db_index=True, editable=False, max_length=150)),
                ("phone_key", models.CharField(blank=True, editable=False, max_length=24)),
                ("status", models.CharField(choices=[("active", "Active"), ("on_leave", "On Leave"), ("suspended", "Suspended"), ("retired", "Retired"), ("discharged", "Discharged")], default="active", max_length=12)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.servicebranch")),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="personnel", to="organization.organizationalunit")),
                ("rank", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="ranks.rank")),
            ],
            options={"db_table": "personnel", "ordering": ["full_name", "id"]},
        ),
        migrations.AddConstraint(
            model_name="personnel",
            constraint=models.UniqueConstraint(condition=Q(service_number__isnull=False), fields=("service_number",), name="personnel_service_number_unique"),
        ),
        migrations.CreateModel(
            name="PersonnelHistory",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("field", models.CharField(choices=[("rank", "Rank"), ("org_unit", "Org Unit"), ("status", "Status")], max_length=10)),
                ("old_ref", models.CharField(blank=True, max_length=64)),
                ("new_ref", models.CharField(max_length=64)),
                ("old_label", models.CharField(blank=True, max_length=200)),
                ("new_label", models.CharField(max_length=200)),
                ("effective_date", models.DateField()),
                ("reason", models.CharField(blank=True, max_length=300)),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                ("recorded_by_id", models.UUIDField(blank=True, null=True)),
                ("recorded_by_username", models.CharField(blank=True, max_length=150)),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="history", to="personnel.personnel")),
            ],
            options={"db_table": "personnel_history", "ordering": ["-effective_date", "-recorded_at"]},
        ),
        migrations.AddIndex(
            model_name="personnelhistory",
            index=models.Index(fields=["personnel", "field"], name="phist_person_field_idx"),
        ),
        migrations.CreateModel(
            name="ImportBatch",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField()),
                ("status", models.CharField(choices=[("preview", "Preview"), ("committed", "Committed")], default="preview", max_length=10)),
                ("rows", models.JSONField(default=list)),
                ("total", models.PositiveIntegerField(default=0)),
                ("valid_count", models.PositiveIntegerField(default=0)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "personnel_import_batches"},
        ),
    ]
