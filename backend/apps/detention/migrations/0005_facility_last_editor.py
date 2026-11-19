from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("detention", "0004_one_active_custody_per_id")]

    operations = [
        migrations.AddField(model_name="custodyfacility", name="last_edited_by_username", field=models.CharField(blank=True, max_length=150)),
    ]
