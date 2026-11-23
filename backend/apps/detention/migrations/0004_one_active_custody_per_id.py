from django.db import migrations, models


def backfill_id_keys(apps, schema_editor):
    """Give every person currently in custody their duplicate-detection key. If the old data already holds the same ID twice in
    custody, only the earliest keeps the key: nothing is changed or removed, the later row is simply not covered by the new rule."""
    Record = apps.get_model("detention", "DetentionRecord")
    seen = set()
    for r in Record.objects.filter(status="in_custody").exclude(id_ref="").order_by("booked_at", "created_at"):
        key = "".join(ch for ch in r.id_ref.upper() if ch.isalnum())[:80]
        if key and key not in seen:
            seen.add(key)
            Record.objects.filter(pk=r.pk).update(id_ref_key=key)


class Migration(migrations.Migration):
    # Separate from 0003 so the data step and the new index never share a transaction with the table changes.
    dependencies = [("detention", "0003_station_detention_units")]

    operations = [
        migrations.RunPython(backfill_id_keys, migrations.RunPython.noop),
        migrations.AddConstraint(model_name="detentionrecord", constraint=models.UniqueConstraint(
            condition=models.Q(("id_ref_key", ""), _negated=True), fields=("id_ref_key",), name="det_one_active_custody_per_id")),
    ]
