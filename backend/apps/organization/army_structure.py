"""Army organizational structure as supplied by army personnel (meeting requirements, section 3). ARMY ONLY.

Everything is DATA in the existing tables (units, unit types), created through the existing placement rules, so it stays
configurable and can be restructured later with the normal tools. Navy units are never read or written here.

Shape created:
    System HQ
      Army Headquarters "Taliska Guud"         (Army branch command directly under the system HQ)
        Hogganka Ciidanka / Maaliyadda / Taakulada / Howlgelinta / Isgaarsiinta / Caafimaadka / Gaadiidka   (directorates)
      Regional commands "Qaybta ..." (Army branch command of each region, type Qayb)
        Mudug & Cayn, Nugaal & Sool, Bari (Karkaar is within Bari), Sanaag
        Every regional command also gets Guuto (brigade) and Urur (battalion) units: one Guuto per command and one Urur per Guuto by
        default, raised later with `apply_army_structure --apply --guuto-per-command N --urur-per-guuto M` (additive: it only ever
        creates what is missing, never deletes or renames), or by authorized users with the normal unit tools.
      Urur offices (unit types only): Howlgelin, Xafiiska Ururka, Maamulka Lacagta, Saadka, Xubinta Caafimaadka.
      Finance: a Finance Department "Waaxda Maaliyadda" under every regional command ({REGION}-ARMY-FIN).
      Health (medics): a Health Department "Waaxda Caafimaadka" under every regional command ({REGION}-ARMY-HEALTH), a Medical Unit
        in every Urur (Xubinta Caafimaadka, above) and a Medical team "Koox Caafimaad" ({KOOX}-MED) in every existing Koox.

Assumptions to confirm with the army (also listed in the implementation report): the English labels are working
translations; Taliye Qaybeed / Taliye Urur / Abaanduule are command appointments (see personnel appointments), not units;
the template's Gaas level is left in place although the supplied structure does not mention it.
"""
from django.db.models import F, Q
from django.utils import timezone

ARMY_HQ_CODE = "ARMY-HQ"
# unit-code suffix, Somali name (as supplied), working English label
DIRECTORATES = [
    ("CIIDANKA", "Hogganka Ciidanka", "Forces Directorate"),
    ("MAALIYADDA", "Hogganka Maaliyadda", "Finance Directorate"),
    ("TAAKULADA", "Hogganka Taakulada", "Support Directorate"),
    ("HOWLGELINTA", "Hogganka Howlgelinta", "Operations Directorate"),
    ("ISGAARSIINTA", "Hogganka Isgaarsiinta", "Communications Directorate"),
    ("CAAFIMAADKA", "Hogganka Caafimaadka", "Medical Directorate"),
    ("GAADIIDKA", "Hogganka Gaadiidka", "Transport Directorate"),
]
# region code, Somali name (as supplied), working English label. New region: SANAAG.
COMMANDS = [
    ("MUDUG", "Qaybta Mudug & Cayn", "Mudug & Cayn Regional Command"),
    ("NUGAAL", "Qaybta Nugaal & Sool", "Nugaal & Sool Regional Command"),
    ("BARI", "Qaybta Bari", "Bari Regional Command"),
    ("SANAAG", "Qaybta Sanaag", "Sanaag Regional Command"),
]
# Regions that get Guuto (brigade) and Urur (battalion) units from this tool. Everything here stays editable data.
FIELD_FORCE_REGIONS = tuple(c for c, _, _ in COMMANDS)  # all four Army regional commands
DEFAULT_GUUTO_PER_COMMAND = 1
DEFAULT_URUR_PER_GUUTO = 1
MAX_PER_PARENT = 20  # a sanity ceiling for the command-line options, not a rule of the army
# Battalion-level sections created as real units under every Urur this tool manages: code suffix, unit type, Somali, English.
URUR_OFFICES = [
    ("OPS", "URUR_HOWLGELIN", "Howlgelin", "Operations Section (Howlgelin)"),
    ("ADMIN", "URUR_XAFIIS", "Xafiiska Ururka", "Battalion Administrative Office (Xafiiska Ururka)"),
    ("FIN", "URUR_LACAG", "Maamulka Lacagta", "Finance Section (Maamulka Lacagta)"),
    ("SUPPLY", "URUR_SAAD", "Saadka", "Logistics and Supply Section (Saadka)"),
    ("MED", "URUR_CAAFIMAAD", "Xubinta Caafimaadka", "Medical Unit (Xubinta Caafimaadka)"),
]
REGION_NAMES = {c: (so, en) for c, so, en in COMMANDS}

