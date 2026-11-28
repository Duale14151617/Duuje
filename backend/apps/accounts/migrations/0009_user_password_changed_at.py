from django.db import migrations, models
from django.utils import timezone


def start_clock(apps, schema_editor):
    """Existing accounts start their password age from the day this migration runs, so nobody is locked out the moment a limit is switched on."""
    User = apps.get_model("accounts", "User")
    User.objects.filter(password_changed_at__isnull=True).update(password_changed_at=timezone.now())


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0008_backup_codes_and_passkeys"),
    ]

    operations = [
        migrations.AddField(model_name="user", name="password_changed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.RunPython(start_clock, migrations.RunPython.noop),
    ]
