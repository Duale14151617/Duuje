"""Default custody facilities: one jail center (police lock-up) for every police station, and one generic prison per region.

Jail center = the station's own cells, short-term, run by the Police. Prison = long-term, run by the prison authority, outside the
Police; here it is only a place a person is handed over to. The generic names are placeholders to rename in the Custody facilities page.
Idempotent: it only creates what is missing and never touches a name an administrator has edited.
"""
from apps.organization import police_structure as ps
from apps.organization.models import OrganizationalUnit

from .models import CustodyFacility

PRISON_AUTHORITY = "Prison authority (not the Police)"


def ensure_jail_center(station):
    """The jail center record of one police station. Returns (facility, created).

    Safe to run again: nothing is created if the station already has any jail center (whatever its code or name), and an existing
    record is never edited. A new record starts as NOT VERIFIED: it is a placeholder for administrators to confirm, not proof that the
    station has a working lock-up, and nobody can be placed in it until it has been verified as operational."""
    existing = CustodyFacility.objects.filter(org_unit=station, kind="jail_center").order_by("created_at").first()
    if existing is not None:
        return existing, False
    code = f"{station.code}-JAIL"
    fac = CustodyFacility.objects.filter(code=code).first()
    if fac is not None:  # the code is taken by a facility of another unit: do not touch it, and do not invent a second code
        return fac, False
    return CustodyFacility.objects.create(
        code=code, kind="jail_center", org_unit=station, operated_by="Police", status="unverified",
        status_note="Created automatically. Not yet checked: confirm the station really has a lock-up before use.",
        name_en=f"Jail center: {station.name_en}", name_so=f"Xarunta Jeelka: {station.name_so or station.name_en}"), True


def ensure_defaults():
    """Returns (jail centers made, prisons made)."""
    jails = prisons = 0
    for st in OrganizationalUnit.objects.filter(unit_type__code="POLICE_STATION", active=True):
        jails += ensure_jail_center(st)[1]
    for rcode, name in ps.REGIONS:
        code = f"PRISON-{rcode}"
        if not CustodyFacility.objects.filter(code=code).exists():
            CustodyFacility.objects.create(code=code, kind="prison", name_en=f"{name} Prison", name_so=f"Xabsiga {name}", operated_by=PRISON_AUTHORITY,
                                           status="unverified", status_note="Generic placeholder. The real prison, its name and location are to be confirmed by the administration.")
            prisons += 1
    return jails, prisons
