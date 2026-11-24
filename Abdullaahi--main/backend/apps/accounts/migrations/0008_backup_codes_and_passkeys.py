import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0007_user_notify_email"),
    ]

    operations = [
        migrations.CreateModel(
            name="MfaBackupCode",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("code_hash", models.CharField(max_length=64, unique=True)),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="backup_codes", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "mfa_backup_codes", "ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="PasskeyCredential",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("credential_id", models.CharField(max_length=512, unique=True)),
                ("public_key", models.TextField()),
                ("sign_count", models.BigIntegerField(default=0)),
                ("name", models.CharField(max_length=60)),
                ("transports", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="passkeys", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "user_passkeys", "ordering": ["created_at"]},
        ),
        migrations.CreateModel(
            name="PasskeyChallenge",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("purpose", models.CharField(max_length=16)),
                ("challenge", models.CharField(max_length=128)),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"db_table": "passkey_challenges"},
        ),
    ]
