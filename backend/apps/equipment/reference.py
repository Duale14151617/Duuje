"""Reference data the catalogue starts with. It states what the equipment IS, never that the Army owns any.

Everything seeded is 'unverified' until a second person holding equipment.verify has checked it; no specifications and no photographs
are invented (HQ adds them with their source). Somali names are left blank until supplied: the screens fall back to English.
Seeding only creates what is missing and never overwrites an edit.
"""

# code, name_en, group for a NEW vehicle category (an existing category is reused as it is)
VEHICLE_CLASSES = [
    ("main_battle_tank", "Main Battle Tank", "combat_vehicle", 110),
    ("armoured_personnel_carrier", "Armoured Personnel Carrier", "protected_transport", 120),
    ("military_transport_truck", "Military Transport Truck", "general_transport", 130),
    ("military_cargo_truck", "Military Cargo Truck", "general_transport", 140),
    ("utility_pickup", "Utility Pickup", "utility", 150),
]
# code, name, class code (VehicleCategory.code), manufacturer, description
VEHICLE_MODELS = [
    ("t-54-t-55", "T-54/T-55", "main_battle_tank", "Soviet state tank factories", "Soviet-designed main battle tank family (T-54 and its T-55 development)."),
    ("btr-60", "BTR-60", "armoured_personnel_carrier", "Gorky Automobile Plant (GAZ)", "Soviet 8x8 wheeled armoured personnel carrier."),
    ("fiat-6614", "Fiat 6614", "armoured_personnel_carrier", "Fiat", "Italian 4x4 wheeled armoured personnel carrier."),
    ("renault-gbc-180", "Renault GBC 180", "military_transport_truck", "Renault", "French military transport truck."),
    ("m939", "M939", "military_cargo_truck", "AM General", "Military cargo truck (5-ton 6x6 family)."),
    ("toyota-land-cruiser-j79", "Toyota Land Cruiser J79", "utility_pickup", "Toyota", "Utility pickup (Land Cruiser 70 series, J79 double cab)."),
    ("toyota-hilux", "Toyota Hilux", "utility_pickup", "Toyota", "Utility pickup."),
    ("nissan-frontier", "Nissan Frontier", "utility_pickup", "Nissan", "Utility pickup."),
    ("ford-f-350", "Ford F-350", "utility", "Ford", "Utility vehicle (heavy-duty pickup chassis)."),  # existing "Utility vehicle" category is reused
]
MOUNTED_WEAPON_CATEGORIES = [
    ("heavy_machine_gun", "Heavy machine guns", 10), ("automatic_cannon", "Automatic cannons", 20),
    ("anti_aircraft_gun", "Anti-aircraft guns", 30), ("recoilless_rifle", "Recoilless rifles", 40),
    ("integrated_armament", "Integrated vehicle armament", 50),
]


def seed_catalogue(VehicleCategory, MountedWeaponCategory, EquipmentItem):
    """Works with real or migration-state models. Idempotent."""
    for code, en, group, order in VEHICLE_CLASSES:
        VehicleCategory.objects.get_or_create(code=code, defaults={"name_en": en, "sort_order": order, "group": group})
    for code, en, order in MOUNTED_WEAPON_CATEGORIES:
        MountedWeaponCategory.objects.get_or_create(code=code, defaults={"name_en": en, "sort_order": order})
    for code, name, cls, maker, desc in VEHICLE_MODELS:
        cat = VehicleCategory.objects.filter(code=cls).first()
        if cat is not None:
            EquipmentItem.objects.get_or_create(code=code, defaults={
                "name": name, "kind": "vehicle_model", "vehicle_category": cat, "manufacturer": maker, "description": desc,
                "source_ref": "Supplied by Army headquarters as a reference model; facts not yet checked", "created_by_username": "system"})
