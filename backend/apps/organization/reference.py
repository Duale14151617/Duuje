"""Reference content for the Puntland Army organizational template (Addendum to 1.3, version 1.3.1).

Used by the data migration (upgrades) and by `seed_reference_data` (fresh installs). Everything here is created only
when missing, so administrator edits are never overwritten, and the figures are *reference establishment figures*,
not constraints. Functions take the model classes as arguments so a migration can pass its historical models.
"""

# code, name, tier, parent code, standard children per parent, reference min, reference max, description
UNIT_TYPES = [
    ("TALISKA_GUUD", "Taliska Guud", 1, None, None, None, None, "Regional command"),
    ("QAYB", "Qayb", 2, "TALISKA_GUUD", None, 6000, 7000, ""),
    ("GAAS", "Gaas", 3, "QAYB", 2, 3500, 3500, ""),
    ("GUUTO", "Guuto", 4, "GAAS", None, 900, 1001, ""),
    ("URUR", "Urur", 5, "GUUTO", None, 320, 330, ""),
    ("HORIN", "Horin", 6, "URUR", None, 99, 99, ""),
    ("KOOX", "Koox", 7, "HORIN", None, 33, 33, ""),
    ("UNUG", "Unug", 8, "KOOX", None, 9, 9, ""),
]
# code, name, description (English). Somali descriptions are left blank until verified wording is supplied.
DESIGNATIONS = [
    ("SAHAN", "Sahan", "Reconnaissance designation"),
    ("SANCO", "Sanco", "Miino baar / bomb squad designation"),
]
# parent type, child type, designation, note
RULES = [
    ("GUUTO", "HORIN", "SAHAN", "Each Guuto has a designated Horin Sahan."),
    ("GAAS", "URUR", "SAHAN", "Each Gaas has a designated Urur Sahan/Sanco. Assumption: one Urur for each designation "
                              "(a single Urur may carry both); confirm with the institution."),
    ("GAAS", "URUR", "SANCO", "Each Gaas has a designated Urur Sahan/Sanco. Assumption: one Urur for each designation "
                              "(a single Urur may carry both); confirm with the institution."),
]


def ensure_reference(UnitType, SpecialistDesignation, DesignationRule):
    types = {}
    for code, name, tier, parent, per_parent, lo, hi, desc in UNIT_TYPES:
        types[code], _ = UnitType.objects.get_or_create(code=code, defaults={
            "name_en": name, "name_so": name, "tier": tier, "parent_type": types.get(parent),
            "standard_per_parent": per_parent, "reference_min": lo, "reference_max": hi, "description_en": desc})
    desigs = {}
    for code, name, desc in DESIGNATIONS:
        desigs[code], _ = SpecialistDesignation.objects.get_or_create(code=code, defaults={
            "name_en": name, "name_so": name, "description_en": desc})
    for parent, child, desig, note in RULES:
        DesignationRule.objects.get_or_create(parent_type=types[parent], child_type=types[child],
                                              designation=desigs[desig], defaults={"note": note})
    return types


def tag_regional_army_commands(OrganizationalUnit, ServiceBranch, types):
    """Each region's Army branch command *is* that region's Taliska Guud. Only untyped units are touched."""
    army = ServiceBranch.objects.filter(code="ARMY").first()
    if army is None:
        return 0
    return OrganizationalUnit.objects.filter(level="branch_command", branch=army, unit_type__isnull=True).update(
        unit_type=types["TALISKA_GUUD"])
