from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("logistics", "0006_asset_lifecycle")]

    operations = [
        migrations.AddField(model_name="stocktransaction", name="lot", field=models.CharField(blank=True, max_length=40)),
    ]
