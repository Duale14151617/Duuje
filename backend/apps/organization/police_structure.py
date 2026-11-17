"""Police organizational structure (the separate Police deployment, ARMYHQ_PROFILE=police).

Everything is DATA in the existing tables (unit types, appointment types, units), so it stays configurable with the normal
tools. Shape created:

    System HQ
      Police Headquarters                      (Police command directly under the system HQ)
        Directorates: CID, Traffic, Tax collection
      Regional commands, one for EACH region (a commander and a deputy each)
        Bari, Karkaar, Mudug, Nugaal, Gardafuu, Highland, Sool, Sanaag, Cayn
        Sections in every regional command: CID, Traffic, Tax collection
      Two generic stations under every regional command: "Station one / Jeelka kowaad" (CODE-POL-S1) and "Station two / Jeelka labaad"
      (CODE-POL-S2), each with Koox 1 and Koox 2. Rename them, or add real ones, with the normal unit tools.
      Districts (a chief and a deputy each), police stations (a commander and a deputy each) and Kooxo are added by authorized
      users with the normal unit tools: the real district and station names are theirs to enter. Every new station is created
      with two Kooxo (Koox 1 and Koox 2) automatically; add more by hand.

The Police uses the same 18-rank ladder as the Army. The service branch keeps its internal code ARMY (the ranks hang on it and
the headquarters placement rule names it) and is labelled "Police" here.

Assumptions to confirm with the Police (the Somali and English labels are working labels): the three named services also exist as
sections inside every regional command; the headquarters has no commissioner appointment yet (add the title as data when decided).
"""
from django.db.models import F
from django.utils import timezone

POLICE_HQ_CODE = "POLICE-HQ"
BRANCH_CODE = "ARMY"  # internal branch code, labelled "Police"
REGIONS = [  # code, name (the Somali and English names are the same proper nouns)
    ("BARI", "Bari"), ("KARKAAR", "Karkaar"), ("MUDUG", "Mudug"), ("NUGAAL", "Nugaal"), ("GARDAFUU", "Gardafuu"),
    ("HIGHLAND", "Highland"), ("SOOL", "Sool"), ("SANAAG", "Sanaag"), ("CAYN", "Cayn"),
]
SERVICES = [  # code suffix, Somali, English
    ("CID", "Waaxda Baarista Dambiyada (CID)", "Criminal Investigation Department (CID)"),
    ("TRAFFIC", "Waaxda Taraafikada", "Traffic Department"),
    ("TAX", "Waaxda Ururinta Canshuuraha", "Tax Collection Department"),
]
# code, Somali, English, tier, parent type code, formation role
TYPES = [
    ("POLICE_HQ", "Taliska Booliska", "Police Headquarters", 1, None, "ghq"),
    ("POLICE_DIRECTORATE", "Hogganka", "Directorate", 2, "POLICE_HQ", ""),
    ("POLICE_REGION", "Taliska Gobolka", "Regional command", 3, "POLICE_HQ", "regional"),
    ("POLICE_SECTION", "Waax", "Section", 4, "POLICE_REGION", ""),
    ("POLICE_DISTRICT", "Degmo", "District", 4, "POLICE_REGION", "district"),
    ("POLICE_STATION", "Saldhig", "Police station", 5, "POLICE_DISTRICT", "station"),
    ("POLICE_KOOX", "Koox", "Koox (team)", 6, "POLICE_STATION", ""),
]
# code, Somali, English, unit type, role
APPOINTMENTS = [
    ("POLICE_REGION_COMMANDER", "Taliyaha Gobolka", "Regional commander", "POLICE_REGION", "commander"),
    ("POLICE_REGION_DEPUTY", "Ku-xigeenka Taliyaha Gobolka", "Deputy regional commander", "POLICE_REGION", "deputy"),
    ("POLICE_DISTRICT_CHIEF", "Taliyaha Degmada", "District chief", "POLICE_DISTRICT", "commander"),
    ("POLICE_DISTRICT_DEPUTY", "Ku-xigeenka Taliyaha Degmada", "Deputy district chief", "POLICE_DISTRICT", "deputy"),
    ("POLICE_STATION_COMMANDER", "Taliyaha Saldhigga", "Station commander", "POLICE_STATION", "commander"),
    ("POLICE_STATION_DEPUTY", "Ku-xigeenka Taliyaha Saldhigga", "Deputy station commander", "POLICE_STATION", "deputy"),
]
KOOXO_PER_STATION = 2
# Departments a district or station runs, beside Command and Administration, HR and Logistics (already in the catalogue).
# code, English, Somali (working labels to confirm with the Police), restricted roster, sort order
STATION_DEPARTMENT_DEFS = [
    ("OPERATIONS", "Operations and Duty Office", "Hawlgalka iyo Xafiiska Shaqada", False, 80),
    ("INVESTIGATION", "Investigation (CID)", "Baarista Dambiyada (CID)", False, 85),
    ("CUSTODY", "Custody and Jail", "Xarunta Jeelka iyo Haynta", False, 90),
    ("COMMUNITY", "Community Policing", "Booliska Bulshada", False, 95),
]
# Two generic police stations (Jeelka) under EVERY regional command, so each region starts with somewhere to book detainees and post
# officers. code suffix, English, Somali. Real stations are added with the normal unit tools; these are placeholders to rename.
STATIONS = [
    ("S1", "Station one", "Jeelka kowaad"),
    ("S2", "Station two", "Jeelka labaad"),
]

