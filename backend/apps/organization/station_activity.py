"""What a unit (a police station above all) is actually doing: Occurrence Book, custody, attendance, vehicles and its jail.

READ-ONLY and built from the records the other apps already keep; nothing is stored or invented here. Each block is only returned
to a caller who holds the permission of the module it comes from (a block they may not see is `None`, never zero), and every
count covers the unit and everything below it (a station's Kooxo, a district's stations ...), by the unit path.
"""
from collections import Counter
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from apps.accounts import scope

WINDOW_DAYS = 30
RECENT = 8


def _may(user, code, unit):
    return scope.can(user, code, unit=unit)


def facilities_of(unit):
    """Custody facilities that belong to the unit's subtree (a station's jail center), with how many people are held now."""
    from apps.detention.models import CustodyFacility, DetentionRecord

    facs = list(CustodyFacility.objects.filter(org_unit__path__startswith=unit.path, active=True).select_related("org_unit").order_by("kind", "name_en"))
    held = dict(DetentionRecord.objects.filter(facility__in=facs, status=DetentionRecord.Status.IN_CUSTODY)
                .values_list("facility_id").annotate(n=Count("id")))
    return [{"id": str(f.pk), "code": f.code, "kind": f.kind, "name_en": f.name_en, "name_so": f.name_so,
             "unit_id": str(f.org_unit_id), "capacity": f.capacity, "in_custody": held.get(f.pk, 0), "status": f.status, "usable": f.usable,
             "operated_by": f.operated_by} for f in facs]


def _occurrence(unit, since):
    from apps.occurrence.models import OccurrenceEntry

    qs = OccurrenceEntry.objects.filter(org_unit__path__startswith=unit.path, status=OccurrenceEntry.Status.RECORDED)
    recent = qs.filter(occurred_at__gte=since)
    cats = Counter(dict(recent.values_list("category").annotate(n=Count("id"))))
    today = timezone.localdate()
    rows = qs.select_related("org_unit").order_by("-occurred_at")[:RECENT]
    return {
        "today": qs.filter(occurred_at__date=today).count(),
        "last_30_days": recent.count(),
        "by_category": [{"category": k, "count": v} for k, v in cats.most_common()],
        "recent": [{"id": str(e.pk), "ob_number": e.ob_number, "category": e.category, "summary": e.summary,
                    "location": e.location, "occurred_at": e.occurred_at, "unit_code": e.org_unit.code} for e in rows],
    }


def _custody(unit, since):
    from apps.detention.models import DetentionRecord

    S = DetentionRecord.Status
    qs = DetentionRecord.objects.filter(org_unit__path__startswith=unit.path).exclude(status=S.VOID)
    held = qs.filter(status=S.IN_CUSTODY)
    rows = held.select_related("facility").order_by("-booked_at")[:RECENT]
    return {
        "in_custody": held.count(),
        "booked_30_days": qs.filter(booked_at__gte=since).count(),
        "released_30_days": qs.filter(status=S.RELEASED, ended_at__gte=since).count(),
        "transferred_30_days": qs.filter(status=S.TRANSFERRED, ended_at__gte=since).count(),
        "held": [{"id": str(r.pk), "register_no": r.register_no, "detainee_name": r.detainee_name, "reason": r.reason,
                  "booked_at": r.booked_at, "cell": r.cell, "facility": r.facility.name_en if r.facility_id else ""} for r in rows],
    }


def _attendance(unit):
    from apps.attendance.models import AttendanceRecord

    today = timezone.localdate()
    qs = AttendanceRecord.objects.filter(org_unit__path__startswith=unit.path, report_date=today, superseded_at__isnull=True)
    c = dict(qs.values_list("status").annotate(n=Count("id")))
    return {"date": today, "present": c.get("present", 0), "absent": c.get("absent", 0), "on_leave": c.get("on_leave", 0),
            "reported": sum(c.values())}


def _vehicles(unit):
    from apps.vehicles.models import Vehicle

    qs = Vehicle.objects.filter(org_unit__path__startswith=unit.path)
    by = Counter(dict(qs.values_list("status").annotate(n=Count("id"))))
    return {"total": sum(by.values()), "by_status": [{"status": k, "count": v} for k, v in by.most_common()]}


def unit_activity(user, unit):
    """Activity of one unit and its subtree. Blocks the caller may not see are None."""
    since = timezone.now() - timedelta(days=WINDOW_DAYS)
    see_ob_custody = _may(user, "detention.view", unit)
    return {
        "window_days": WINDOW_DAYS,
        "occurrence": _occurrence(unit, since) if see_ob_custody else None,
        "custody": _custody(unit, since) if see_ob_custody else None,
        "attendance": _attendance(unit) if _may(user, "attendance.view", unit) else None,
        "vehicles": _vehicles(unit) if _may(user, "vehicles.view", unit) else None,
    }
