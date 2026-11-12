from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_email_verification")]

    operations = [
        migrations.AddField(model_name="user", name="temp_password_expires_at",
                            field=models.DateTimeField(blank=True, null=True)),
    ]
