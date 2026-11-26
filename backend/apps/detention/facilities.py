"""Default custody facilities: one jail center (army lock-up) for every army station, and one generic prison per region.

Jail center = the station's own cells, short-term, run by the Army. Prison = long-term, run by the prison authority, outside the
Army; here it is only a place a person is handed over to. The generic names are placeholders to rename in the Custody facilities page.
Idempotent: it only creates what is missing and never touches a name an administrator has edited.
"""
from apps.organization import army_structure as ps
from .hierarchy import CUSTODY_UNIT_TYPE
from apps.organization.models import OrganizationalUnit

from .models import CustodyCell, CustodyFacility, DetentionEvent, DetentionRecord

PRISON_AUTHORITY = "Prison authority (not the Army)"


def ensure_jail_center(station):
    """The jail center record of one army station. Returns (facility, created).

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
        code=code, kind="jail_center", org_unit=station, operated_by="Army", status="unverified",
        status_note="Created automatically. Not yet checked: confirm the station really has a lock-up before use.",
        name_en=f"Jail center: {station.name_en}", name_so=f"Xarunta Jeelka: {station.name_so or station.name_en}"), True


def ensure_defaults():
    """Returns (jail centers made, prisons made)."""
    jails = prisons = 0
    for st in OrganizationalUnit.objects.filter(unit_type__code=CUSTODY_UNIT_TYPE, active=True):
        jails += ensure_jail_center(st)[1]
    for rcode, name in [(c, c.title()) for c, _so, _en in ps.COMMANDS]:
        code = f"PRISON-{rcode}"
        if not CustodyFacility.objects.filter(code=code).exists():
            CustodyFacility.objects.create(code=code, kind="prison", name_en=f"{name} Prison", name_so=f"Xabsiga {name}", operated_by=PRISON_AUTHORITY,
                                           status="unverified", status_note="Generic placeholder. The real prison, its name and location are to be confirmed by the administration.")
            prisons += 1
    return jails, prisons


# ---- demonstration set-up -------------------------------------------------------------------------------------------------
PREAPPROVED_NOTE = "Pre-approved by the administrator for a demonstration deployment. NOT verified on site."
DEMO_CELLS = [("C1", "Cell 1 (adult men)", 4, "men"), ("C2", "Cell 2 (women)", 2, "women"), ("C3", "Cell 3 (general)", 4, "any")]  # sample sizes only


def preapprove_demo(stations=None, actor="system"):
    """For SAMPLE / demonstration deployments only: mark the stations' not-yet-verified jail centers operational, give each three sample
    cells, and place everyone in custody who has no cell into one (women in C2, men in C1, overflow in C3). Idempotent. It never touches a
    facility an administrator has suspended or closed, never edits a verified one, and never changes a person who already has a cell.
    The note on each record says plainly that it was pre-approved and not verified on site. Returns (verified, cells, placed)."""
    from django.db.models import F
    from django.utils import timezone

    from apps.audit.services import record

    verified = cells_made = placed = 0
    stations = stations if stations is not None else OrganizationalUnit.objects.filter(unit_type__code=CUSTODY_UNIT_TYPE, active=True)
    for st in stations:
        fac, _ = ensure_jail_center(st)
        if fac.status == CustodyFacility.Status.UNVERIFIED and fac.active:
            fac.status, fac.status_note, fac.status_at, fac.status_by_username = "operational", PREAPPROVED_NOTE, timezone.now(), actor
            fac.version += 1
            fac.save()
            record("detention.facility_status", actor=None, entity_type="custody_facility", entity_id=fac.pk, metadata={"code": fac.code, "from": "unverified", "to": "operational", "preapproved": True})
            verified += 1
        if not fac.usable:
            continue
        by_code = {}
        for code, name, cap, reserved in DEMO_CELLS:
            c, made = CustodyCell.objects.get_or_create(facility=fac, code=code, defaults={"name": name, "capacity": cap, "reserved_for": reserved, "note": "Sample cell"})
            cells_made += made
            by_code[code] = c

        def room(c):
            return c.active and DetentionRecord.objects.filter(cell_ref=c, status="in_custody").count() < c.capacity

        for rec in DetentionRecord.objects.filter(org_unit=st, status="in_custody", cell_ref__isnull=True).order_by("booked_at"):
            order = ("C2", "C3") if rec.sex == "female" else ("C1", "C3")
            cell = next((by_code[k] for k in order if room(by_code[k])), None)
            if cell is None:
                continue
            DetentionRecord.objects.filter(pk=rec.pk).update(facility=rec.facility or fac, cell_ref=cell, cell=cell.code, version=F("version") + 1)
            DetentionEvent.objects.create(record=rec, kind="cell_move", occurred_at=timezone.now(), text=f"Placed in {cell.code} (sample set-up)", by_username=actor)
            placed += 1
    return verified, cells_made, placed
