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

    dependencies = [
        ("personnel", "0006_death_record_and_statuses"),
        ("organization", "0006_station_level"),
        ("accounts", "0002_mfa_replay_and_password_reset"),
    ]

    operations = [
        migrations.CreateModel(
            name="AppointmentType",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code", models.CharField(max_length=40, unique=True)),
                ("name_en", models.CharField(max_length=120)),
                ("name_so", models.CharField(blank=True, max_length=120)),
                ("exclusive", models.BooleanField(default=True, help_text="Only one current holder per unit.")),
                ("active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("unit_type", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                related_name="+", to="organization.unittype")),
            ],
            options={"db_table": "personnel_appointment_types", "ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="CommandAppointment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("exclusive", models.BooleanField(default=True)),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("authority_ref", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by_id", models.UUIDField(blank=True, null=True)),
                ("created_by_username", models.CharField(blank=True, max_length=150)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("ended_by_id", models.UUIDField(blank=True, null=True)),
                ("ended_by_username", models.CharField(blank=True, max_length=150)),
                ("end_reason", models.CharField(blank=True, max_length=300)),
                ("appointment_type", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                       related_name="appointments", to="personnel.appointmenttype")),
                ("org_unit", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                               to="organization.organizationalunit")),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                related_name="appointments", to="personnel.personnel")),
                ("role_assignment", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                                      related_name="+", to="accounts.roleassignment")),
            ],
            options={"db_table": "personnel_command_appointments", "ordering": ["-effective_from", "-created_at"]},
        ),
        migrations.AddConstraint(
            model_name="commandappointment",
            constraint=models.UniqueConstraint(fields=["org_unit", "appointment_type"], name="appointment_one_open_exclusive",
                                               condition=models.Q(ended_at__isnull=True, exclusive=True)),
        ),
        migrations.AddConstraint(
            model_name="commandappointment",
            constraint=models.CheckConstraint(
                condition=models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=models.F("effective_from")),
                name="appointment_dates_ordered"),
        ),
        no_delete_trigger("personnel_command_appointments"),
    ]
