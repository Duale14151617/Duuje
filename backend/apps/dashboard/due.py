"""Due soon: things with a date that is close or already past, limited to what the person may see.

Three kinds: ID cards about to expire, vehicles due for service, and court dates or remand orders for people in custody. Nothing
here invents a deadline: each date comes from a record somebody entered. A list never shows more than CAP rows per kind (the true
count is always given). The same figures feed the daily digest notification, which says only HOW MANY items are waiting.
"""
from django.conf import settings
from datetime import timedelta

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.accounts import scope
from apps.detention.models import CourtHearing, DetentionRecord
from apps.issuance.models import IssuedDocument
from apps.vehicles.models import MaintenanceRecord, Vehicle

CAP = 50
ID_CARD_DAYS = 30
SERVICE_DAYS = 14
COURT_DAYS = 2


def _limit(q, unit, prefix):
    """Narrow a scope filter to one unit and everything under it (for a station's own summary)."""
    return q if unit is None else q & Q(**{f"{prefix}path__startswith": unit.path})


def _group(kind, rows, perm_link):
    rows = list(rows)
    return {"kind": kind, "count": len(rows), "items": rows[:CAP], "link": perm_link}


def _id_cards(user, today, unit=None):
    q = scope.unit_scope_q(user, "credentials.view", "org_unit__")
    if q is None:
        return None
    q = _limit(q, unit, "org_unit__")
    qs = IssuedDocument.objects.filter(q, kind="id_card", status="valid", expires_on__isnull=False,
                                       expires_on__lte=today + timedelta(days=ID_CARD_DAYS)).select_related("personnel", "org_unit").order_by("expires_on")
    return _group("id_cards", ({"id": str(d.pk), "label": d.personnel.full_name if d.personnel else d.reference, "due_on": d.expires_on.isoformat(),
                                "overdue": d.expires_on < today, "unit_en": d.org_unit.name_en, "unit_so": d.org_unit.name_so} for d in qs),
                  "/credentials")


def _vehicle_service(user, today, unit=None):
    q = scope.unit_scope_q(user, "vehicles.view", "vehicle__org_unit__")
    if q is None:
        return None
    q = _limit(q, unit, "vehicle__org_unit__")
    newer = MaintenanceRecord.objects.filter(vehicle=OuterRef("vehicle"), performed_on__gt=OuterRef("performed_on"))
    qs = (MaintenanceRecord.objects.filter(q, state="completed", next_due_date__isnull=False,
                                           next_due_date__lte=today + timedelta(days=SERVICE_DAYS))
          .exclude(vehicle__status=Vehicle.Status.DECOMMISSIONED).exclude(Exists(newer))
          .select_related("vehicle", "vehicle__org_unit").order_by("next_due_date"))
    return _group("vehicle_service", ({"id": str(m.vehicle_id), "label": f"{m.vehicle.vehicle_id} {m.vehicle.plate}".strip(),
                                       "due_on": m.next_due_date.isoformat(), "overdue": m.next_due_date < today,
                                       "unit_en": m.vehicle.org_unit.name_en, "unit_so": m.vehicle.org_unit.name_so} for m in qs), "/vehicles")


def _court(user, now, unit=None):
    if not settings.CUSTODY_ENABLED:  # custody is switched off
        return None
    q = scope.unit_scope_q(user, "detention.view", "org_unit__")
    if q is None:
        return None
    q = _limit(q, unit, "org_unit__")
    today = timezone.localdate(now)
    held = DetentionRecord.objects.filter(q, status=DetentionRecord.Status.IN_CUSTODY).select_related("org_unit").prefetch_related("hearings")
    rows = []
    for r in held:
        hearings = [h for h in r.hearings.all() if h.status != "cancelled"]
        soon = [h.hearing_at for h in hearings if h.status == "scheduled" and h.hearing_at and now <= h.hearing_at <= now + timedelta(days=COURT_DAYS)]
        remands = [h.remand_until for h in hearings if h.remand_until]
        expired = bool(remands and max(remands) < today)
        if soon or expired:
            due = min(soon) if soon else None
            rows.append({"id": str(r.pk), "label": r.register_no, "due_on": (due.date() if due else max(remands)).isoformat(),
                         "overdue": expired, "note": "remand" if expired else "hearing", "unit_en": r.org_unit.name_en, "unit_so": r.org_unit.name_so})
    rows.sort(key=lambda x: x["due_on"])
    return _group("court", rows, "/detention")


def due_soon(user, now=None, unit=None):
    now = now or timezone.now()
    today = timezone.localdate(now)
    groups = [g for g in (_id_cards(user, today, unit), _vehicle_service(user, today, unit), _court(user, now, unit)) if g is not None]
    return {"groups": groups, "total": sum(g["count"] for g in groups), "as_of": now.isoformat()}
