from django.db import migrations

from apps.core.db_triggers import append_only_trigger


class Migration(migrations.Migration):
    dependencies = [("logistics", "0001_initial")]
    operations = [append_only_trigger("stock_transactions"), append_only_trigger("asset_events")]
