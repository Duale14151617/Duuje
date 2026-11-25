from django.db import migrations


def forwards(apps, schema_editor):
    """One-off cleanup: remove the unsubmitted 'New thing' draft. Drafts were never applied, so live structure is unaffected."""
    StructureChange = apps.get_model("organization", "StructureChange")
    StructureChange.objects.filter(title="New thing", status="draft").delete()


class Migration(migrations.Migration):
    dependencies = [("organization", "0014_police_station_departments")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
