"""The institution's answers to the open policy items, and the deduction tier on suspended/jailed pay decisions.
Additive: one column with a default of 0 (no deduction), so every existing decision keeps its meaning."""
from django.db import migrations, models

from apps.payroll.policy_defaults import upgrade_open_items


def upgrade(apps, schema_editor):
    upgrade_open_items(apps.get_model("payroll", "PolicySetting"))


class Migration(migrations.Migration):
    dependencies = [("payroll", "0004_policy_seed_and_triggers")]
    operations = [
        migrations.AddField("statuspaydecision", "deduction_percent", models.PositiveSmallIntegerField(default=0)),
        migrations.RunPython(upgrade, migrations.RunPython.noop),
    ]
