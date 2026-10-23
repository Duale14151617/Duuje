"""Puntland Police structure as working units (not just types or a list). POLICE BRANCH ONLY: Army and Navy units are never read or written.

Shape created, for every region that has a Police command (Bari, Karkaar, Nugaal, Mudug and the new Sanaag):
    <REGION>-POLICE                    regional Police command (created for Sanaag; the others come from seed_reference_data)
      <REGION>-POLICE-PERS/OPS/TRN/FINLOG/CID/PR/TRAFFIC    departments (CID is restricted: needs `cid.access`)
      <REGION>-POLICE-ST1 ...          Police stations (level `station`, directly under the regional Police command)

Department and station names are NOT confirmed by the Puntland Police authorities (see docs/POLICE_MODULE.md), so everything here is
ordinary editable data in the Organization screens. The tool only ever creates what is missing: it never renames, deletes, or loosens a
restriction. Stations default to one per command; raise it later with `--stations-per-command N`.

It does nothing while the Police pilot switch (POLICE_MODULE_ENABLED) is off, exactly like the rest of the Police module.
Police ranks are the Army ranking, approved when seeded (apps/ranks/police_catalogue.py), so people can be assigned at once.
"""
from .police import DEPARTMENTS

POLICE_REGIONS = ("BARI", "KARKAAR", "NUGAAL", "MUDUG", "SANAAG")
DEFAULT_STATIONS_PER_COMMAND = 1
MAX_STATIONS = 20  # sanity ceiling for the command-line option, not a rule of the police


def apply(OU, ServiceBranch, dry_run=True, stations_per_command=DEFAULT_STATIONS_PER_COMMAND):
    """Return [(action, detail)]. Writes only when dry_run is False. Idempotent and additive."""
    out = []
    police = ServiceBranch.objects.filter(code="POLICE").first()
    sys_hq = OU.objects.filter(level="headquarters").first()
    if police is None or sys_hq is None:
        return [("blocked", "Police branch or system headquarters is missing; run seed_reference_data first.")]
    for region_code in POLICE_REGIONS:
        place = region_code.title()
        region = OU.objects.filter(code=region_code, level="region").first()
        if region is None:
            out.append(("create_unit", region_code))
            if not dry_run:
                region = OU.objects.create(code=region_code, name_en=place, name_so=place, level="region", parent=sys_hq)
        cmd = OU.objects.filter(code=f"{region_code}-POLICE", branch=police).first()
        if cmd is None:
            out.append(("create_unit", f"{region_code}-POLICE"))
            if not dry_run and region is not None:
                cmd = OU.objects.create(code=f"{region_code}-POLICE", name_en=f"{place} Police", name_so=f"{place} Booliska",
                                        level="branch_command", parent=region, branch=police)
        for code, name, restricted in DEPARTMENTS:
            ucode = f"{region_code}-POLICE-{code}"
            unit = OU.objects.filter(code=ucode).first()
            if unit is None:
                out.append(("create_unit", ucode))
                if not dry_run and cmd is not None:
                    label = f"{place} Police {name}"
                    OU.objects.create(code=ucode, name_en=label, name_so=label, level="unit", parent=cmd, restricted=restricted)
            elif restricted and not unit.restricted:
                out.append(("restrict_unit", ucode))  # never loosened, only tightened
                if not dry_run:
                    OU.objects.filter(pk=unit.pk).update(restricted=True)
        for n in range(1, stations_per_command + 1):
            scode = f"{region_code}-POLICE-ST{n}"
            if OU.objects.filter(code=scode).exists():
                continue
            out.append(("create_unit", scode))
            if not dry_run and cmd is not None:
                OU.objects.create(code=scode, name_en=f"Station {n} ({place} Police)", name_so=f"Saldhigga {n} ({place} Booliska)",
                                  level="station", parent=cmd)
    return out
