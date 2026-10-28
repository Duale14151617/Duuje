from django.db import migrations, models


class Migration(migrations.Migration):
    """Lets a food batch say it came from an opening-balance import. Only the list of allowed values changes; no table is altered."""

    dependencies = [("logistics", "0004_food_stores")]

    operations = [
        migrations.AlterField(
            model_name="foodbatch", name="source",
            field=models.CharField(choices=[("receipt", "Receipt"), ("allocation", "Allocation"), ("opening", "Opening")],
                                   default="receipt", max_length=10)),
    ]