# code, Somali, English working label, tier, parent type
NEW_TYPES = [
    ("HQ_DIRECTORATE", "Hogganka", "Directorate (Hogganka)", 2, "TALISKA_GUUD"),
    ("URUR_HOWLGELIN", "Howlgelin", "Operations office (Howlgelin)", 6, "URUR"),
    ("URUR_XAFIIS", "Xafiiska Ururka", "Urur office (Xafiiska Ururka)", 6, "URUR"),
    ("URUR_LACAG", "Maamulka Lacagta", "Finance administration (Maamulka Lacagta)", 6, "URUR"),
    ("URUR_SAAD", "Saadka", "Supplies (Saadka)", 6, "URUR"),
    ("URUR_CAAFIMAAD", "Xubinta Caafimaadka", "Medical member (Xubinta Caafimaadka)", 6, "URUR"),
    ("HEALTH_DEPT", "Waaxda Caafimaadka", "Health Department (Waaxda Caafimaadka)", 3, "QAYB"),
    ("FINANCE_DEPT", "Waaxda Maaliyadda", "Finance Department (Waaxda Maaliyadda)", 3, "QAYB"),
    ("KOOX_MED", "Koox Caafimaad", "Medical team (Koox Caafimaad)", 8, "KOOX"),
]


def _bump(OU, pk, **fields):
    OU.objects.filter(pk=pk).update(version=F("version") + 1, updated_at=timezone.now(), **fields)


