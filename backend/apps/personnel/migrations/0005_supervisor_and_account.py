import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("personnel", "0004_disciplinary_and_documents"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="personnel",
            name="supervisor",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="subordinates", to="personnel.personnel"),
        ),
        migrations.AddField(
            model_name="personnel",
            name="account",
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                       related_name="personnel_record", to=settings.AUTH_USER_MODEL),
        ),
    ]
