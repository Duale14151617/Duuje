"""PostgreSQL protection for the vehicle register: history is append-only, and a vehicle, its maintenance records and its documents
can never be deleted (decommissioning keeps the record). SQLite (dev/tests) relies on the application-level guards."""
from django.db import migrations

from apps.core.db_triggers import append_only_trigger


def no_delete_trigger(table):
    fn = f"{table}_no_delete"

    def run(statements):
        def inner(apps, schema_editor):
            if schema_editor.connection.vendor != "postgresql":
                return
            for sql in statements:
                schema_editor.execute(sql)
        return inner

    forward = [
        f"""CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION '{table} rows cannot be deleted'; END; $$ LANGUAGE plpgsql""",
        f"""CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {fn}()""",
    ]
    reverse = [f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table}", f"DROP FUNCTION IF EXISTS {fn}()"]
    return migrations.RunPython(run(forward), run(reverse))


class Migration(migrations.Migration):
    dependencies = [("vehicles", "0001_initial")]
    operations = [append_only_trigger("vehicle_events"), no_delete_trigger("vehicles"),
                  no_delete_trigger("vehicle_maintenance"), no_delete_trigger("vehicle_documents")]
