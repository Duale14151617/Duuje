"""What a unit is actually doing: attendance today and vehicles.

READ-ONLY and built from the records the other apps already keep; nothing is stored or invented here. Each block is only returned
to a caller who holds the permission of the module it comes from (a block they may not see is `None`, never zero), and every
count covers the unit and everything below it (a battalion's sections, a brigade's battalions ...), by the unit path.
"""
from collections import Counter

from django.db.models import Count
from django.utils import timezone

from apps.accounts import scope

WINDOW_DAYS = 30


def _may(user, code, unit):
    return scope.can(user, code, unit=unit)


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
    return {
        "window_days": WINDOW_DAYS,
        "attendance": _attendance(unit) if _may(user, "attendance.view", unit) else None,
        "vehicles": _vehicles(unit) if _may(user, "vehicles.view", unit) else None,
    }
