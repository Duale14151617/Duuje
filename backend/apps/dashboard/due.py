"""Due soon: things with a date that is close or already past, limited to what the person may see.

Kinds: ID cards about to expire, vehicles due for service, fitness reviews due, approved leave about to end, training past or near its
end date and still open, and role assignments about to end or just ended. Nothing
here invents a deadline: each date comes from a record somebody entered. A list never shows more than CAP rows per kind (the true
count is always given). The same figures feed the daily digest notification, which says only HOW MANY items are waiting.
"""
from datetime import timedelta

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.accounts import scope
from apps.accounts.models import RoleAssignment
from apps.issuance.models import IssuedDocument
from apps.leave.models import LeaveRequest
from apps.medical.models import MedicalEntry
from apps.training.models import TrainingRecord
from apps.vehicles.models import MaintenanceRecord, Vehicle

CAP = 50
ID_CARD_DAYS = 30
SERVICE_DAYS = 14
FITNESS_DAYS = 14
LEAVE_DAYS = 3
TRAINING_DAYS = 7
ROLE_DAYS = 30
ROLE_GRACE_DAYS = 30  # a role that ended this recently still shows, as overdue, until someone renews or revokes it


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


def _fitness_reviews(user, today, unit=None):
    """People whose current fitness entry has a review date that is close or past. Only the NAME and DATE are shown: the status, the
    restriction and the details stay behind `fitness.view` / `medical.view` on the fitness page."""
    q = scope.unit_scope_q(user, "fitness.view", "personnel__org_unit__")
    if q is None:
        return None
    q = _limit(q, unit, "personnel__org_unit__")
    newer = MedicalEntry.objects.filter(personnel=OuterRef("personnel"), recorded_at__gt=OuterRef("recorded_at"))
    corrected = MedicalEntry.objects.filter(corrects=OuterRef("pk"))
    qs = (MedicalEntry.objects.filter(q, review_due__isnull=False, review_due__lte=today + timedelta(days=FITNESS_DAYS))
          .exclude(Exists(newer)).exclude(Exists(corrected))
          .select_related("personnel", "personnel__org_unit").order_by("review_due"))
    return _group("fitness_reviews", ({"id": str(e.personnel_id), "label": e.personnel.full_name, "due_on": e.review_due.isoformat(),
                                       "overdue": e.review_due < today, "unit_en": e.personnel.org_unit.name_en,
                                       "unit_so": e.personnel.org_unit.name_so} for e in qs), "/fitness")


def _leave_ending(user, today, unit=None):
    q = scope.unit_scope_q(user, "leave.view", "org_unit__")
    if q is None:
        return None
    q = _limit(q, unit, "org_unit__")
    qs = (LeaveRequest.objects.filter(q, status=LeaveRequest.Status.APPROVED, start_date__lte=today,
                                      end_date__gte=today, end_date__lte=today + timedelta(days=LEAVE_DAYS))
          .select_related("personnel", "org_unit").order_by("end_date"))
    return _group("leave_ending", ({"id": str(r.pk), "label": r.personnel.full_name, "due_on": r.end_date.isoformat(), "overdue": False,
                                    "unit_en": r.org_unit.name_en, "unit_so": r.org_unit.name_so} for r in qs), "/leave")


def _training_open(user, today, unit=None):
    """Courses whose end date is near or past while the record is still enrolled or in progress: someone has to close it out."""
    q = scope.unit_scope_q(user, "training.view", "personnel__org_unit__")
    if q is None:
        return None
    q = _limit(q, unit, "personnel__org_unit__")
    qs = (TrainingRecord.objects.filter(q, status__in=[TrainingRecord.Status.ENROLLED, TrainingRecord.Status.IN_PROGRESS],
                                        end_date__isnull=False, end_date__lte=today + timedelta(days=TRAINING_DAYS))
          .select_related("personnel", "personnel__org_unit", "course").order_by("end_date"))
    return _group("training_open", ({"id": str(t.pk), "label": f"{t.personnel.full_name} · {t.course.name_en}", "due_on": t.end_date.isoformat(),
                                     "overdue": t.end_date < today, "unit_en": t.personnel.org_unit.name_en,
                                     "unit_so": t.personnel.org_unit.name_so} for t in qs), "/training")


def _role_ends(user, today, unit=None):
    q = scope.unit_scope_q(user, "users.manage", "org_unit__")
    if q is None:
        return None
    q = _limit(q, unit, "org_unit__")
    qs = (RoleAssignment.objects.filter(q, revoked_at__isnull=True, user__is_active=True, valid_until__isnull=False,
                                        valid_until__lte=today + timedelta(days=ROLE_DAYS),
                                        valid_until__gte=today - timedelta(days=ROLE_GRACE_DAYS))
          .select_related("user", "role", "org_unit").order_by("valid_until"))
    return _group("role_ends", ({"id": str(a.pk), "label": f"{a.user.full_name or a.user.username} · {a.role.name_en}",
                                 "due_on": a.valid_until.isoformat(), "overdue": a.valid_until < today,
                                 "unit_en": a.org_unit.name_en, "unit_so": a.org_unit.name_so} for a in qs), "/users")


def due_soon(user, now=None, unit=None):
    now = now or timezone.now()
    today = timezone.localdate(now)
    makers = (_id_cards, _vehicle_service, _fitness_reviews, _leave_ending, _training_open, _role_ends)
    groups = [g for g in (m(user, today, unit) for m in makers) if g is not None]
    return {"groups": groups, "total": sum(g["count"] for g in groups), "as_of": now.isoformat()}
