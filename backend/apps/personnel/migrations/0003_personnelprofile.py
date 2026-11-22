import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("personnel", "0002_append_only_triggers"),
    ]

    operations = [
        migrations.CreateModel(
            name="PersonnelProfile",
            fields=[
                ("personnel", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True,
                                                   related_name="profile", serialize=False, to="personnel.personnel")),
                ("data_enc", models.TextField(blank=True, default="")),
                ("photo_enc", models.BinaryField(blank=True, null=True)),
                ("photo_updated_at", models.DateTimeField(blank=True, null=True)),
                ("weapon_key", models.CharField(blank=True, editable=False, max_length=64, null=True, unique=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "personnel_profile"},
        ),
    ]
