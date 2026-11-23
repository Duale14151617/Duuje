"""Vehicle ownership: state property (plates start GD) or private (plates start PL).
Existing vehicles default to state property; their stored plates are left exactly as recorded (nothing is rewritten or invented)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0005_category_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="ownership",
            field=models.CharField(choices=[("state", "State"), ("private", "Private")], default="state", max_length=10),
        ),
        migrations.AddIndex(
            model_name="vehicle",
            index=models.Index(fields=["ownership"], name="vehicle_ownership_idx"),
        ),
    ]
