"""Payment event statuses include reconciliation states ("unreconciled", "discrepancy") longer than 10 characters.
Widening a varchar is additive and rewrites no rows."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("payroll", "0005_policy_answers_and_deduction")]
    operations = [
        migrations.AlterField("paymentevent", "from_status", models.CharField(blank=True, max_length=16)),
        migrations.AlterField("paymentevent", "to_status", models.CharField(blank=True, max_length=16)),
    ]
