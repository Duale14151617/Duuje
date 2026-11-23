from django.db import migrations

from apps.core.db_triggers import append_only_trigger


class Migration(migrations.Migration):
    dependencies = [("payroll", "0001_initial")]
    operations = [append_only_trigger("payroll_transactions"), append_only_trigger("payroll_run_actions"),
                  append_only_trigger("survivor_payments")]
