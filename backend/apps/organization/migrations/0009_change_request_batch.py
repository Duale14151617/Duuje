from django.db import migrations, models


class Migration(migrations.Migration):
    """Groups requests entered together (bulk transfer) so they are decided together. One nullable column."""

    dependencies = [("organization", "0008_change_request_kinds")]

    operations = [
        migrations.AddField(model_name="changerequest", name="batch_id", field=models.UUIDField(blank=True, db_index=True, null=True)),
    ]
