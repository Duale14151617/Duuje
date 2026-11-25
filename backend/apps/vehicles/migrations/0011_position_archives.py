import uuid

from django.db import migrations, models

from apps.core.db_triggers import no_delete_trigger

# Before: vehicle_positions_no_delete() refused every delete. After: it still refuses, except for rows that an archive in the ledger
# (vehicle_position_archives, status 'archived') covers, that are older than 30 days, and only in a transaction that names that archive
# (SET LOCAL policehq.purge_archive = '<batch id>'). `purge_positions` is the only code that does this.
OLD_FN = """CREATE OR REPLACE FUNCTION vehicle_positions_no_delete() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'vehicle_positions rows cannot be deleted'; END; $$ LANGUAGE plpgsql"""

NEW_FN = """CREATE OR REPLACE FUNCTION vehicle_positions_no_delete() RETURNS trigger AS $$
        DECLARE aid text;
        BEGIN
            aid := current_setting('policehq.purge_archive', true);
            IF aid IS NOT NULL AND aid <> ''
               AND OLD.recorded_at < now() - interval '30 days'
               AND EXISTS (SELECT 1 FROM vehicle_position_archives a
                           WHERE a.id = aid::uuid AND a.status = 'archived'
                             AND OLD.recorded_at >= a.range_start AND OLD.recorded_at <= a.range_end) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION 'vehicle_positions rows cannot be deleted';
        END; $$ LANGUAGE plpgsql"""


def _swap(sql):
    def run(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql":
            schema_editor.execute(sql)
    return run


class Migration(migrations.Migration):
    dependencies = [("vehicles", "0010_vehicle_positions")]

    operations = [
        migrations.CreateModel(
            name="VehiclePositionArchive",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.CharField(max_length=150)),
                ("cutoff", models.DateTimeField()),
                ("range_start", models.DateTimeField()),
                ("range_end", models.DateTimeField()),
                ("row_count", models.PositiveIntegerField()),
                ("file_name", models.CharField(max_length=255)),
                ("data_sha256", models.CharField(max_length=64)),
                ("signature", models.CharField(max_length=128)),
                ("key_fingerprint", models.CharField(max_length=16)),
                ("status", models.CharField(choices=[("archived", "Archived"), ("purged", "Purged"), ("abandoned", "Abandoned")], default="archived", max_length=10)),
                ("closed_at", models.DateTimeField(blank=True, null=True)),
                ("closed_by", models.CharField(blank=True, max_length=150)),
                ("purged_count", models.PositiveIntegerField(default=0)),
                ("skipped_count", models.PositiveIntegerField(default=0)),
            ],
            options={"db_table": "vehicle_position_archives", "ordering": ["-created_at"]},
        ),
        no_delete_trigger("vehicle_position_archives"),
        migrations.RunPython(_swap(NEW_FN), _swap(OLD_FN)),
    ]
