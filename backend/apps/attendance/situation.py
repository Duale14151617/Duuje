"""Unit situation report figures, computed from saved records only (never typed in).

Covers one unit and everything below it: personnel status counts (jailed, on leave, ... as at the time the report is made),
attendance for the period (present / absent / on leave, person-days not recorded) and ammunition (balance at start, opening, receipts, returns, issues,
expenditure, loss and damage, adjustments, transfers out, remaining) from the ammunition ledger. The figures are a snapshot: they are recomputed when the draft is created, edited
and submitted, then frozen in the submission's revision, so an approved report never changes under the reader.

Ammunition = stock categories whose code starts with "ammunition". Reading them needs `logistics.restricted` AND
`logistics.view` over the unit: a commander who is not authorized cannot produce the report, rather than getting zeros.
"""
from datetime import timedelta

from django.db.models import Count, F, Q

from apps.accounts import scope
from apps.core.errors import field_error
from apps.logistics import ammunition
from apps.logistics.models import Asset, AssetEvent, Reconciliation, ReconciliationLine, StockLine
from apps.weapons.models import WeaponCustody
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING

from .models import AttendanceRecord

SITUATION_REPORT = "unit_situation_report"
AMMO_PREFIX = "ammunition"
FIGURE_KEYS = [
    "personnel_total", "personnel_active", "personnel_on_leave", "personnel_suspended", "personnel_jailed", "personnel_died",
    "attendance_present", "attendance_absent", "attendance_on_leave", "attendance_not_recorded",
    "ammo_balance_start", "ammo_opening_recorded", "ammo_received", "ammo_returned", "ammo_adjusted_up",
    "ammo_issued", "ammo_expended", "ammo_lost_damaged", "ammo_adjusted_down", "ammo_transferred_out", "ammo_remaining",
    "weapons_total", "weapons_in_custody", "weapons_issued", "weapons_returned", "weapons_lost_missing", "weapons_registered",
    "weapons_condition_changes", "weapons_held_by_non_serving",
    "recon_completed", "recon_variance_lines", "recon_open_discrepancies",
]


def authorize(user, unit):
    if not scope.can(user, "attendance.view", unit=unit):
        raise field_error("org_unit", "out_of_scope", "That unit is outside your scope.")
    if not (scope.can(user, "logistics.restricted", unit=unit) and scope.can(user, "logistics.view", unit=unit)):
        raise field_error("figures", "ammunition_not_authorized", "You are not authorized to report ammunition for this unit.")
    if not scope.can(user, "weapons.view", unit=unit):
        raise field_error("figures", "weapons_not_authorized", "You are not authorized to report weapons for this unit.")


def period_kind(start, end):
    """day / month / half / year when the dates are exactly such a period, otherwise None."""
    for kind in ("day", "month", "half", "year"):
        if period_bounds(kind, start) == (start, end):
            return kind
    return None


def weapon_figures(unit, start, end):
    assets = Asset.objects.filter(weapon__isnull=False).filter(
        Q(org_unit__path__startswith=unit.path) | Q(issued_to_unit__path__startswith=unit.path))
    custody = WeaponCustody.objects.filter(asset__in=assets)
    events = AssetEvent.objects.filter(asset__in=assets, created_at__date__range=(start, end))
    return {
        "weapons_total": assets.count(),
        "weapons_in_custody": custody.filter(issued_at__date__lte=end).filter(
            Q(returned_at__isnull=True) | Q(returned_at__date__gt=end)).count(),
        "weapons_issued": custody.filter(issued_at__date__range=(start, end)).count(),
        "weapons_returned": custody.filter(returned_at__date__range=(start, end), outcome="returned").count(),
        "weapons_lost_missing": events.filter(kind__in=["lost", "missing"]).count(),
        "weapons_registered": events.filter(kind="register").count(),
        "weapons_condition_changes": events.filter(kind="condition").count(),
        "weapons_held_by_non_serving": custody.filter(returned_at__isnull=True, personnel__status__in=NOT_SERVING).count(),
    }


def reconciliation_figures(unit, start, end):
    recs = Reconciliation.objects.filter(org_unit__path__startswith=unit.path)
    done = recs.filter(status="completed", completed_at__date__range=(start, end))
    lines = ReconciliationLine.objects.filter(reconciliation__in=done)
    off_count = lines.filter(stock_line__isnull=False, counted_quantity__isnull=False).exclude(counted_quantity=F("expected_quantity")).count()
    not_found = lines.filter(asset__isnull=False, found=False).count()
    open_lines = ReconciliationLine.objects.filter(reconciliation__in=recs.filter(status="open"), stock_line__isnull=False,
                                                   counted_quantity__isnull=False).exclude(counted_quantity=F("expected_quantity"))
    return {"recon_completed": done.count(), "recon_variance_lines": off_count + not_found,
            "recon_open_discrepancies": open_lines.count()}


def compute_figures(user, unit, start, end):
    authorize(user, unit)
    if period_kind(start, end) is None:
        raise field_error("period_end", "period_not_standard", "Choose a whole day, month, six months or year.")
    days = (end - start).days + 1
    people = Personnel.objects.filter(org_unit__path__startswith=unit.path)
    by_status = {s: n for s, n in people.values_list("status").annotate(n=Count("id"))}
    serving = people.exclude(status__in=NOT_SERVING).count()
    rows = AttendanceRecord.objects.filter(org_unit__path__startswith=unit.path, report_date__range=(start, end),
                                           superseded_at__isnull=True)
    att = {s: n for s, n in rows.values_list("status").annotate(n=Count("id"))}
    recorded = sum(att.values())

    lines = StockLine.objects.filter(org_unit__path__startswith=unit.path, category__kind="stock",
                                     category__code__startswith=AMMO_PREFIX)
    ammo = {f"ammo_{k}": v for k, v in ammunition.totals(list(lines), start, end).items()}
    return {
        "personnel_total": serving,
        "personnel_active": by_status.get("active", 0), "personnel_on_leave": by_status.get("on_leave", 0),
        "personnel_suspended": by_status.get("suspended", 0), "personnel_jailed": by_status.get("jailed", 0),
        "personnel_died": by_status.get("died", 0),
        "attendance_present": att.get("present", 0), "attendance_absent": att.get("absent", 0),
        "attendance_on_leave": att.get("on_leave", 0),
        "attendance_not_recorded": max(0, serving * days - recorded),
        **ammo,
        **weapon_figures(unit, start, end),
        **reconciliation_figures(unit, start, end),
    }


def period_bounds(kind, anchor):
    if kind == "day":
        return anchor, anchor
    if kind == "month":
        first = anchor.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        return first, nxt - timedelta(days=1)
    if kind == "half":
        return (anchor.replace(month=1, day=1), anchor.replace(month=6, day=30)) if anchor.month <= 6 \
            else (anchor.replace(month=7, day=1), anchor.replace(month=12, day=31))
    if kind == "year":
        return anchor.replace(month=1, day=1), anchor.replace(month=12, day=31)
    raise field_error("period", "invalid_period", "Choose day, month, half or year.")
