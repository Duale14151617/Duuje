from django.db import migrations, models


class Migration(migrations.Migration):
    """Rank categories back to the four used by the Army list. Choices only: no table or data changes."""

    dependencies = [
        ("ranks", "0005_police_rank_categories"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rank",
            name="category",
            field=models.CharField(
                choices=[("enlisted", "Enlisted"), ("warrant", "Warrant"), ("officer", "Officer"),
                         ("unspecified", "Unspecified")],
                max_length=16),
        ),
    ]
