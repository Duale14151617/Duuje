"""Published reference facts for catalogue entries, each with where it was read.

Everything here comes from open, public sources read on 2026-11-03 (listed per entry). It describes what a KIND of equipment is.
It never says the Army owns one. Entries stay 'unverified' until a second person holding equipment.verify checks them against
the cited source (that is what the verify step is for). Facts that sources disagree on are left out rather than guessed.

Photographs are NOT included: public pictures carry their own licences. HQ uploads a photograph through the catalogue screen after
checking the licence on the source page (for example the file page on Wikimedia Commons), and notes the licence in the caption.

Add more entries by appending to SPECS / WEAPONS; `manage.py load_reference_specs` only fills entries that have no specifications yet.
"""

WIKI = "https://en.wikipedia.org/wiki/"

# code (existing EquipmentItem.code) -> (source_ref up to 300 chars, [(name, value, unit)])
SPECS = {
    "t-54-t-55": (
        f"{WIKI}T-54/T-55 (dimensions, crew, guns); science.howstuffworks.com/t-54-t-55-main-battle-tank.htm (engine). Read 2026-11-03.",
        [("Place of origin", "Soviet Union", ""), ("Type", "Main battle tank (medium tank)", ""), ("Crew", "4", ""),
         ("Mass (T-55)", "36", "t"), ("Length, gun forward", "9.00", "m"), ("Width", "3.37", "m"), ("Height", "2.40", "m"),
         ("Main gun", "D-10T 100 mm rifled gun", ""), ("Secondary armament", "7.62 mm SGMT coaxial machine gun; 12.7 mm DShK on some variants", ""),
         ("Engine (T-55)", "V-12 water-cooled diesel, 580 hp", "")]),
    "btr-60": (
        f"{WIKI}BTR-60 (BTR-60PB figures). Read 2026-11-03.",
        [("Place of origin", "Soviet Union", ""), ("Type", "Amphibious 8x8 wheeled armoured personnel carrier", ""),
         ("Crew and passengers", "3 crew + 14 passengers (varies by variant)", ""), ("Mass (BTR-60PB)", "10.3", "t"), ("Length", "7.56", "m"),
         ("Width", "2.83", "m"), ("Height", "2.31", "m"), ("Armament (BTR-60PB)", "14.5 mm KPVT heavy machine gun; 7.62 mm PKT coaxial machine gun", ""),
         ("Maximum speed, road", "80", "km/h"), ("Maximum speed, water", "10", "km/h")]),
    "fiat-6614": (
        f"{WIKI}Fiat_CM6614 (also called Type 6614). Read 2026-11-03.",
        [("Place of origin", "Italy", ""), ("Type", "Amphibious 4x4 wheeled armoured personnel carrier", ""), ("Mass", "8,500", "kg"),
         ("Length", "5.86", "m"), ("Width", "2.5", "m"), ("Height", "1.78", "m"), ("Crew and passengers", "1-2 crew + 8-10 passengers", ""),
         ("Armament options", "One 7.62 mm or one .50 cal machine gun", ""), ("Maximum speed", "100", "km/h"), ("Operational range", "700", "km")]),
    "renault-gbc-180": (
        f"{WIKI}Renault_GBC_180; French Ministry of Defence leaflet archives.defense.gouv.fr (gbc 180.pdf, length, width, crew). Read 2026-11-03.",
        [("Place of origin", "France", ""), ("Type", "6x6 all-terrain heavy cargo truck (rebuild of the Berliet GBC 8 KT)", ""), ("Payload", "5,000", "kg"),
         ("Engine", "MIDR 06.02.26 six-cylinder diesel, 6.2 L, 175 PS", ""), ("Length", "7.33", "m"), ("Width", "2.40", "m"),
         ("Seating", "3 in cab + 20 in the rear", ""), ("Ground clearance", "0.60", "m"), ("Maximum speed", "88", "km/h"), ("Operational range", "800", "km")]),
    "m939": (
        f"{WIKI}M939_series_5-ton_6%C3%976_truck (M925A2 figures); encyclopedia.pub/entry/28531 (cargo load). Read 2026-11-03.",
        [("Place of origin", "United States", ""), ("Type", "5-ton 6x6 heavy tactical truck", ""), ("Cargo load", "4,500", "kg"),
         ("Mass (M925A2)", "9,990", "kg"), ("Length", "8.43", "m"), ("Width", "2.46", "m"), ("Height", "3.07", "m"),
         ("Engine (M925A2)", "Cummins 6CTA8.3 diesel, 240 hp", ""), ("Production", "44,590 built by AM General, 1982-1987", "")]),
}

