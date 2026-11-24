"""Police Fleet Management: the Police vehicle types, all under the main category "Police Vehicles".

The fleet module itself (registration, Vehicle ID, plate, unit, driver, responsible officer = custodian, status, maintenance,
documents, history, role-based access and audit log) is the vehicle register in this app. This file only supplies the Police
vehicle types for it. Somali names are working labels to be confirmed by the Police. Seeding states what a type IS and never that
the Police owns any vehicle of it. Idempotent; never overwrites an administrator's edit.
"""
MAIN_CATEGORY = "police_vehicles"

# code, name_en, name_so (working label), sort, purpose
POLICE_VEHICLE_CATEGORIES = [
    ("police_transport", "Police Transport Vehicles", "Gawaarida Qaadista Booliska", 210,
     "Transporting officers and personnel."),
    ("police_pickup", "Police Pickup Trucks", "Bikaab-gaadiidka Booliska (Pickup)", 220,
     "Patrols, operational duties and carrying equipment."),
    ("police_tactical", "Police Tactical Vehicles", "Gawaarida Tacticalka Booliska", 230,
     "Specialized units conducting high-risk operations."),
    ("police_armored", "Police Armored Vehicles", "Gawaarida Hubaysan ee Booliska", 240,
     "Operations requiring enhanced vehicle protection."),
    ("police_motorcycle", "Police Motorcycles", "Mootooyinka Booliska", 250,
     "Traffic enforcement and patrols."),
    ("police_prisoner_transport", "Police Prisoner Transport Vehicles", "Gawaarida Qaadista Maxaabiista Booliska", 260,
     "Transporting arrested or detained persons to police stations, detention facilities or other authorized locations."),
]

# Military-only or duplicate categories from the shared reference data. Retired (hidden from the register form) only while no vehicle
# uses them; HQ can switch any of them back on under the vehicle categories.
RETIRE_IF_UNUSED = ("main_battle_tank", "armoured_personnel_carrier", "military_transport_truck", "military_cargo_truck",
                    "armored_truck", "hilux_4x4", "motorcycle")


def apply(VehicleCategory, Vehicle, dry_run=True):
    """Returns [(action, detail)]. Writes only when dry_run is False."""
    lines = []
    for code, en, so, order, purpose in POLICE_VEHICLE_CATEGORIES:
        if VehicleCategory.objects.filter(code=code).exists():
            continue
        lines.append(("create_category", f"{en} ({code}): {purpose}"))
        if not dry_run:
            VehicleCategory.objects.create(code=code, name_en=en, name_so=so, sort_order=order, group=MAIN_CATEGORY)
    for code in RETIRE_IF_UNUSED:
        cat = VehicleCategory.objects.filter(code=code, active=True).first()
        if cat is None or Vehicle.objects.filter(category=cat).exists():
            continue
        lines.append(("retire_category", f"{cat.name_en} ({code}): not a Police vehicle type and no vehicle uses it"))
        if not dry_run:
            cat.active = False
            cat.save(update_fields=["active"])
    return lines