def apply(OU, UnitType, ServiceBranch, Personnel, dry_run=True, guuto_per_command=DEFAULT_GUUTO_PER_COMMAND,
          urur_per_guuto=DEFAULT_URUR_PER_GUUTO):
    """Return a list of (action, detail) lines. Writes only when dry_run is False. Idempotent: running it again is a no-op."""
    out = []
    army = ServiceBranch.objects.filter(code="ARMY").first()
    sys_hq = OU.objects.filter(level="headquarters").first()
    if army is None or sys_hq is None:
        return [("blocked", "Army branch or system headquarters is missing; run seed_reference_data first.")]
    types = {t.code: t for t in UnitType.objects.all()}
    if any(t not in types for t in ("TALISKA_GUUD", "QAYB", "GUUTO", "URUR")):
        return [("blocked", "The organizational template is missing; run seed_reference_data first.")]

    for code, so, en, tier, parent in NEW_TYPES:
        if code not in types:
            out.append(("create_type", code))
            if not dry_run:
                types[code] = UnitType.objects.create(code=code, name_so=so, name_en=en, tier=tier, parent_type=types[parent])

    def ensure(code, **kw):
        unit = OU.objects.filter(code=code).first()
        if unit is None:
            out.append(("create_unit", code))
            if not dry_run:
                unit = OU.objects.create(code=code, **kw)
        return unit

    hq = ensure(ARMY_HQ_CODE, name_so="Taliska Guud", name_en="Army Headquarters (Taliska Guud)", level="branch_command",
                parent=sys_hq, branch=army, unit_type=types["TALISKA_GUUD"])
    for suffix, so, en in DIRECTORATES:
        dcode = f"{ARMY_HQ_CODE}-{suffix}"
        if hq is None:  # dry run, headquarters not created yet
            out.append(("create_unit", dcode))
        else:
            ensure(dcode, name_so=so, name_en=f"{so} ({en})", level="unit", parent=hq, unit_type=types.get("HQ_DIRECTORATE"))

    for region_code, so, en in COMMANDS:
        region = OU.objects.filter(code=region_code, level="region").first()
        if region is None:
            out.append(("create_unit", region_code))
            if not dry_run:
                region = OU.objects.create(code=region_code, name_en=region_code.title(), name_so=region_code.title(),
                                           level="region", parent=sys_hq)
        cmd = OU.objects.filter(code=f"{region_code}-ARMY", branch=army).first()
        label = f"{region_code}-ARMY"
        if cmd is None:
            out.append(("create_unit", label))
            if not dry_run and region is not None:
                OU.objects.create(code=label, name_so=so, name_en=f"{so} ({en})", level="branch_command", parent=region,
                                  branch=army, unit_type=types["QAYB"])
            continue
        changes = {}
        if cmd.name_so != so:
            changes.update(name_so=so, name_en=f"{so} ({en})")
        if cmd.unit_type_id in (None, types["TALISKA_GUUD"].pk):  # older tagging: the regional command was typed Taliska Guud
            changes["unit_type"] = types["QAYB"]
        if changes:
            out.append(("update_unit", f"{label}: {', '.join(sorted(changes))}"))
            if not dry_run:
                _bump(OU, cmd.pk, **changes)

    # Guuto (brigade) and Urur (battalion) for every Army regional command. Created only when missing, so a larger number later just adds more.
    for region_code in FIELD_FORCE_REGIONS:
        cmd = OU.objects.filter(code=f"{region_code}-ARMY", branch=army).first()
        place = region_code.title()
        for g in range(1, guuto_per_command + 1):
            gcode = f"{region_code}-ARMY-G{g}"
            guuto = OU.objects.filter(code=gcode).first()
            if guuto is None:
                out.append(("create_unit", gcode))
                if not dry_run and cmd is not None:
                    guuto = OU.objects.create(code=gcode, name_so=f"Guuto {g} ({place})", name_en=f"Guuto {g} (Brigade {g}, {place})",
                                              level="unit", parent=cmd, unit_type=types["GUUTO"])
            for u in range(1, urur_per_guuto + 1):
                ucode = f"{gcode}-U{u}"
                urur = OU.objects.filter(code=ucode).first()
                if urur is None:
                    out.append(("create_unit", ucode))
                    if not dry_run and guuto is not None:
                        urur = OU.objects.create(code=ucode, name_so=f"Urur {u} (Guuto {g}, {place})",
                                                 name_en=f"Urur {u} (Battalion {u}, Guuto {g}, {place})", level="unit", parent=guuto,
                                                 unit_type=types["URUR"])
                for suffix, tcode, so, en in URUR_OFFICES:  # the battalion's sections exist as real units, not just types
                    ocode = f"{ucode}-{suffix}"
                    if OU.objects.filter(code=ocode).exists():
                        continue
                    out.append(("create_unit", ocode))
                    if not dry_run and urur is not None:
                        OU.objects.create(code=ocode, name_so=f"{so} (Urur {u}, Guuto {g}, {place})",
                                          name_en=f"{en}, Urur {u}, Guuto {g}, {place}", level="unit", parent=urur, unit_type=types[tcode])

    # Health (medics). One Health Department under every regional command, and a Medical team in every Koox that exists. Kooxes are
    # raised by authorized users, so the teams are added the next time this runs (every deploy), never deleted or renamed here.
    for region_code in FIELD_FORCE_REGIONS:
        cmd = OU.objects.filter(code=f"{region_code}-ARMY", branch=army).first()
        so_region, _ = REGION_NAMES[region_code]
        hcode = f"{region_code}-ARMY-HEALTH"
        if not OU.objects.filter(code=hcode).exists():
            out.append(("create_unit", hcode))
            if not dry_run and cmd is not None:
                OU.objects.create(code=hcode, name_so=f"Waaxda Caafimaadka ({so_region})",
                                  name_en=f"Health Department (Waaxda Caafimaadka), {region_code.title()}", level="unit", parent=cmd,
                                  unit_type=types.get("HEALTH_DEPT"))
        fcode = f"{region_code}-ARMY-FIN"  # regional finance staff belong here; their payment roles are assigned at the command
        if not OU.objects.filter(code=fcode).exists():
            out.append(("create_unit", fcode))
            if not dry_run and cmd is not None:
                OU.objects.create(code=fcode, name_so=f"Waaxda Maaliyadda ({so_region})",
                                  name_en=f"Finance Department (Waaxda Maaliyadda), {region_code.title()}", level="unit", parent=cmd,
                                  unit_type=types.get("FINANCE_DEPT"))
        if cmd is None:
            continue
        for koox in OU.objects.filter(unit_type__code="KOOX", active=True, path__startswith=cmd.path).order_by("code"):
            mcode = f"{koox.code}-MED"
            if OU.objects.filter(code=mcode).exists():
                continue
            out.append(("create_unit", mcode))
            if not dry_run:
                OU.objects.create(code=mcode, name_so=f"Koox Caafimaad ({koox.name_so})", name_en=f"Medical team (Koox Caafimaad), {koox.name_en}",
                                  level="unit", parent=koox, unit_type=types.get("KOOX_MED"))

    # Karkaar is within Bari: the Army has no separate Karkaar command. Retired only when nothing is left in it.
    karkaar = OU.objects.filter(code="KARKAAR-ARMY", branch=army, active=True).first()
    if karkaar is not None:
        people = Personnel.objects.filter(org_unit__path__startswith=karkaar.path).exclude(
            status__in=["retired", "discharged", "died"]).count()
        kids = OU.objects.filter(parent=karkaar, active=True).count()
        if people or kids:
            out.append(("blocked", f"KARKAAR-ARMY still holds {people} serving personnel and {kids} active units; "
                                   "transfer them into Qaybta Bari with the normal transfer tools, then run this again."))
        else:
            out.append(("deactivate_unit", "KARKAAR-ARMY"))
            if not dry_run:
                _bump(OU, karkaar.pk, active=False)
    return out
