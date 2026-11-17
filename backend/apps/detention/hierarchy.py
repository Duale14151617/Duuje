"""Hierarchy and custody-setup verification (read-only). Answers: does every active police station sit in the right place of the
chart (under a district or a regional command, inside a region), have its departments, and have a consistent custody setup?

Nothing is created or changed here and nothing is invented: a station with no district is reported as "no district assigned" for the
administration to decide, not given one. Used by `manage.py verify_station_hierarchy`, the oversight dashboard and the tests."""
from django.db.models import F

from apps.organization import profiles
from apps.organization.models import OrganizationalUnit as OU, UnitDepartment

from .models import CustodyCell, CustodyFacility, DetentionRecord

ERROR, WARNING, INFO = "error", "warning", "info"
VALID_PARENTS = ("POLICE_DISTRICT", "POLICE_REGION")  # a station sits under a district, or directly under its regional command


def index():
    """{unit pk: unit} for the whole chart (it is small), with unit types loaded."""
    return {u.pk: u for u in OU.objects.select_related("unit_type")}


def lineage(unit, by_id):
    """(regional command, district, chain) of a unit. Either may be None. The chain is parent, grandparent ... up to the root."""
    chain, seen, cur = [], {unit.pk}, unit
    while cur.parent_id and cur.parent_id in by_id and cur.parent_id not in seen:
        cur = by_id[cur.parent_id]
        seen.add(cur.pk)
        chain.append(cur)
    code = lambda u: u.unit_type.code if u.unit_type_id else ""
    region = next((u for u in chain if code(u) == "POLICE_REGION"), None) or next((u for u in chain if u.level == OU.Level.REGION), None)
    district = next((u for u in chain if code(u) == "POLICE_DISTRICT"), None)
    return region, district, chain


def stations():
    """Active units that are police stations."""
    return list(OU.objects.filter(unit_type__code="POLICE_STATION", active=True).select_related("unit_type", "parent", "parent__unit_type").order_by("path"))


def check():
    by_id = index()
    out = []

    def add(sev, code, unit, msg):
        out.append({"severity": sev, "code": code, "unit": unit.code if unit else "", "unit_name": unit.name_en if unit else "", "message": msg})

    sts = stations()
    facs = list(CustodyFacility.objects.filter(kind="jail_center").select_related("org_unit", "org_unit__unit_type"))
    by_station = {}
    for f in facs:
        by_station.setdefault(f.org_unit_id, []).append(f)
    wanted = set(profiles.STATION_DEPARTMENTS)
    have = {}
    for unit_id, code in UnitDepartment.objects.filter(active=True, unit__unit_type__code="POLICE_STATION").values_list("unit_id", "department__code"):
        have.setdefault(unit_id, set()).add(code)
    names = {}
    for st in sts:
        region, district, chain = lineage(st, by_id)
        parent = by_id.get(st.parent_id)
        if parent is None:
            add(ERROR, "no_parent", st, "The station has no parent unit.")
        else:
            ptype = parent.unit_type.code if parent.unit_type_id else ""
            if ptype not in VALID_PARENTS:
                add(ERROR, "wrong_parent_type", st, f"The parent is {parent.code}, which is not a district or a regional command.")
            if not st.path.startswith(parent.path):
                add(ERROR, "path_mismatch", st, "The stored hierarchy path does not follow the parent: the unit tree needs repair.")
        if region is None:
            add(ERROR, "no_region", st, "The station is not inside any regional command.")
        if any(not u.active for u in chain):
            add(ERROR, "inactive_ancestor", st, "An office above this active station is switched off.")
        if district is None:
            add(INFO, "no_district", st, "No district is assigned. The station sits directly under its regional command; assign one only when the real district is known.")
        elif region is not None and district.pk not in {u.pk for u in chain}:
            add(ERROR, "district_outside_region", st, "The district is not part of the station's region.")
        names.setdefault((st.parent_id, st.name_en.strip().lower()), []).append(st)
        missing = wanted - have.get(st.pk, set())
        if missing:
            add(WARNING, "missing_departments", st, "Station departments not yet set up: " + ", ".join(sorted(missing)) + ".")
        mine = by_station.get(st.pk, [])
        if not mine:
            add(ERROR, "no_jail_center", st, "No jail center record exists for this station. Run apply_custody_facilities.")
        else:
            if len(mine) > 1:
                add(INFO, "several_jail_centers", st, f"{len(mine)} jail centers are recorded for this station.")
            if not any(f.usable for f in mine):
                states = ", ".join(sorted({("switched off" if not f.active else f.get_status_display().lower()) for f in mine}))
                add(WARNING, "no_operational_jail", st, f"No jail center is verified as operational ({states}). It needs administrative verification before use.")
    for group in names.values():
        if len(group) > 1:
            add(WARNING, "duplicate_station_name", group[0], f"{len(group)} active stations share this name under the same parent.")
    for f in facs:
        u = f.org_unit
        if not (u.unit_type_id and u.unit_type.code == "POLICE_STATION"):
            add(WARNING, "facility_unit_not_station", u, f"Jail center {f.code} belongs to a unit that is not a police station.")
        elif not u.active and f.active:
            add(WARNING, "facility_of_inactive_station", u, f"Jail center {f.code} is switched on but its station is not active.")
    # in-custody consistency
    for r in DetentionRecord.objects.filter(status="in_custody", facility__isnull=False).exclude(facility__org_unit=F("org_unit")).select_related("org_unit", "facility")[:200]:
        add(ERROR, "record_in_foreign_facility", r.org_unit, f"{r.register_no} is held in a jail center of another station.")
    from .capacity import stats_for, summarise
    st_map = stats_for([f.pk for f in facs])
    for f in facs:
        s = summarise(f, st_map[f.pk])
        if s["over_capacity"]:
            add(WARNING, "over_capacity", f.org_unit, f"{f.code} holds {s['occupied']} people against a capacity of {s['capacity']}.")
        if not f.usable and st_map[f.pk]["held"]:
            add(WARNING, "held_in_unusable_facility", f.org_unit, f"{st_map[f.pk]['held']} people are recorded in {f.code}, which is not verified as operational.")
    for c in CustodyCell.objects.filter(active=True).select_related("facility__org_unit"):
        n = c.records.filter(status="in_custody").count()
        if n > c.capacity:
            add(ERROR, "cell_over_capacity", c.facility.org_unit, f"Cell {c.code} of {c.facility.code} holds {n} against a capacity of {c.capacity}.")
    summary = {"stations": len(sts), "errors": sum(1 for x in out if x["severity"] == ERROR),
               "warnings": sum(1 for x in out if x["severity"] == WARNING), "info": sum(1 for x in out if x["severity"] == INFO)}
    return {**summary, "findings": out}

