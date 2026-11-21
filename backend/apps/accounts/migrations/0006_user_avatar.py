import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0005_temp_password_expiry")]

    operations = [
        migrations.CreateModel(
            name="UserAvatar",
            fields=[
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, related_name="avatar",
                                              serialize=False, to=settings.AUTH_USER_MODEL)),
                ("image_enc", models.BinaryField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by_username", models.CharField(blank=True, max_length=150)),
            ],
            options={"db_table": "user_avatars"},
        ),
    ]
