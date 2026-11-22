import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import _runner


def no_delete_trigger(table):
    fn = f"{table}_no_delete"
    forward = [
        f"""CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION '{table} rows cannot be deleted'; END; $$ LANGUAGE plpgsql""",
        f"""CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {fn}()""",
    ]
    reverse = [f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}", f"DROP FUNCTION IF EXISTS {fn}()"]
    return migrations.RunPython(_runner(forward), _runner(reverse))


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("personnel", "0008_attendance_support_category"),
        ("organization", "0006_station_level"),
    ]

    operations = [
        migrations.CreateModel(
            name="AbsenceReason",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=40, unique=True)),
                ("name_en", models.CharField(max_length=120)),
                ("name_so", models.CharField(blank=True, max_length=120)),
                ("requires_document", models.BooleanField(default=False)),
                ("active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "attendance_absence_reasons", "ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="AttendanceRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("report_date", models.DateField()),
                ("status", models.CharField(choices=[("present", "Present"), ("absent", "Absent"), ("on_leave", "On Leave")], max_length=10)),
                ("note", models.CharField(blank=True, max_length=300)),
                ("reported_by_id", models.UUIDField(blank=True, null=True)),
                ("reported_by_username", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("superseded_at", models.DateTimeField(blank=True, null=True)),
                ("amend_reason", models.CharField(blank=True, max_length=300)),
                ("document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                               related_name="+", to="personnel.personneldocument")),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                               to="organization.organizationalunit")),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="attendance",
                                                to="personnel.personnel")),
                ("reason", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                             related_name="+", to="attendance.absencereason")),
                ("supersedes", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                 related_name="amendments", to="attendance.attendancerecord")),
            ],
            options={"db_table": "attendance_records", "ordering": ["-report_date", "personnel_id", "-created_at"]},
        ),
        migrations.AddIndex(
            model_name="attendancerecord",
            index=models.Index(fields=["org_unit", "report_date"], name="attendance_unit_day_idx"),
        ),
        migrations.AddConstraint(
            model_name="attendancerecord",
            constraint=models.UniqueConstraint(fields=["personnel", "report_date"], condition=models.Q(superseded_at__isnull=True),
                                               name="attendance_one_current_per_day"),
        ),
        migrations.AddConstraint(
            model_name="attendancerecord",
            constraint=models.CheckConstraint(condition=models.Q(status="absent") | models.Q(reason__isnull=True),
                                              name="attendance_reason_only_when_absent"),
        ),
        no_delete_trigger("attendance_records"),
    ]
