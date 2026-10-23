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


CONDITIONS = [("serviceable", "Serviceable"), ("needs_repair", "Needs Repair"), ("unserviceable", "Unserviceable")]


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("logistics", "0001_initial"),
        ("personnel", "0008_attendance_support_category"),
        ("organization", "0006_station_level"),
    ]

    operations = [
        migrations.CreateModel(
            name="WeaponDetail",
            fields=[
                ("asset", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, primary_key=True,
                                               related_name="weapon", serialize=False, to="logistics.asset")),
                ("weapon_type", models.CharField(max_length=60)),
                ("make_model", models.CharField(blank=True, max_length=120)),
                ("caliber", models.CharField(blank=True, max_length=40)),
                ("condition", models.CharField(choices=CONDITIONS, default="serviceable", max_length=16)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "weapon_details"},
        ),
        migrations.CreateModel(
            name="WeaponCustody",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("issued_by_id", models.UUIDField(blank=True, null=True)),
                ("issued_by_username", models.CharField(blank=True, max_length=150)),
                ("authority_ref", models.CharField(max_length=150)),
                ("issue_condition", models.CharField(choices=CONDITIONS, max_length=16)),
                ("issue_note", models.CharField(blank=True, max_length=300)),
                ("status_before", models.CharField(max_length=12)),
                ("returned_at", models.DateTimeField(blank=True, null=True)),
                ("returned_by_id", models.UUIDField(blank=True, null=True)),
                ("returned_by_username", models.CharField(blank=True, max_length=150)),
                ("outcome", models.CharField(blank=True, choices=[("returned", "Returned"), ("lost", "Lost"), ("missing", "Missing")], max_length=10)),
                ("return_condition", models.CharField(blank=True, choices=CONDITIONS, max_length=16)),
                ("return_note", models.CharField(blank=True, max_length=300)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="custody", to="logistics.asset")),
                ("issued_unit_before", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                                         related_name="+", to="organization.organizationalunit")),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="weapon_custody", to="personnel.personnel")),
            ],
            options={"db_table": "weapon_custody", "ordering": ["-issued_at"]},
        ),
        migrations.AddConstraint(
            model_name="weaponcustody",
            constraint=models.UniqueConstraint(fields=["asset"], condition=models.Q(returned_at__isnull=True), name="weapon_one_open_custody"),
        ),
        migrations.AddConstraint(
            model_name="weaponcustody",
            constraint=models.CheckConstraint(
                condition=models.Q(returned_at__isnull=True, outcome="") | models.Q(returned_at__isnull=False) & ~models.Q(outcome=""),
                name="weapon_custody_closed_has_outcome"),
        ),
        no_delete_trigger("weapon_custody"),
    ]
