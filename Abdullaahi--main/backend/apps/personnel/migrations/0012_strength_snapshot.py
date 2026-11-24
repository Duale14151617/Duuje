from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("personnel", "0011_department_and_appointment_roles"),
    ]

    operations = [
        migrations.CreateModel(
            name="StrengthSnapshot",
            fields=[
                ("date", models.DateField(primary_key=True, serialize=False)),
                ("total_all", models.PositiveIntegerField()),
                ("serving_all", models.PositiveIntegerField()),
                ("total_open", models.PositiveIntegerField()),
                ("serving_open", models.PositiveIntegerField()),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "strength_snapshots", "ordering": ["date"]},
        ),
    ]
