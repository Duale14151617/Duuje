"""The unit report: one PDF for a unit and everything below it. Strength, leave, weapons, vehicles and fuel for a period.

Counts and totals only: no names, service numbers or serial numbers, so a printed or emailed copy can go to a commander who has no
login. A section is included only when EVERY person who will see the report may see that kind of information for this unit
(`viewers`: the signed-in person for a download; the schedule's creator and all recipients for an emailed copy), the same rule the
scheduled strength email uses, so a report can never show someone more than the app would.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Sum
from django.utils import timezone

from apps.accounts import scope
from apps.core.pdf import build_pdf
from apps.leave.models import LeaveRequest
from apps.logistics.models import Asset
from apps.personnel import report as strength
from apps.vehicles.logbook import consumption
from apps.vehicles.models import FuelEntry, Vehicle, VehicleStatusType

MAX_DAYS = 366
ASSET_LABELS = {"in_stock": "In store", "issued": "Issued", "maintenance": "In maintenance", "missing": "Missing", "lost": "Lost", "retired": "Retired"}
WEAPON_CONDITIONS = {"serviceable": "Serviceable", "needs_repair": "Needs repair", "unserviceable": "Unserviceable"}
LEAVE_LABELS = {"pending": "Waiting for decision", "approved": "Approved", "rejected": "Rejected", "cancelled": "Cancelled"}
CONDITION_LABELS = {"good": "Good", "fair": "Fair", "poor": "Poor", "unserviceable": "Unserviceable", "unknown": "Not recorded"}


def _label(code, labels):
    return labels.get(code, str(code).replace("_", " ").capitalize())


def _allowed(viewers, code, unit):
    return all(scope.can(u, code, unit=unit) for u in viewers)


def _strength(viewers, unit, d0, d1):
    data = strength.build(viewers[0], unit, d0, d1)
    if data is None:
        return None
    t = data["totals"]
    out = [{"heading": "Strength", "rows": [
        ["Serving", t["serving"]], ["Recorded in total", t["on_file"]], ["Active", t["active"]], ["On leave", t["on_leave"]],
        ["Suspended", t["suspended"]], ["Joined in the period", t["joined"]], ["Left in the period", t["left"]],
        ["Promoted in the period", t["promoted"]]]}]
    if data["ranks"]:
        out.append({"heading": "Serving by rank", "columns": ["Rank", "Serving", "Recorded"],
                    "rows": [[r["name_en"] or "-", r["serving"], r["on_file"]] for r in data["ranks"]]})
    return out


def _leave(unit, d0, d1, today):
    base = LeaveRequest.objects.filter(org_unit__path__startswith=unit.path)
    rows = dict(base.filter(start_date__lte=d1, end_date__gte=d0).values_list("status").annotate(n=Count("id")))
    away = base.filter(status="approved", start_date__lte=today, end_date__gte=today).count()
    lines = [["Away on approved leave today", away]]
    lines += [[_label(k, LEAVE_LABELS) + " (requests touching the period)", v] for k, v in sorted(rows.items())]
    return [{"heading": "Leave", "rows": lines}]


def _weapons(unit):
    base = Asset.objects.filter(org_unit__path__startswith=unit.path, weapon__isnull=False)
    by_status = dict(base.values_list("status").annotate(n=Count("id")))
    in_service = base.exclude(status__in=["retired", "lost"])
    by_cond = dict(in_service.values_list("weapon__condition").annotate(n=Count("id")))
    rows = [["Weapons on the register", sum(by_status.values())]]
    rows += [[_label(k, ASSET_LABELS), v] for k, v in sorted(by_status.items())]
    out = [{"heading": "Weapons", "rows": rows}]
    if by_cond:
        out.append({"heading": "Weapons in service by condition", "rows": [[_label(k, WEAPON_CONDITIONS), v] for k, v in sorted(by_cond.items())]})
    return out


def _vehicles(unit):
    base = Vehicle.objects.filter(org_unit__path__startswith=unit.path)
    names = dict(VehicleStatusType.objects.values_list("code", "name_en"))
    by_status = dict(base.values_list("status").annotate(n=Count("id")))
    by_cond = dict(base.exclude(status="decommissioned").values_list("condition").annotate(n=Count("id")))
    out = [{"heading": "Vehicles", "rows": [["Vehicles on the register", sum(by_status.values())]] +
            [[names.get(k) or _label(k, {}), v] for k, v in sorted(by_status.items())]}]
    if by_cond:
        out.append({"heading": "Vehicles in use by condition", "rows": [[_label(k, CONDITION_LABELS), v] for k, v in sorted(by_cond.items())]})
    return out


def _fuel(viewers, unit, d0, d1):
    qs = FuelEntry.objects.filter(vehicle__org_unit__path__startswith=unit.path, voided_at__isnull=True, filled_on__gte=d0, filled_on__lte=d1)
    entries = qs.count()
    if not entries:
        return [{"heading": "Fuel", "rows": [["Refuellings recorded in the period", 0]]}]
    litres = qs.aggregate(s=Sum("litres"))["s"] or Decimal(0)
    rows = [["Refuellings recorded in the period", entries], ["Litres bought", f"{litres:,.1f}"]]
    rows += [[f"  {k.capitalize()} (litres)", f"{v:,.1f}"] for k, v in qs.values_list("fuel_type").annotate(s=Sum("litres")).order_by("fuel_type")]
    if _allowed(viewers, "vehicles.cost", unit):
        for cur, total in qs.exclude(cost__isnull=True).values_list("currency").annotate(s=Sum("cost")).order_by("currency"):
            rows.append([f"Fuel cost{' (' + cur + ')' if cur else ''}", f"{total:,.2f}"])
    out = [{"heading": "Fuel", "rows": rows}]
    top = []
    per_vehicle = qs.values("vehicle_id", "vehicle__vehicle_id", "vehicle__plate").annotate(s=Sum("litres")).order_by("-s")[:15]
    for v in per_vehicle:
        c = consumption(qs.filter(vehicle_id=v["vehicle_id"]))
        label = v["vehicle__vehicle_id"] + (f" ({v['vehicle__plate']})" if v["vehicle__plate"] else "")
        top.append([label, f"{v['s']:,.1f}", f"{c:.1f}" if c is not None else "-"])
    out.append({"heading": "Fuel by vehicle (highest first, up to 15)", "columns": ["Vehicle", "Litres", "L / 100 km"], "rows": top,
                "note": "Litres per 100 km needs at least two full-tank fills in the period, so some vehicles show a dash."})
    return out


def build(viewers, unit, d0, d1):
    """Sections for the unit report, and whether anything could be shown. `viewers` is a non-empty list of users."""
    today = timezone.localdate()
    sections = []
    if _allowed(viewers, "personnel.view", unit):
        sections += _strength(viewers, unit, d0, d1) or []
    if _allowed(viewers, "leave.view", unit):
        sections += _leave(unit, d0, d1, today)
    if _allowed(viewers, "weapons.view", unit):
        sections += _weapons(unit)
    if _allowed(viewers, "vehicles.view", unit):
        sections += _vehicles(unit)
        sections += _fuel(viewers, unit, d0, d1)
    return sections


def period(raw_from, raw_to, default_days=30):
    """(from, to) dates from ISO strings; raises ValueError with a readable message."""
    today = timezone.localdate()
    try:
        d1 = date.fromisoformat(raw_to) if raw_to else today
        d0 = date.fromisoformat(raw_from) if raw_from else d1 - timedelta(days=default_days - 1)
    except ValueError:
        raise ValueError("Use dates written as YYYY-MM-DD.")
    if d1 < d0:
        raise ValueError("The end date cannot be before the start date.")
    if (d1 - d0).days > MAX_DAYS:
        raise ValueError("Choose a period of at most one year.")
    return d0, d1


def render_pdf(viewers, unit, d0, d1):
    """The finished PDF as bytes, or None when the viewers may see nothing about this unit."""
    sections = build(viewers, unit, d0, d1)
    if not sections:
        return None
    org = getattr(settings, "ORG_NAME", "Puntland Defence Forces")
    prepared = timezone.localtime().strftime("%Y-%m-%d %H:%M")
    return build_pdf(
        f"Unit report: {unit.name_en}", sections, org=org,
        subtitle=f"Period {d0.isoformat()} to {d1.isoformat()}. Includes this unit and every unit below it. Prepared {prepared}. "
                 "Totals only: no names, service numbers or serial numbers are included.",
        footer=f"{org} - for official use")


def filename(unit, d0, d1):
    safe = "".join(c if c.isalnum() else "-" for c in (unit.code or "unit")).strip("-").lower() or "unit"
    return f"unit-report-{safe}-{d0.isoformat()}-to-{d1.isoformat()}.pdf"
