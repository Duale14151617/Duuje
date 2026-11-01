import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import append_only_trigger, _runner


def no_delete_trigger(table):
    """Documents may change only to be withdrawn, but a row can never be removed (not even by a compromised app account)."""
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
        ("personnel", "0003_personnelprofile"),
    ]

    operations = [
        migrations.CreateModel(
            name="DisciplinaryRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("data_enc", models.TextField()),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                ("recorded_by_id", models.UUIDField(blank=True, null=True)),
                ("recorded_by_username", models.CharField(blank=True, max_length=150)),
                ("corrects", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                               related_name="corrections", to="personnel.disciplinaryrecord")),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                related_name="disciplinary_records", to="personnel.personnel")),
            ],
            options={"db_table": "personnel_disciplinary", "ordering": ["-recorded_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="disciplinaryrecord",
            index=models.Index(fields=["personnel", "-recorded_at"], name="pdisc_person_idx"),
        ),
        migrations.CreateModel(
            name="PersonnelDocument",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("category", models.CharField(choices=[
                    ("service_record", "Service Record"), ("appointment", "Appointment"),
                    ("training_certificate", "Training Certificate"), ("commendation", "Commendation"),
                    ("identity", "Identity"), ("other", "Other")], max_length=24)),
                ("meta_enc", models.TextField()),
                ("content_enc", models.BinaryField()),
                ("content_type", models.CharField(max_length=40)),
                ("size_bytes", models.PositiveIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                ("uploaded_by_id", models.UUIDField(blank=True, null=True)),
                ("uploaded_by_username", models.CharField(blank=True, max_length=150)),
                ("withdrawn_at", models.DateTimeField(blank=True, null=True)),
                ("withdrawn_by_id", models.UUIDField(blank=True, null=True)),
                ("withdrawn_by_username", models.CharField(blank=True, max_length=150)),
                ("withdrawn_reason_enc", models.TextField(blank=True, default="")),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,
                                                related_name="documents", to="personnel.personnel")),
            ],
            options={"db_table": "personnel_documents", "ordering": ["-uploaded_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="personneldocument",
            index=models.Index(fields=["personnel", "-uploaded_at"], name="pdoc_person_idx"),
        ),
        append_only_trigger("personnel_disciplinary"),
        no_delete_trigger("personnel_documents"),
    ]
