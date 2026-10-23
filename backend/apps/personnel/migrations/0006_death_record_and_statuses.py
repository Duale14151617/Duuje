import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import _runner


def no_delete_trigger(table):
    """A death record can be withdrawn but never removed, even by a compromised application account."""
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
        ("personnel", "0005_supervisor_and_account"),
    ]

    operations = [
        migrations.AlterField(
            model_name="personnel",
            name="status",
            field=models.CharField(
                choices=[("active", "Active"), ("on_leave", "On Leave"), ("suspended", "Suspended"), ("jailed", "Jailed"),
                         ("died", "Died"), ("retired", "Retired"), ("discharged", "Discharged")],
                default="active", max_length=12),
        ),
        migrations.AlterField(
            model_name="personneldocument",
            name="category",
            field=models.CharField(
                choices=[("service_record", "Service Record"), ("appointment", "Appointment"),
                         ("training_certificate", "Training Certificate"), ("commendation", "Commendation"),
                         ("identity", "Identity"), ("death_evidence", "Death Evidence"), ("other", "Other")],
                max_length=24),
        ),
        migrations.CreateModel(
            name="DeathRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("date_of_death", models.DateField()),
                ("note", models.CharField(blank=True, max_length=300)),
                ("state", models.CharField(choices=[("reported", "Reported"), ("confirmed", "Confirmed"),
                                                    ("withdrawn", "Withdrawn")], default="reported", max_length=10)),
                ("reported_at", models.DateTimeField(auto_now_add=True)),
                ("reported_by_id", models.UUIDField(blank=True, null=True)),
                ("reported_by_username", models.CharField(blank=True, max_length=150)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("confirmed_by_id", models.UUIDField(blank=True, null=True)),
                ("confirmed_by_username", models.CharField(blank=True, max_length=150)),
                ("withdrawn_at", models.DateTimeField(blank=True, null=True)),
                ("withdrawn_by_id", models.UUIDField(blank=True, null=True)),
                ("withdrawn_by_username", models.CharField(blank=True, max_length=150)),
                ("withdrawn_reason", models.CharField(blank=True, max_length=300)),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                related_name="death_records", to="personnel.personnel")),
            ],
            options={"db_table": "personnel_death_records", "ordering": ["-reported_at", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="deathrecord",
            constraint=models.UniqueConstraint(fields=["personnel"], condition=~models.Q(state="withdrawn"),
                                               name="death_one_open_record_per_person"),
        ),
        migrations.AddConstraint(
            model_name="deathrecord",
            constraint=models.CheckConstraint(
                condition=~models.Q(state="confirmed") | (models.Q(confirmed_at__isnull=False) & models.Q(confirmed_by_id__isnull=False)),
                name="death_confirmed_has_confirmer"),
        ),
        no_delete_trigger("personnel_death_records"),
    ]
