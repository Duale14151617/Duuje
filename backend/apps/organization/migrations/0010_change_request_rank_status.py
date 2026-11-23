from django.db import migrations, models


class Migration(migrations.Migration):
    """Adds the rank-change and status-change request kinds. Choices only: no table or data changes."""

    dependencies = [("organization", "0009_change_request_batch")]

    operations = [
        migrations.AlterField(model_name="changerequest", name="kind", field=models.CharField(
            choices=[("transfer", "Transfer"), ("appointment_add", "Appointment Add"), ("appointment_end", "Appointment End"),
                     ("rank_change", "Rank Change"), ("status_change", "Status Change")],
            db_index=True, max_length=20)),
    ]
