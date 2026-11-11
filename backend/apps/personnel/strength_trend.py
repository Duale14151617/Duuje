"""Daily headcount snapshots for the strength trend. Aggregates only; no person-level data is stored.

Recorded two ways: the `snapshot_strength` management command (run it daily from cron where one exists), and lazily the first
time the combined report is opened each day, so a host without a scheduler (a free web tier) still builds a history. Days nobody
opens the report and no cron runs simply have no point; the chart connects the days that exist.
"""
from datetime import timedelta

from django.db import IntegrityError
from django.db.models import Count, Q
from django.utils import timezone

from apps.organization.models import OrganizationalUnit

from .models import Personnel, StrengthSnapshot

LEFT = (Personnel.Status.RETIRED, Personnel.Status.DISCHARGED)
TREND_DAYS = 90


def _restricted_q():
    """Personnel in a restricted unit or anywhere beneath it (same path rule the access gate uses)."""
    q = Q(pk__in=[])
    for path in OrganizationalUnit.objects.filter(restricted=True).values_list("path", flat=True):
        q |= Q(org_unit__path__startswith=path)
    return q


def _counts(people):
    total = people.count()
    serving = people.exclude(status__in=LEFT).count()
    return total, serving


def take_snapshot(day=None):
    """Record (or return) the snapshot for `day` (default: today). Safe to call repeatedly and from concurrent requests."""
    day = day or timezone.localdate()
    existing = StrengthSnapshot.objects.filter(date=day).first()
    if existing:
        return existing
    everyone = Personnel.objects.all()
    total_all, serving_all = _counts(everyone)
    total_open, serving_open = _counts(everyone.exclude(_restricted_q()))
    try:
        return StrengthSnapshot.objects.create(date=day, total_all=total_all, serving_all=serving_all,
                                               total_open=total_open, serving_open=serving_open)
    except IntegrityError:  # another request recorded today first
        return StrengthSnapshot.objects.get(date=day)


def series(include_restricted: bool, days: int = TREND_DAYS):
    """Chronological points for the report. Restricted units are counted only when the caller may see inside them."""
    since = timezone.localdate() - timedelta(days=days)
    key = "all" if include_restricted else "open"
    return [{"date": r.date.isoformat(), "total": getattr(r, f"total_{key}"), "serving": getattr(r, f"serving_{key}")}
            for r in StrengthSnapshot.objects.filter(date__gte=since)]
