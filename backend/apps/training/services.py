from datetime import date

from django.db import transaction
from rest_framework.exceptions import PermissionDenied

from apps.accounts import scope
from apps.audit.services import record
from apps.core.concurrency import versioned_update
from apps.core.errors import field_error
from apps.core.exceptions import VersionConflict
from apps.core.orgpaths import region_id
from apps.organization.models import OrganizationalUnit
from apps.workflows.services import InvalidTransition

from .models import TrainingRecord

S = TrainingRecord.Status
TRANSITIONS = {  # new status -> allowed current statuses
    "in_progress": {S.ENROLLED},
    "completed": {S.IN_PROGRESS},
    "failed": {S.IN_PROGRESS},
    "withdrawn": {S.ENROLLED, S.IN_PROGRESS},
}
OPEN = {S.ENROLLED, S.IN_PROGRESS}
ELIGIBLE = {"active", "on_leave"}


def authorize(request, person):
    if not scope.can(request.user, "training.manage", unit=person.org_unit):
        record("access.denied", request=request, outcome="denied", entity_type="training_record",
               metadata={"permission": "training.manage"})
        raise PermissionDenied("You do not have permission to do that here.", code="permission_denied")


def enroll(request, person, course, start_date, end_date, notes):
    authorize(request, person)
    if person.status not in ELIGIBLE:
        raise field_error("personnel", "person_not_eligible")
    if not course.active:
        raise field_error("course", "course_inactive")
    if end_date and end_date < start_date:
        raise field_error("end_date", "period_invalid")
    if TrainingRecord.objects.filter(personnel=person, course=course, start_date=start_date).exists():
        raise field_error("start_date", "training_duplicate")
    with transaction.atomic():
        rec = TrainingRecord.objects.create(personnel=person, course=course, start_date=start_date, end_date=end_date,
                                            notes=notes, created_by=request.user, created_by_username=request.user.username)
        record("training.enroll", request=request, entity_type="training_record", entity_id=rec.pk,
               metadata={"course": course.code, "unit": str(person.org_unit_id)})
    return rec


def edit(request, rec, changes, expected):
    authorize(request, rec.personnel)
    if rec.status not in OPEN:
        raise InvalidTransition()
    end = changes.get("end_date", rec.end_date)
    if end and end < rec.start_date:
        raise field_error("end_date", "period_invalid")
    with transaction.atomic():
        updated = versioned_update(rec, changes, expected)
        record("training.update", request=request, entity_type="training_record", entity_id=updated.pk,
               metadata={"fields": sorted(changes)})
    return updated


def set_status(request, rec, new_status, completed_on, expected):
    authorize(request, rec.personnel)
    if rec.version != expected:
        raise VersionConflict()
    if rec.status not in TRANSITIONS[new_status]:
        raise InvalidTransition()
    changes = {"status": new_status}
    if new_status == "completed":
        if completed_on is None:
            raise field_error("completed_on", "completed_on_required")
        if completed_on < rec.start_date or completed_on > date.today():
            raise field_error("completed_on", "completed_on_invalid")
        changes["completed_on"] = completed_on
    with transaction.atomic():
        old = rec.status
        updated = versioned_update(rec, changes, expected)
        record(f"training.{new_status}", request=request, entity_type="training_record", entity_id=updated.pk,
               metadata={"from": old, "to": new_status})
    return updated


def summary(user, params):
    q = scope.unit_scope_q(user, "training.report", "personnel__org_unit__")
    if q is None:
        return {"rows": []}
    qs = TrainingRecord.objects.filter(q).select_related("course", "personnel__org_unit")
    if params.get("course"):
        qs = qs.filter(course=params["course"])
    if params.get("from"):
        qs = qs.filter(start_date__gte=params["from"])
    if params.get("to"):
        qs = qs.filter(start_date__lte=params["to"])
    regions = {str(r.pk): r for r in OrganizationalUnit.objects.filter(level="region")}
    rows = {}
    for rec in qs[:10000]:
        rid = region_id(rec.personnel.org_unit.path)
        key = (rec.course_id, rid)
        if key not in rows:
            r = regions.get(rid)
            rows[key] = {"course": {"id": str(rec.course_id), "code": rec.course.code, "name_en": rec.course.name_en,
                                    "name_so": rec.course.name_so},
                         "region": {"id": rid, "code": r.code if r else "", "name_en": r.name_en if r else "",
                                    "name_so": r.name_so if r else ""}, "counts": {}, "total": 0}
        rows[key]["counts"][rec.status] = rows[key]["counts"].get(rec.status, 0) + 1
        rows[key]["total"] += 1
    return {"rows": sorted(rows.values(), key=lambda x: (x["course"]["code"], x["region"]["code"]))}
