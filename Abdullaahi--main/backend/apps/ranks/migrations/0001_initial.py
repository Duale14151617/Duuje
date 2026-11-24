import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("organization", "0001_initial"),
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Rank",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("category", models.CharField(choices=[("enlisted", "Enlisted"), ("warrant", "Warrant"), ("officer", "Officer")], max_length=10)),
                ("code", models.CharField(max_length=16)),
                ("name_en", models.CharField(max_length=100)),
                ("name_so", models.CharField(blank=True, max_length=100)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("approval_status", models.CharField(choices=[("draft", "Draft"), ("approved", "Approved")], default="draft", max_length=10)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("active", models.BooleanField(default=True)),
                ("version", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("branch", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="ranks", to="organization.servicebranch")),
            ],
            options={"db_table": "ranks", "ordering": ["branch__code", "sort_order"]},
        ),
        migrations.AddConstraint(
            model_name="rank",
            constraint=models.UniqueConstraint(fields=("branch", "code"), name="rank_unique_code_per_branch"),
        ),
    ]
