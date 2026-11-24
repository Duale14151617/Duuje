from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("personnel", "0007_command_appointments")]

    operations = [
        migrations.AlterField(
            model_name="personneldocument",
            name="category",
            field=models.CharField(
                choices=[("service_record", "Service Record"), ("appointment", "Appointment"),
                         ("training_certificate", "Training Certificate"), ("commendation", "Commendation"),
                         ("identity", "Identity"), ("death_evidence", "Death Evidence"),
                         ("attendance_support", "Attendance Support"), ("other", "Other")],
                max_length=24),
        ),
    ]
