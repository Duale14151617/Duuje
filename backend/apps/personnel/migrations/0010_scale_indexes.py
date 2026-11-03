from django.db import migrations, models


class Migration(migrations.Migration):
    """Indexes for 10,000+ personnel: unit + status filters (dashboard, lists), status, and the default name ordering."""

    dependencies = [("personnel", "0009_unit_tasks")]

    operations = [
        migrations.AddIndex(model_name="personnel", index=models.Index(fields=["org_unit", "status"], name="personnel_unit_status")),
        migrations.AddIndex(model_name="personnel", index=models.Index(fields=["status"], name="personnel_status")),
        migrations.AddIndex(model_name="personnel", index=models.Index(fields=["full_name", "id"], name="personnel_name_id")),
    ]
