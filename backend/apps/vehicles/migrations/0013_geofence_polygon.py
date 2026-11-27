from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("vehicles", "0012_geofences")]

    operations = [
        migrations.AddField(model_name="geofence", name="shape", field=models.CharField(choices=[("circle", "Circle"), ("polygon", "Polygon")], default="circle", max_length=7)),
        migrations.AddField(model_name="geofence", name="points", field=models.JSONField(blank=True, default=list)),
    ]
