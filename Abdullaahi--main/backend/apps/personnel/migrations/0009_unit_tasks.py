import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q

U = settings.AUTH_USER_MODEL


class Migration(migrations.Migration):
    """Administrative task tracking for units: tables only; nothing existing is changed."""

    dependencies = [
        migrations.swappable_dependency(U),
        ("organization", "0007_change_request"),
        ("personnel", "0008_attendance_support_category"),
    ]

    operations = [
        migrations.CreateModel(name="UnitTask", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("title", models.CharField(max_length=200)),
            ("description", models.CharField(blank=True, max_length=1000)),
            ("authority_ref", models.CharField(max_length=150)),
            ("assigned_on", models.DateField()),
            ("due_on", models.DateField(blank=True, null=True)),
            ("status", models.CharField(choices=[("open", "Open"), ("in_progress", "In Progress"), ("completed", "Completed"),
                                                 ("cancelled", "Cancelled")], db_index=True, default="open", max_length=12)),
            ("completion_report", models.CharField(blank=True, max_length=2000)),
            ("document_ref", models.CharField(blank=True, max_length=150)),
            ("cancel_reason", models.CharField(blank=True, max_length=300)),
            ("completed_at", models.DateTimeField(blank=True, null=True)),
            ("created_by_username", models.CharField(blank=True, max_length=150)),
            ("version", models.PositiveIntegerField(default=1)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
            ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=U)),
            ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
            ("responsible", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="personnel.personnel")),
        ], options={"db_table": "unit_tasks", "ordering": ["due_on", "-created_at", "id"]}),
        migrations.AddConstraint(model_name="unittask", constraint=models.CheckConstraint(
            condition=~Q(title="") & ~Q(authority_ref=""), name="unittask_title_authority_present")),
        migrations.AddConstraint(model_name="unittask", constraint=models.CheckConstraint(
            condition=Q(due_on__isnull=True) | Q(due_on__gte=F("assigned_on")), name="unittask_due_after_assigned")),
        migrations.CreateModel(name="TaskEvent", fields=[
            ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
            ("kind", models.CharField(max_length=12)),
            ("from_status", models.CharField(blank=True, max_length=12)),
            ("to_status", models.CharField(blank=True, max_length=12)),
            ("note", models.CharField(blank=True, max_length=300)),
            ("actor_id", models.UUIDField(blank=True, null=True)),
            ("actor_username", models.CharField(blank=True, max_length=150)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("task", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="events", to="personnel.unittask")),
        ], options={"db_table": "unit_task_events", "ordering": ["created_at", "id"]}),
    ]
