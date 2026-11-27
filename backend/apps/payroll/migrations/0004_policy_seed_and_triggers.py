from django.db import migrations

from apps.core.db_triggers import append_only_trigger
from apps.payroll.policy_defaults import seed_policy


def seed(apps, schema_editor):
    seed_policy(apps.get_model("payroll", "PolicySetting"))


class Migration(migrations.Migration):
    dependencies = [("payroll", "0003_policy_payments_arrears")]
    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
        append_only_trigger("payroll_payment_events"), append_only_trigger("payroll_arrears_payments"),
        append_only_trigger("survivor_beneficiary_changes"),
    ]
