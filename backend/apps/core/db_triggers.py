"""PostgreSQL triggers that make a table append-only even for a compromised application account."""
from django.db import migrations


def _runner(statements):
    def run(apps, schema_editor):
        if schema_editor.connection.vendor != "postgresql":
            return  # SQLite (dev/tests): the application-level guard still applies
        for sql in statements:
            schema_editor.execute(sql)
    return run


def append_only_trigger(table):
    fn = f"{table}_append_only"
    forward = [
        f"""CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION '{table} is append-only'; END; $$ LANGUAGE plpgsql""",
        f"""CREATE TRIGGER {table}_no_change BEFORE UPDATE OR DELETE ON {table}
        FOR EACH ROW EXECUTE FUNCTION {fn}()""",
    ]
    reverse = [f"DROP TRIGGER IF EXISTS {table}_no_change ON {table}", f"DROP FUNCTION IF EXISTS {fn}()"]
    return migrations.RunPython(_runner(forward), _runner(reverse))
