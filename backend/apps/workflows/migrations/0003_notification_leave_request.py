import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("workflows", "0002_append_only_triggers"), ("leave", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="leave_request",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="leave.leaverequest"),
        ),
    ]
