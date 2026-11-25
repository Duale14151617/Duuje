from django.db import migrations, models


class Migration(migrations.Migration):
    """Two more formation roles (district, police station) so districts and stations show in the organizational chart under their
    regional command, each with its jail center. Choices only: no data is changed."""

    dependencies = [("organization", "0012_departments_and_formation_roles")]

    operations = [
        migrations.AlterField(
            model_name="unittype", name="formation_role",
            field=models.CharField(blank=True, choices=[
                ("ghq", "General Headquarters"), ("regional", "Regional command"), ("brigade", "Brigade"),
                ("battalion", "Battalion"), ("district", "District"), ("station", "Police station")], default="", max_length=10),
        ),
    ]
