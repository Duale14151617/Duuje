import uuid

import django.db.models.deletion
from django.db import migrations, models

LEAVE_TYPES = [  # code, English, Somali (working translation, needs review), max days per request
    ("annual", "Annual leave", "Fasax sannadeed", 30),
    ("sick", "Sick leave", "Fasax jiro", None),
    ("compassionate", "Compassionate leave", "Fasax naxariis", 14),
    ("study", "Study leave", "Fasax waxbarasho", None),
    ("other", "Other leave", "Fasax kale", None),
]


def seed_types(apps, schema_editor):
    LeaveType = apps.get_model("leave", "LeaveType")
    for code, en, so, cap in LEAVE_TYPES:
        LeaveType.objects.get_or_create(code=code, defaults={"name_en": en, "name_so": so, "max_days": cap})


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("personnel", "0008_attendance_support_category"),
        ("organization", "0006_station_level"),
    ]

    operations = [
        migrations.CreateModel(
            name="LeaveType",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=40, unique=True)),
                ("name_en", models.CharField(max_length=120)),
                ("name_so", models.CharField(blank=True, max_length=120)),
                ("max_days", models.PositiveIntegerField(blank=True, null=True)),
                ("active", models.BooleanField(default=True)),
            ],
            options={"db_table": "leave_types", "ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="LeaveRequest",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("start_date", models.DateField()),
                ("end_date", models.DateField()),
                ("reason", models.CharField(blank=True, max_length=300)),
                ("status", models.CharField(choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected"), ("cancelled", "Cancelled")], db_index=True, default="pending", max_length=10)),
                ("requested_by_id", models.UUIDField(blank=True, null=True)),
                ("requested_by_username", models.CharField(blank=True, max_length=150)),
                ("decided_by_id", models.UUIDField(blank=True, null=True)),
                ("decided_by_username", models.CharField(blank=True, max_length=150)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("leave_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="leave.leavetype")),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="leave_requests", to="personnel.personnel")),
            ],
            options={"db_table": "leave_requests", "ordering": ["-start_date", "-created_at"]},
        ),
        migrations.AddIndex(model_name="leaverequest", index=models.Index(fields=["org_unit", "start_date"], name="leave_unit_start_idx")),
        migrations.AddConstraint(model_name="leaverequest", constraint=models.CheckConstraint(condition=models.Q(("end_date__gte", models.F("start_date"))), name="leave_end_after_start")),
        migrations.CreateModel(
            name="RosterShift",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("duty_date", models.DateField()),
                ("shift", models.CharField(choices=[("day", "Day"), ("night", "Night"), ("standby", "Standby"), ("off", "Off")], max_length=8)),
                ("post", models.CharField(blank=True, max_length=100)),
                ("set_by_username", models.CharField(blank=True, max_length=150)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="organization.organizationalunit")),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="roster_shifts", to="personnel.personnel")),
            ],
            options={"db_table": "leave_roster_shifts", "ordering": ["duty_date", "personnel_id"]},
        ),
        migrations.AddIndex(model_name="rostershift", index=models.Index(fields=["org_unit", "duty_date"], name="roster_unit_day_idx")),
        migrations.AddConstraint(model_name="rostershift", constraint=models.UniqueConstraint(fields=["personnel", "duty_date"], name="roster_one_per_person_day")),
        migrations.RunPython(seed_types, migrations.RunPython.noop),
    ]
