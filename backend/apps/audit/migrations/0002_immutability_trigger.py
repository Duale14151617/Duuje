from django.db import migrations

FORWARD = [
    """CREATE OR REPLACE FUNCTION audit_events_immutable() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION 'audit_events is append-only'; END;
    $$ LANGUAGE plpgsql""",
    """CREATE TRIGGER audit_events_no_change BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_immutable()""",
    """CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION audit_events_immutable()""",
]
REVERSE = [
    "DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events",
    "DROP TRIGGER IF EXISTS audit_events_no_change ON audit_events",
    "DROP FUNCTION IF EXISTS audit_events_immutable()",
]


def _run(statements):
    def op(apps, schema_editor):
        if schema_editor.connection.vendor != "postgresql":
            return  # SQLite (dev/tests): the model layer still blocks changes.
        for sql in statements:
            schema_editor.execute(sql)
    return op


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunPython(_run(FORWARD), _run(REVERSE))]
