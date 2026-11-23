from django.db import migrations, models


class Migration(migrations.Migration):
    """Adds the appointment request kinds. Choices only: no table or data changes."""

    dependencies = [("organization", "0007_change_request")]

    operations = [
        migrations.AlterField(model_name="changerequest", name="kind", field=models.CharField(
            choices=[("transfer", "Transfer"), ("appointment_add", "Appointment Add"), ("appointment_end", "Appointment End")],
            db_index=True, max_length=20)),
    ]