SPECS.update({
    "toyota-land-cruiser-j79": (
        f"{WIKI}Toyota_Land_Cruiser_(J70) (79 series, double cab from 2012); supply.unicef.org/s0008703.html (HZJ79 double-cab figures). Read 2026-11-03.",
        [("Manufacturer country", "Japan", ""), ("Type", "Off-road utility pickup: the 79 series of the Land Cruiser 70 Series", ""),
         ("70 Series in production since", "1984", ""), ("Double-cab pickup body", "from 2012", ""), ("Layout", "Front engine, four-wheel drive", ""),
         ("Example: HZJ79 double cab, engine", "4,200 cc six-cylinder diesel", ""), ("Example: HZJ79 double cab, gearbox", "5-speed manual", ""),
         ("Example: HZJ79 double cab, seats", "6", ""), ("Example: HZJ79 double cab, fuel tank", "130", "L"),
         ("Note", "Engines and body options differ by market and year; check the vehicle's own papers", "")]),
    "toyota-hilux": (
        f"{WIKI}Toyota_Hilux. Read 2026-11-03.",
        [("Manufacturer country", "Japan", ""), ("In production since", "March 1968", ""), ("Class", "Compact pickup (1968-2004); mid-size pickup (2004 onward)", ""),
         ("Body styles", "2-door pickup (from 1968); 4-door pickup (from 1981)", ""), ("Chassis", "Body-on-frame", ""),
         ("Cumulative global sales", "17.7 million by 2017", ""), ("Note", "Specifications differ by generation, market and engine", "")]),
    "nissan-frontier": (
        f"{WIKI}Nissan_Frontier_(North_America); en.wikipedia.org/wiki/Nissan_Navara (alternative names). Read 2026-11-03.",
        [("Manufacturer country", "Japan", ""), ("In production since", "1997", ""), ("Also sold as", "Nissan Navara / NP300 in many other markets", ""),
         ("Class", "Compact pickup (1997-2005); mid-size pickup (2005 onward)", ""), ("Body styles", "2-door and 4-door pickup", ""),
         ("Layout", "Front engine, rear-wheel or four-wheel drive", ""), ("Predecessor", "Nissan Hardbody (D21)", ""),
         ("Note", "Specifications differ by generation, market and engine", "")]),
    "ford-f-350": (
        f"{WIKI}Ford_Super_Duty (the F-350 is part of the Super Duty range). Read 2026-11-03.",
        [("Manufacturer country", "United States", ""), ("Range", "Ford Super Duty (F-250 to F-550)", ""), ("In production since", "January 1998 (model year 1999)", ""),
         ("Class", "Heavy-duty pickup truck / chassis cab", ""), ("F-350 body options", "Pickup truck and chassis cab", ""),
         ("Layout", "Front engine, rear-wheel or four-wheel drive", ""), ("Note", "Specifications differ by model year, cab, axle and engine", "")]),
})

# New mounted-weapon reference entries: (code, name, category code, manufacturer, description, source_ref, specs).
# Identification-level facts only (type, calibre, origin, size); nothing about building, modifying or using a weapon.
WEAPONS = [
    ("dshk-12-7", "DShK 12.7 mm heavy machine gun", "heavy_machine_gun", "Tula Arms Plant (original Soviet production)",
     "Soviet 12.7 mm heavy machine gun introduced in 1938; used vehicle-mounted, on a tripod or on a wheeled carriage.",
     f"{WIKI}DShK; globalmilitary.net/firearms/dshk/ (manufacturer). Read 2026-11-03.",
     [("Place of origin", "Soviet Union", ""), ("Introduced", "1938", ""), ("Cartridge", "12.7 x 108 mm", ""),
      ("Mass, gun only", "34", "kg"), ("Mass on wheeled mounting", "157", "kg"), ("Length", "1,625", "mm"), ("Barrel length", "1,070", "mm")]),
]

EXTRA_WEAPON_CATEGORIES = [("general_purpose_machine_gun", "General-purpose machine guns", 5)]  # code, name_en, sort_order

WEAPONS += [
    ("zu-23-2", "ZU-23-2 23 mm anti-aircraft twin autocannon", "anti_aircraft_gun", "Designed by KBP Instrument Design Bureau (Soviet Union)",
     "Soviet twin 23 mm anti-aircraft autocannon on a two-wheel carriage; also seen fitted to trucks and other vehicles.",
     f"{WIKI}ZU-23-2; {WIKI}ZSU-23-4_Shilka (truck-mounted use). Read 2026-11-03.",
     [("Place of origin", "Soviet Union", ""), ("Type", "Towed 23 mm anti-aircraft twin autocannon", ""), ("Cartridge", "23 x 152 mmB", ""), ("GRAU index", "2A13", ""),
      ("Designed", "Late 1950s", ""), ("In service", "1960 to present", ""), ("Mass", "0.95", "t"), ("Length", "4.57", "m")]),
    ("m2-browning", "M2 Browning .50 heavy machine gun", "heavy_machine_gun", "Several makers (including Colt, Fabrique Nationale, General Dynamics)",
     "American .50 calibre heavy machine gun designed by John Browning; widely used on vehicles, boats and fixed mounts.",
     f"{WIKI}M2_Browning (M2HB figures). Read 2026-11-03.",
     [("Place of origin", "United States", ""), ("Designer", "John Browning (designed 1918)", ""), ("M2HB in service", "1933 to present", ""),
      ("Cartridge", ".50 BMG (12.7 x 99 mm NATO)", ""), ("Mass, gun only", "38", "kg"), ("Mass with tripod and T&E mechanism", "58", "kg"),
      ("Length", "1,654", "mm"), ("Barrel length", "1,143", "mm"), ("Operation", "Air-cooled, belt-fed, short recoil", "")]),
    ("pkm", "PK / PKM 7.62 mm general-purpose machine gun", "general_purpose_machine_gun", "Degtyaryov Plant",
     "Soviet belt-fed general-purpose machine gun designed by Mikhail Kalashnikov; the PKT version is used as a vehicle coaxial gun.",
     f"{WIKI}PK_machine_gun (PK figures). Read 2026-11-03.",
     [("Place of origin", "Soviet Union", ""), ("Designer", "Mikhail Kalashnikov", ""), ("Introduced", "1961", ""), ("Cartridge", "7.62 x 54 mmR", ""),
      ("Mass (PK, with integral bipod)", "9", "kg"), ("Length", "1,203", "mm"), ("Barrel length", "605", "mm"), ("Variants", "PK, PKS, PKT, PKM, PKMS", "")]),
]

PLACEHOLDER_SOURCE = "Supplied by Army headquarters as a reference model"
