"""Administrative group for vehicle categories (utility, personnel transport, general transport, protected transport, other).
Existing categories are filled in from their codes; anything not recognised stays in "other" and HQ can regroup it."""
from django.db import migrations, models

GROUPS = {
    "hilux_4x4": "utility", "utility": "utility",
    "bus": "personnel_transport",
    "truck": "general_transport",
    "armored_truck": "protected_transport",
}


def fill_groups(apps, schema_editor):
    Category = apps.get_model("vehicles", "VehicleCategory")
    for code, group in GROUPS.items():
        Category.objects.filter(code=code).update(group=group)


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0004_seed_system_statuses"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehiclecategory",
            name="group",
            field=models.CharField(
                choices=[("utility", "Utility"), ("personnel_transport", "Personnel Transport"), ("general_transport", "General Transport"),
                         ("protected_transport", "Protected Transport"), ("other", "Other")],
                default="other", max_length=24),
        ),
        migrations.RunPython(fill_groups, migrations.RunPython.noop),
    ]
