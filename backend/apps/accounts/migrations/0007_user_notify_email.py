from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0006_user_avatar")]

    operations = [
        migrations.AddField(model_name="user", name="notify_email", field=models.BooleanField(default=False)),
    ]
