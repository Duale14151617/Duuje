from django.db import migrations

from apps.core.db_triggers import append_only_trigger


class Migration(migrations.Migration):
    dependencies = [("workflows", "0001_initial")]
    operations = [append_only_trigger("approval_actions"), append_only_trigger("submission_revisions")]
