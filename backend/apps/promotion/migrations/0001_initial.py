import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [("ranks", "0001_initial")]

    operations = [
        migrations.CreateModel(
            name="PromotionRule",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("min_months", models.PositiveSmallIntegerField()),
                ("active", models.BooleanField(default=True)),
                ("updated_by_username", models.CharField(blank=True, max_length=150)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("next_rank", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to="ranks.rank")),
                ("rank", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="promotion_rule", to="ranks.rank")),
            ],
            options={"db_table": "promotion_rules"},
        ),
        migrations.AddConstraint(
            model_name="promotionrule",
            constraint=models.CheckConstraint(condition=models.Q(("min_months__gte", 1), ("min_months__lte", 600)), name="promotion_months_range"),
        ),
    ]
