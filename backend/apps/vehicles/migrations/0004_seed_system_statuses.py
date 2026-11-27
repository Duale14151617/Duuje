"""The six built-in statuses exist from the moment the table does, so every existing vehicle row already has a valid status."""
from django.db import migrations

SYSTEM = [("operational", "Operational", "Shaqeynaya", True, 10), ("under_maintenance", "Under maintenance", "Dayactir hoostiisa", False, 20),
          ("under_repair", "Under repair", "Hagaajin hoostiisa", False, 30), ("out_of_service", "Out of service", "Shaqada ka baxay", False, 40),
          ("awaiting_inspection", "Awaiting inspection", "Hubin sugaya", False, 50), ("decommissioned", "Decommissioned", "Laga saaray adeegga", False, 90)]


def seed(apps, schema_editor):
    T = apps.get_model("vehicles", "VehicleStatusType")
    for code, en, so, avail, order in SYSTEM:
        T.objects.get_or_create(code=code, defaults={"name_en": en, "name_so": so, "available": avail, "is_system": True, "sort_order": order})


class Migration(migrations.Migration):
    dependencies = [("vehicles", "0003_configurable_statuses")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
