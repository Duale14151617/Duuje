"""Fitness for duty and restricted medical records.

Commanders with `fitness.view` see each person's fitness status, review date and duty restriction. The details behind it
(diagnosis, treatment, notes) need `medical.view`, held by the medical officer. Everything is encrypted at rest, append-only,
scoped like the rest of the personnel data, and every read and write is audited.
"""
import uuid
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record as audit
from apps.audit.services import record_read
from apps.core import crypto
from apps.core.errors import field_error
from apps.core.params import json_body, uuid_param
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING

from .models import MedicalEntry

STATUSES = [s.value for s in MedicalEntry.Fitness]
MAX_PEOPLE = 1000
MAX_REVIEW_YEARS = 3


def _uid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _dec(token):
    return crypto.decrypt(token) if token else ""


def _current(entries):
    """From one person's entries (newest first): the latest that nobody corrected."""
    corrected = {e.corrects_id for e in entries if e.corrects_id}
    return next((e for e in entries if e.pk not in corrected), None)


class FitnessViewSet(viewsets.ViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {"list": ("fitness.view", "any"), "history": ("fitness.view", "any"), "add": ("medical.manage", "any")}
    queryset = MedicalEntry.objects.none()

    def list(self, request):
        """?org_unit=<id>[&state=fit|limited|unfit|under_review|unassessed|overdue]: current fitness of serving people in the unit and below."""
        uid = uuid_param(request, "org_unit")
        unit = OrganizationalUnit.objects.filter(pk=uid).first() if uid else None
        if unit is None or not scope.can(request.user, "fitness.view", unit=unit):
            raise field_error("org_unit", "out_of_scope", "That unit is outside your scope.")
        q = scope.unit_scope_q(request.user, "fitness.view", "org_unit__")
        people = list(Personnel.objects.filter(q, org_unit__path__startswith=unit.path).exclude(status__in=NOT_SERVING)
                      .select_related("rank").order_by("full_name").distinct()[:MAX_PEOPLE])
        by_person = {}
        for e in MedicalEntry.objects.filter(personnel_id__in=[p.pk for p in people]).order_by("-recorded_at", "-id"):
            by_person.setdefault(e.personnel_id, []).append(e)
        today, wanted = timezone.localdate(), request.query_params.get("state")
        counts = {"fit": 0, "limited": 0, "unfit": 0, "under_review": 0, "unassessed": 0, "overdue": 0}
        rows = []
        for p in people:
            cur = _current(by_person.get(p.pk, []))
            overdue = cur is not None and cur.review_due is not None and cur.review_due < today
            state = cur.fitness_status if cur else "unassessed"
            counts[state] += 1
            counts["overdue"] += 1 if overdue else 0
            if wanted and wanted != state and not (wanted == "overdue" and overdue):
                continue
            rows.append({"personnel": {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number},
                         "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so},
                         "fitness_status": state, "review_due": cur.review_due.isoformat() if cur and cur.review_due else None,
                         "overdue": overdue, "restriction": _dec(cur.restriction_enc) if cur else "",
                         "assessed_at": cur.recorded_at.isoformat() if cur else None})
        record_read(request, "fitness.read", entity_type="fitness", org_unit=unit, count=len(rows))
        return Response({"org_unit": str(unit.pk), "counts": counts, "results": rows})

    @action(detail=False, methods=["get"])
    def history(self, request):
        """?personnel=<id>: every entry for one person, newest first. Details are included only for holders of `medical.view`."""
        pid = uuid_param(request, "personnel")
        person = Personnel.objects.select_related("org_unit").filter(pk=pid).first() if pid else None
        if person is None or not scope.can(request.user, "fitness.view", unit=person.org_unit):
            raise field_error("personnel", "person_unknown", "Unknown person.")  # unknown and out of scope read alike
        with_details = scope.can(request.user, "medical.view", unit=person.org_unit)
        rows = list(MedicalEntry.objects.filter(personnel=person).order_by("-recorded_at", "-id"))
        corrected = {e.corrects_id for e in rows if e.corrects_id}
        record_read(request, "medical.view" if with_details else "fitness.view", entity_type="personnel", entity_id=person.pk,
                    org_unit=person.org_unit, count=len(rows))
        return Response({"personnel": str(person.pk), "full_name": person.full_name, "can_see_details": with_details, "results": [
            {"id": str(e.pk), "fitness_status": e.fitness_status, "review_due": e.review_due.isoformat() if e.review_due else None,
             "restriction": _dec(e.restriction_enc), "details": _dec(e.details_enc) if with_details else None,
             "corrects": str(e.corrects_id) if e.corrects_id else None, "superseded": e.pk in corrected,
             "recorded_at": e.recorded_at.isoformat(), "recorded_by": e.recorded_by_username} for e in rows]})

    @action(detail=False, methods=["post"])
    def add(self, request):
        """{personnel, fitness_status, review_due?, restriction?, details?, corrects?}. Appends one entry; nothing is ever edited."""
        d = json_body(request)
        pid = d.get("personnel")
        person = Personnel.objects.select_related("org_unit").filter(pk=_uid(pid)).first() if _uid(pid) else None
        if person is None or not scope.can(request.user, "medical.manage", unit=person.org_unit):
            raise field_error("personnel", "person_unknown", "Unknown person.")
        if person.status in NOT_SERVING:
            raise field_error("personnel", "person_not_serving", "This person is no longer serving.")
        if d.get("fitness_status") not in STATUSES:
            raise field_error("fitness_status", "invalid_status", "Choose a fitness status.")
        due = None
        if d.get("review_due"):
            try:
                due = date.fromisoformat(str(d["review_due"]))
            except ValueError:
                raise field_error("review_due", "invalid_date", "Use a date like 2026-03-01.")
            if due < timezone.localdate() or due > timezone.localdate() + timedelta(days=366 * MAX_REVIEW_YEARS):
                raise field_error("review_due", "due_invalid", "The review date must be from today to three years ahead.")
        restriction, details = str(d.get("restriction") or "").strip(), str(d.get("details") or "").strip()
        if len(restriction) > 300 or len(details) > 4000:
            raise field_error("details", "too_long", "That text is too long.")
        if details and not scope.can(request.user, "medical.view", unit=person.org_unit):
            raise field_error("details", "details_not_allowed", "You may not record medical details.")
        with transaction.atomic():
            Personnel.objects.select_for_update().get(pk=person.pk)
            target = None
            if d.get("corrects"):
                target = MedicalEntry.objects.filter(pk=_uid(d["corrects"]), personnel=person).first() if _uid(d["corrects"]) else None
                if target is None:
                    raise field_error("corrects", "record_not_found", "That entry does not belong to this person.")
                if target.corrections.exists():
                    raise field_error("corrects", "already_corrected", "That entry was already corrected. Correct the latest entry instead.")
            row = MedicalEntry.objects.create(
                personnel=person, corrects=target, fitness_status=d["fitness_status"], review_due=due,
                restriction_enc=crypto.encrypt(restriction) if restriction else "", details_enc=crypto.encrypt(details) if details else "",
                recorded_by_id=request.user.pk, recorded_by_username=request.user.username)
            audit("medical.correct" if target else "medical.add", request=request, entity_type="personnel", entity_id=person.pk,
                  metadata={"entry": str(row.pk), "status": row.fitness_status})  # never the text itself
        return Response({"id": str(row.pk), "fitness_status": row.fitness_status}, status=201)
