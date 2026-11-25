"""Adds the main category "Police Vehicles" to the vehicle category groups. No data changes: the Police vehicle types are created by
the apply_police_fleet command (police profile only)."""
from django.db import migrations, models

GROUPS = [("police_vehicles", "Police Vehicles"), ("utility", "Utility"), ("personnel_transport", "Personnel Transport"),
          ("general_transport", "General Transport"), ("protected_transport", "Protected Transport"),
          ("combat_vehicle", "Combat Vehicle"), ("other", "Other")]


class Migration(migrations.Migration):
    dependencies = [("vehicles", "0007_reference_models_photos_armament")]

    operations = [
        migrations.AlterField(model_name="vehiclecategory", name="group", field=models.CharField(choices=GROUPS, default="other", max_length=24)),
    ]
