import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("schedules", "0001_initial"),
    ]
    operations = [
        migrations.CreateModel(
            name="AlertPreference",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "alert_preferences"},
        ),
        migrations.CreateModel(
            name="AlertLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(max_length=20)),
                ("key", models.CharField(max_length=120)),
                ("sent_at", models.DateTimeField(auto_now_add=True)),
                ("recipients", models.PositiveSmallIntegerField(default=0)),
            ],
            options={"db_table": "alert_log", "ordering": ["-sent_at"]},
        ),
        migrations.AddConstraint(
            model_name="alertpreference",
            constraint=models.UniqueConstraint(fields=("user", "kind"), name="alertpref_user_kind_uniq"),
        ),
        migrations.AddConstraint(
            model_name="alertlog",
            constraint=models.UniqueConstraint(fields=("kind", "key"), name="alertlog_kind_key_uniq"),
        ),
    ]
