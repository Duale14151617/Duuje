from django.db import migrations

from apps.organization.reference import ensure_reference, tag_regional_army_commands


def forward(apps, schema_editor):
    UnitType = apps.get_model("organization", "UnitType")
    Designation = apps.get_model("organization", "SpecialistDesignation")
    Rule = apps.get_model("organization", "DesignationRule")
    types = ensure_reference(UnitType, Designation, Rule)
    tag_regional_army_commands(apps.get_model("organization", "OrganizationalUnit"),
                               apps.get_model("organization", "ServiceBranch"), types)


class Migration(migrations.Migration):
    """Data only: adds the template and tags existing regional Army commands as Taliska Guud. Nothing is deleted."""

    dependencies = [("organization", "0002_specialistdesignation_and_more")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
