from django.db import migrations

STATION_DEPARTMENTS = [
    ("OPERATIONS", "Operations and Duty Office", "Hawlgalka iyo Xafiiska Shaqada", 80),
    ("INVESTIGATION", "Investigation (CID)", "Baarista Dambiyada (CID)", 85),
    ("CUSTODY", "Custody and Jail", "Xarunta Jeelka iyo Haynta", 90),
    ("COMMUNITY", "Community Policing", "Booliska Bulshada", 95),
]
STATION_SET = ["COMMAND_ADMIN", "HR", "LOGISTICS", "OPERATIONS", "INVESTIGATION", "CUSTODY", "COMMUNITY"]
DISTRICT_SET = ["COMMAND_ADMIN", "HR", "LOGISTICS", "OPERATIONS", "INVESTIGATION"]


def forwards(apps, schema_editor):
    """Give the policing departments to the catalogue, tag the district/station types, and establish the departments in every
    existing district and station. Additive and idempotent; creates no people and no appointments."""
    Department = apps.get_model("organization", "Department")
    UnitType = apps.get_model("organization", "UnitType")
    Unit = apps.get_model("organization", "OrganizationalUnit")
    UnitDepartment = apps.get_model("organization", "UnitDepartment")
    for code, en, so, order in STATION_DEPARTMENTS:
        Department.objects.get_or_create(code=code, defaults={"name_en": en, "name_so": so, "sort_order": order})
    for code, role in (("POLICE_DISTRICT", "district"), ("POLICE_STATION", "station")):
        UnitType.objects.filter(code=code, formation_role="").update(formation_role=role)
    depts = {d.code: d for d in Department.objects.filter(active=True)}
    for role, codes in (("district", DISTRICT_SET), ("station", STATION_SET)):
        for unit in Unit.objects.filter(active=True, unit_type__formation_role=role):
            for c in codes:
                if c in depts:
                    UnitDepartment.objects.get_or_create(unit=unit, department=depts[c])


class Migration(migrations.Migration):
    dependencies = [("organization", "0013_district_station_formation_roles")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
