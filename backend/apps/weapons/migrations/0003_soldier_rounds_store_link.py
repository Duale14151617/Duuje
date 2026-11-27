import django.db.models.deletion
from django.db import migrations, models


def link_existing(apps, schema_editor):
    """Link rows written before this migration to their unit-ledger movement by line, kind and voucher. The append-only trigger
    is lifted for this one data fix and restored straight after."""
    SR, ST = apps.get_model("weapons", "SoldierRounds"), apps.get_model("logistics", "StockTransaction")
    pg = schema_editor.connection.vendor == "postgresql"
    if pg:
        schema_editor.execute("ALTER TABLE soldier_rounds DISABLE TRIGGER soldier_rounds_no_change")
    try:
        for r in SR.objects.filter(kind__in=["issue", "return"], store_transaction__isnull=True):
            t = ST.objects.filter(stock_line_id=r.stock_line_id, kind=r.kind, external_ref=r.reference).first()
            if t is not None and not SR.objects.filter(store_transaction=t).exists():
                SR.objects.filter(pk=r.pk).update(store_transaction=t)
    finally:
        if pg:
            schema_editor.execute("ALTER TABLE soldier_rounds ENABLE TRIGGER soldier_rounds_no_change")


class Migration(migrations.Migration):
    dependencies = [
        ("weapons", "0002_soldier_rounds"),
        ("logistics", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="soldierrounds",
            name="store_transaction",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="soldier_rounds", to="logistics.stocktransaction"),
        ),
        migrations.RunPython(link_existing, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="soldierrounds",
            constraint=models.UniqueConstraint(fields=["store_transaction"], condition=models.Q(store_transaction__isnull=False),
                                               name="soldier_rounds_one_per_store_txn"),
        ),
        migrations.AddConstraint(
            model_name="soldierrounds",
            constraint=models.CheckConstraint(condition=models.Q(kind__in=["issue", "return"]) | models.Q(store_transaction__isnull=True),
                                              name="soldier_rounds_writeoff_not_in_store"),
        ),
    ]
