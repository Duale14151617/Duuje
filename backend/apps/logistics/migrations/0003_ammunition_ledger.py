from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("logistics", "0002_append_only_triggers")]

    operations = [
        migrations.AddField(model_name="stocktransaction", name="external_ref", field=models.CharField(blank=True, max_length=60)),
        migrations.AddField(model_name="stocktransaction", name="authority_ref", field=models.CharField(blank=True, max_length=150)),
        migrations.AlterField(
            model_name="stocktransaction",
            name="kind",
            field=models.CharField(
                choices=[("receive", "Receive"), ("issue", "Issue"), ("adjust", "Adjust"), ("transfer_out", "Transfer Out"),
                         ("transfer_in", "Transfer In"), ("opening", "Opening"), ("return", "Return"),
                         ("expenditure", "Expenditure"), ("loss", "Loss"), ("damage", "Damage")],
                max_length=12),
        ),
        migrations.AddConstraint(
            model_name="stocktransaction",
            constraint=models.CheckConstraint(
                condition=(models.Q(kind__in=["opening", "receive", "return", "transfer_in"], delta__gt=0)
                           | models.Q(kind__in=["issue", "expenditure", "loss", "damage", "transfer_out"], delta__lt=0)
                           | models.Q(kind="adjust")),
                name="stocktxn_delta_sign_by_kind"),
        ),
        migrations.AddConstraint(
            model_name="stocktransaction",
            constraint=models.UniqueConstraint(fields=["stock_line", "kind", "external_ref"], condition=~models.Q(external_ref=""),
                                               name="stocktxn_unique_voucher"),
        ),
        migrations.AddConstraint(
            model_name="stocktransaction",
            constraint=models.UniqueConstraint(fields=["stock_line"], condition=models.Q(kind="opening"), name="stocktxn_one_opening"),
        ),
    ]
