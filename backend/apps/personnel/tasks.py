"""Administrative task tracking for units (Operations Section and others).

Records an authorized task, who is responsible, assignment and due dates, status, and a completion report with a document
reference. It supports accountability only; it adds no operational procedure. HQ administrators act directly; every change
is audited and written to an append-only event log.
"""
from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from apps.accounts import scope
from apps.audit.services import record
from apps.core.concurrency import versioned_update
from apps.core.errors import field_error
from apps.organization.models import OrganizationalUnit

from .models import Personnel, TaskEvent, UnitTask
from .services import NOT_SERVING

PERM = "tasks.manage"
OPEN = (UnitTask.Status.OPEN, UnitTask.Status.IN_PROGRESS)


class InvalidState(APIException):
    status_code = 409
    default_detail = "That is not allowed in the current state."
    default_code = "invalid_transition"


def _id(value):
    import uuid
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _text(value, field, code, maxlen, required=True):
    value = str(value or "").strip()
    if required and not value:
        raise field_error(field, code, "Required.")
    if len(value) > maxlen:
        raise field_error(field, "too_long", "Too long.")
    return value


def _day(value, field, required=False):
    if value in (None, ""):
        if required:
            raise field_error(field, "invalid_date", "Required.")
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise field_error(field, "invalid_date", "Use a date like 2026-01-31.")


def _unit(actor, value):
    unit = OrganizationalUnit.objects.filter(pk=_id(value), active=True).first() if _id(value) else None
    if unit is None or not scope.can(actor, PERM, unit=unit):  # unknown and out-of-scope read alike
        raise field_error("org_unit", "org_unit_invalid", "That unit cannot be used.")
    return unit


def _responsible(value, unit):
    if value in (None, ""):
        return None
    person = Personnel.objects.filter(pk=_id(value), org_unit__path__startswith=unit.path).exclude(status__in=NOT_SERVING).first() if _id(value) else None
    if person is None:
        raise field_error("responsible", "responsible_not_in_unit", "The responsible person must be serving in this unit or a unit below it.")
    return person


def _event(task, actor, kind, from_status="", to_status="", note=""):
    TaskEvent.objects.create(task=task, kind=kind, from_status=from_status, to_status=to_status, note=note[:300],
                             actor_id=getattr(actor, "pk", None), actor_username=getattr(actor, "username", ""))


def _check_dates(assigned, due):
    if due and due < assigned:
        raise field_error("due_on", "due_before_assigned", "The due date is before the assignment date.")


def create(request, d):
    unit = _unit(request.user, d.get("org_unit"))
    title = _text(d.get("title"), "title", "title_required", 200)
    authority = _text(d.get("authority_ref"), "authority_ref", "authority_required", 150)
    assigned = _day(d.get("assigned_on"), "assigned_on") or date.today()
    due = _day(d.get("due_on"), "due_on")
    _check_dates(assigned, due)
    person = _responsible(d.get("responsible"), unit)
    with transaction.atomic():
        task = UnitTask.objects.create(
            org_unit=unit, title=title, description=_text(d.get("description"), "description", "", 1000, False), authority_ref=authority,
            assigned_on=assigned, due_on=due, responsible=person, created_by=request.user, created_by_username=request.user.username)
        _event(task, request.user, "created", to_status=task.status, note=authority)
        record("task.create", request=request, entity_type="unit_task", entity_id=task.pk,
               metadata={"unit": str(unit.pk), "authority_ref": authority, "responsible": str(person.pk) if person else None})
    return task


def _manage(request, task):
    if not scope.can(request.user, PERM, unit=task.org_unit):
        raise field_error("org_unit", "org_unit_invalid", "That unit cannot be used.")


def update(request, task, d, expected):
    with transaction.atomic():
        task = UnitTask.objects.select_for_update().select_related("org_unit").get(pk=task.pk)
        _manage(request, task)
        if task.status not in OPEN:
            raise InvalidState()
        fields = {}
        if "title" in d:
            fields["title"] = _text(d["title"], "title", "title_required", 200)
        if "description" in d:
            fields["description"] = _text(d["description"], "description", "", 1000, False)
        if "due_on" in d:
            fields["due_on"] = _day(d["due_on"], "due_on")
        if "responsible" in d:
            fields["responsible"] = _responsible(d["responsible"], task.org_unit)
        _check_dates(task.assigned_on, fields.get("due_on", task.due_on))
        task = versioned_update(task, fields, expected)
        _event(task, request.user, "updated", note=", ".join(sorted(fields)))
        record("task.update", request=request, entity_type="unit_task", entity_id=task.pk, metadata={"fields": sorted(fields)})
    return task


def _move(request, task, expected, kind, to_status, fields, note, allowed=OPEN):
    with transaction.atomic():
        task = UnitTask.objects.select_for_update().select_related("org_unit").get(pk=task.pk)
        _manage(request, task)
        if task.status not in allowed:
            raise InvalidState()
        before = task.status
        task = versioned_update(task, {"status": to_status, **fields}, expected)
        _event(task, request.user, kind, before, to_status, note)
        record(f"task.{kind}", request=request, entity_type="unit_task", entity_id=task.pk, metadata={"from": before, "to": to_status})
    return task


def start(request, task, expected):
    return _move(request, task, expected, "started", UnitTask.Status.IN_PROGRESS, {}, "", allowed=(UnitTask.Status.OPEN,))


def complete(request, task, d, expected):
    report = _text(d.get("completion_report"), "completion_report", "report_required", 2000)
    doc = _text(d.get("document_ref"), "document_ref", "", 150, False)
    return _move(request, task, expected, "completed", UnitTask.Status.COMPLETED,
                 {"completion_report": report, "document_ref": doc, "completed_at": timezone.now()}, doc)


def cancel(request, task, d, expected):
    reason = _text(d.get("reason"), "reason", "reason_required", 300)
    return _move(request, task, expected, "cancelled", UnitTask.Status.CANCELLED, {"cancel_reason": reason}, reason)
