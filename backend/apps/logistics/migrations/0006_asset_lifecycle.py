import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("logistics", "0005_food_batch_opening_source")]

    operations = [
        migrations.AddField(model_name="asset", name="manufacturer", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="asset", name="model", field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name="asset", name="condition", field=models.CharField(
            choices=[("new", "New"), ("good", "Good"), ("fair", "Fair"), ("poor", "Poor"), ("unserviceable", "Unserviceable")],
            default="good", max_length=16)),
        migrations.AddField(model_name="asset", name="acquisition_cost", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="asset", name="currency", field=models.CharField(blank=True, max_length=3)),
        migrations.AddField(model_name="asset", name="acquired_on", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="asset", name="procurement_ref", field=models.CharField(blank=True, max_length=60)),
        migrations.AddField(model_name="asset", name="last_inspected_on", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="asset", name="next_inspection_due", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="asset", name="replaced_by", field=models.OneToOneField(
            blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="replaces", to="logistics.asset")),
        migrations.AddIndex(model_name="asset", index=models.Index(fields=["org_unit", "status"], name="asset_unit_status")),
        migrations.AddIndex(model_name="asset", index=models.Index(fields=["next_inspection_due"], name="asset_next_inspection")),
        migrations.AddField(model_name="stocktransaction", name="unit_cost", field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True)),
        migrations.AddField(model_name="stocktransaction", name="currency", field=models.CharField(blank=True, max_length=3)),
    ]
