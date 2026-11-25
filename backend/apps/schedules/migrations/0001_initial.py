import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organization", "0012_departments_and_formation_roles"),
    ]
    operations = [
        migrations.CreateModel(
            name="ReportSchedule",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("report", models.CharField(default="strength", max_length=20)),
                ("frequency", models.CharField(choices=[("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")], default="weekly", max_length=8)),
                ("weekday", models.PositiveSmallIntegerField(default=0)),
                ("day_of_month", models.PositiveSmallIntegerField(default=1)),
                ("send_hour", models.PositiveSmallIntegerField(default=7)),
                ("period_days", models.PositiveSmallIntegerField(default=7)),
                ("enabled", models.BooleanField(default=True)),
                ("next_run_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("last_run_at", models.DateTimeField(blank=True, null=True)),
                ("last_status", models.CharField(blank=True, max_length=24)),
                ("last_detail", models.CharField(blank=True, max_length=200)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
                ("recipients", models.ManyToManyField(blank=True, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "report_schedules", "ordering": ["name", "id"]},
        ),
    ]
