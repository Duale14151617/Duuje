import uuid

import django.db.models.deletion
from django.db import migrations, models

from apps.core.db_triggers import append_only_trigger


class Migration(migrations.Migration):
    dependencies = [
        ("weapons", "0001_initial"),
        ("logistics", "0001_initial"),
        ("personnel", "0008_attendance_support_category"),
    ]

    operations = [
        migrations.CreateModel(
            name="SoldierRounds",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("kind", models.CharField(choices=[("issue", "Issue"), ("return", "Return"), ("expended", "Expended"), ("lost", "Lost")], max_length=10)),
                ("delta", models.IntegerField()),
                ("reference", models.CharField(blank=True, max_length=60)),
                ("authority_ref", models.CharField(blank=True, max_length=150)),
                ("note", models.CharField(blank=True, max_length=300)),
                ("actor_id", models.UUIDField(blank=True, null=True)),
                ("actor_username", models.CharField(blank=True, max_length=150)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("personnel", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="rounds_ledger", to="personnel.personnel")),
                ("stock_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="logistics.stockline")),
            ],
            options={"db_table": "soldier_rounds", "ordering": ["-created_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="soldierrounds",
            index=models.Index(fields=["personnel", "stock_line"], name="soldier_rounds_person_line"),
        ),
        migrations.AddConstraint(
            model_name="soldierrounds",
            constraint=models.CheckConstraint(condition=~models.Q(delta=0), name="soldier_rounds_nonzero"),
        ),
        migrations.AddConstraint(
            model_name="soldierrounds",
            constraint=models.CheckConstraint(
                condition=models.Q(kind="issue", delta__gt=0) | models.Q(kind__in=["return", "expended", "lost"], delta__lt=0),
                name="soldier_rounds_sign_by_kind"),
        ),
        append_only_trigger("soldier_rounds"),
    ]
