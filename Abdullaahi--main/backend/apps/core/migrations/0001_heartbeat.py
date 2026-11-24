from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Heartbeat",
            fields=[
                ("name", models.CharField(max_length=40, primary_key=True, serialize=False)),
                ("at", models.DateTimeField()),
                ("detail", models.CharField(blank=True, max_length=200)),
            ],
            options={"db_table": "heartbeats"},
        ),
    ]
