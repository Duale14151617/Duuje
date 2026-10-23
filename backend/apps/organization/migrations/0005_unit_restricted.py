from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("organization", "0004_structure_change"),
    ]

    operations = [
        migrations.AddField(
            model_name="organizationalunit",
            name="restricted",
            field=models.BooleanField(default=False),
        ),
    ]
