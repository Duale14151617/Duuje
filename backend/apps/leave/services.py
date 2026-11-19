"""Approved leave as an attendance fact.

Attendance records are append-only and cannot be dated in the future, and leave can be cancelled or rejected after the fact,
so approved leave is not copied into the attendance table. It is read through here instead: a day covered by approved leave
counts as "on leave" until the commander records that day, and a recorded attendance row always wins (for example a soldier
called back early is recorded as present). Cancel the leave and the days stop counting, with nothing to undo.
"""
from datetime import timedelta

from .models import LeaveRequest


def approved_leave_for(person_ids, start, end):
    """Approved leave overlapping [start, end] for these people: {personnel_id: [LeaveRequest, ...]} (leave_type loaded)."""
    out = {}
    qs = LeaveRequest.objects.filter(personnel_id__in=list(person_ids), status="approved", start_date__lte=end,
                                     end_date__gte=start).select_related("leave_type")
    for r in qs:
        out.setdefault(r.personnel_id, []).append(r)
    return out


def leave_on(person_leave, day):
    """The approved leave in `person_leave` (a list from approved_leave_for) that covers `day`, or None."""
    return next((r for r in person_leave or [] if r.start_date <= day <= r.end_date), None)


def unrecorded_leave_days(people, start, end, record_model):
    """How many (person, day) pairs in [start, end] are covered by approved leave and have no current attendance record.
    `people` is a queryset of serving Personnel; `record_model` is AttendanceRecord (passed in to keep apps independent)."""
    ids = list(people.values_list("pk", flat=True))
    if not ids:
        return 0
    leave = approved_leave_for(ids, start, end)
    if not leave:
        return 0
    covered = set()
    for pid, rows in leave.items():
        for r in rows:
            d, last = max(r.start_date, start), min(r.end_date, end)
            while d <= last:
                covered.add((pid, d))
                d += timedelta(days=1)
    recorded = set(record_model.objects.filter(personnel_id__in=list(leave), report_date__range=(start, end),
                                               superseded_at__isnull=True).values_list("personnel_id", "report_date"))
    return len(covered - recorded)