# The Police uses only the Police unit types above, and Koox is its team level. These Army-template types, the Sanco designation
# and the Guuto/Urur appointment titles are switched off (active=False, never deleted) while nothing uses them. An administrator
# can switch any of them back on.
RETIRE_TYPES = ("GUUTO", "URUR", "HORIN", "KOOX")
RETIRE_DESIGNATIONS = ("SANCO",)
RETIRE_APPOINTMENTS = ("TALIYE_GUUTO", "TALIYE_URUR")


def create_kooxo_for_station(OU, UnitType, station, count=KOOXO_PER_STATION):
    """Give a station its first Kooxo, only the ones that are missing (re-running never duplicates)."""
    koox_type = UnitType.objects.filter(code="POLICE_KOOX").first()
    made = 0
    for n in range(1, count + 1):
        code = f"{station.code}-K{n}"
        if OU.objects.filter(code=code).exists():
            continue
        OU.objects.create(code=code, name_so=f"Koox {n}", name_en=f"Koox {n}", level=OU.Level.UNIT, parent=station,
                          unit_type=koox_type)
        made += 1
    return made


def _bump(OU, pk, **fields):
    OU.objects.filter(pk=pk).update(version=F("version") + 1, updated_at=timezone.now(), **fields)


def apply(OU, UnitType, ServiceBranch, AppointmentType, dry_run=True):
    """Return a list of (action, detail) lines. Writes only when dry_run is False. Idempotent: running it again changes nothing."""
    out = []
    branch = ServiceBranch.objects.filter(code=BRANCH_CODE).first()
    sys_hq = OU.objects.filter(level=OU.Level.HQ).first()
    if branch is None or sys_hq is None:
        return [("blocked", "The service branch or the system headquarters is missing; run seed_reference_data first.")]

    if branch.name_en != "Police":
        out.append(("label_branch", "Service branch labelled Police"))
        if not dry_run:
            ServiceBranch.objects.filter(pk=branch.pk).update(name_en="Police", name_so="Booliska")

    types = {t.code: t for t in UnitType.objects.all()}
    from apps.organization.models import Department
    for code, en, so, restricted, order in STATION_DEPARTMENT_DEFS:
        if not Department.objects.filter(code=code).exists():
            out.append(("create_department", code))
            if not dry_run:
                Department.objects.create(code=code, name_en=en, name_so=so, restricted_roster=restricted, sort_order=order)
    for code, so, en, tier, parent, role in TYPES:
        if code in types:
            t = types[code]
            if role and not t.formation_role:  # only fills a blank: an administrator's own choice is never overwritten
                out.append(("set_formation_role", f"{code} -> {role}"))
                if not dry_run:
                    UnitType.objects.filter(pk=t.pk).update(formation_role=role, version=F("version") + 1, updated_at=timezone.now())
            continue
        out.append(("create_type", code))
        if not dry_run:
            types[code] = UnitType.objects.create(code=code, name_so=so, name_en=en, tier=tier, formation_role=role,
                                                  parent_type=types.get(parent) if parent else None)

    for code, so, en, utype, role in APPOINTMENTS:
        if AppointmentType.objects.filter(code=code).exists():
            continue
        out.append(("create_appointment_type", code))
        if not dry_run:
            AppointmentType.objects.create(code=code, name_so=so, name_en=en, unit_type=types.get(utype), exclusive=True, role=role)

    def ensure(code, **kw):
        unit = OU.objects.filter(code=code).first()
        if unit is None:
            out.append(("create_unit", code))
            if not dry_run:
                unit = OU.objects.create(code=code, **kw)
        return unit

    hq = ensure(POLICE_HQ_CODE, name_so="Taliska Booliska", name_en="Police Headquarters (Taliska Booliska)",
                level=OU.Level.BRANCH, parent=sys_hq, branch=branch, unit_type=types.get("POLICE_HQ"))
    for suffix, so, en in SERVICES:
        code = f"{POLICE_HQ_CODE}-{suffix}"
        if hq is None:
            out.append(("create_unit", code))
        else:
            ensure(code, name_so=so, name_en=en, level=OU.Level.UNIT, parent=hq, unit_type=types.get("POLICE_DIRECTORATE"))

    for rcode, name in REGIONS:
        region = OU.objects.filter(code=rcode, level=OU.Level.REGION).first()
        if region is None:
            out.append(("create_unit", rcode))
            if not dry_run:
                region = OU.objects.create(code=rcode, name_en=name, name_so=name, level=OU.Level.REGION, parent=sys_hq)
        cmd_code = f"{rcode}-POL"
        cmd = OU.objects.filter(code=cmd_code).first()
        if cmd is None:
            out.append(("create_unit", cmd_code))
            if not dry_run and region is not None:
                cmd = OU.objects.create(code=cmd_code, name_so=f"Taliska Booliska Gobolka {name}",
                                        name_en=f"{name} Regional Police Command", level=OU.Level.BRANCH, parent=region,
                                        branch=branch, unit_type=types.get("POLICE_REGION"))
        for suffix, so, en in SERVICES:
            scode = f"{cmd_code}-{suffix}"
            if cmd is None:
                out.append(("create_unit", scode))
            else:
                ensure(scode, name_so=so, name_en=en, level=OU.Level.UNIT, parent=cmd, unit_type=types.get("POLICE_SECTION"))
        for suffix, en, so in STATIONS:  # the two generic stations; creating one also gives it Koox 1 and Koox 2 (signal)
            scode = f"{cmd_code}-{suffix}"
            if cmd is None:
                out.append(("create_unit", scode))
            else:
                ensure(scode, name_so=so, name_en=en, level=OU.Level.UNIT, parent=cmd, unit_type=types.get("POLICE_STATION"))

    if not dry_run:  # a generic station that existed before its Kooxo were added still gets them (never duplicates)
        for rcode, _ in REGIONS:
            for suffix, _en, _so in STATIONS:
                st = OU.objects.filter(code=f"{rcode}-POL-{suffix}", unit_type__code="POLICE_STATION").first()
                if st is not None and create_kooxo_for_station(OU, UnitType, st):
                    out.append(("create_koox", f"{st.code}: missing Kooxo added"))

    # Retire the Army-only types so the Police sees Koox as its only team level.
    from apps.organization.models import SpecialistDesignation
    from apps.personnel.models import CommandAppointment
    for code in RETIRE_TYPES:
        t = UnitType.objects.filter(code=code, active=True).first()
        if t is not None and not OU.objects.filter(unit_type=t).exists():
            out.append(("retire_type", code))
            if not dry_run:
                UnitType.objects.filter(pk=t.pk).update(active=False, version=F("version") + 1, updated_at=timezone.now())
    for code in RETIRE_DESIGNATIONS:
        d = SpecialistDesignation.objects.filter(code=code, active=True).first()
        if d is not None and not OU.objects.filter(designations=d).exists():
            out.append(("retire_designation", code))
            if not dry_run:
                SpecialistDesignation.objects.filter(pk=d.pk).update(active=False, version=F("version") + 1, updated_at=timezone.now())
    for code in RETIRE_APPOINTMENTS:
        a = AppointmentType.objects.filter(code=code, active=True).first()
        if a is not None and not CommandAppointment.objects.filter(appointment_type=a).exists():
            out.append(("retire_appointment_type", code))
            if not dry_run:
                AppointmentType.objects.filter(pk=a.pk).update(active=False, version=F("version") + 1, updated_at=timezone.now())
    return out
