from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("detention", "0006_court_case_incidents_cell_rules")]

    operations = [
        migrations.AddField(model_name="detentionrecord", name="client_ref", field=models.CharField(blank=True, max_length=36)),
        migrations.AddField(model_name="detentionevent", name="client_ref", field=models.CharField(blank=True, max_length=36)),
        migrations.AddConstraint(model_name="detentionrecord", constraint=models.UniqueConstraint(condition=models.Q(("client_ref", ""), _negated=True), fields=("client_ref",), name="det_unique_client_ref")),
        migrations.AddConstraint(model_name="detentionevent", constraint=models.UniqueConstraint(condition=models.Q(("client_ref", ""), _negated=True), fields=("client_ref",), name="detevt_unique_client_ref")),
    ]
