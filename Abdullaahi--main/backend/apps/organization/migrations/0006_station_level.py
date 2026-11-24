from django.db import migrations, models


class Migration(migrations.Migration):
    """Adds the Police station level. Choices only: no table or data changes."""

    dependencies = [
        ("organization", "0005_unit_restricted"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organizationalunit",
            name="level",
            field=models.CharField(choices=[
                ("headquarters", "Hq"), ("region", "Region"), ("branch_command", "Branch"),
                ("unit", "Unit"), ("station", "Station")], max_length=20),
        ),
    ]
