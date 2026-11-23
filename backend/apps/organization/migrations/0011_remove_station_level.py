from django.db import migrations, models


class Migration(migrations.Migration):
    """Removes the station level from the choices. Choices only: no table or data changes."""

    dependencies = [
        ("organization", "0010_change_request_rank_status"),
    ]

    operations = [
        migrations.AlterField(
            model_name="organizationalunit",
            name="level",
            field=models.CharField(choices=[
                ("headquarters", "Hq"), ("region", "Region"), ("branch_command", "Branch"),
                ("unit", "Unit")], max_length=20),
        ),
    ]
