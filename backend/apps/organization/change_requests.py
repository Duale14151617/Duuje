"""Approval queue for hierarchy-affecting actions.

HQ administrators PROPOSE; the super administrator DECIDES. A proposal is validated when it is made and validated again when it
is approved (people and units can change in between); only approval writes to live records, in one transaction, with the Army
order reference carried into the personnel history and the audit log. A super administrator's own proposal is applied at once
(`self_approved`). Actions that do not touch the hierarchy do not use this queue.
"""
from datetime import date

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError

from apps.accounts import scope
from apps.audit.services import record
from apps.core.concurrency import versioned_update
from apps.core.errors import field_error

from .models import ChangeRequest, OrganizationalUnit

S = ChangeRequest.Status
PROPOSE, APPROVE = "changes.propose", "changes.approve"


class StaleRequest(APIException):
    status_code = 409
    default_detail = "The records changed since this request was made. Reject it and propose it again."
    default_code = "stale_request"


class InvalidState(APIException):
    status_code = 409
    default_detail = "That is not allowed in the current state."
    default_code = "invalid_transition"


def _day(value, field):
    if value in (None, ""):
        return date.today()
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise field_error(field, "invalid_date", "Use a date like 2026-01-31.")


# ------------------------------------------------------------------ transfer handler
def _check_transfer(actor, code, payload, expect_from=None):
    """Validate a transfer against the live records. Returns (person, destination, normalized payload, summary)."""
    from apps.personnel.models import CommandAppointment, Personnel
    from apps.personnel.services import RuleError, check_assignment

    person = Personnel.objects.select_related("org_unit", "rank", "branch").filter(pk=str(payload.get("personnel") or "")).first() \
        if _is_uuid(payload.get("personnel")) else None
    dest = OrganizationalUnit.objects.select_related("branch").filter(pk=str(payload.get("org_unit") or "")).first() \
        if _is_uuid(payload.get("org_unit")) else None
    # unknown and out-of-scope read alike, as everywhere else in the application
    if person is None or not scope.can(actor, code, unit=person.org_unit):
        raise field_error("personnel", "personnel_not_found", "That person cannot be used.")
    if dest is None or not scope.can(actor, code, unit=dest):
        raise field_error("org_unit", "org_unit_invalid", "That unit cannot be used.")
    if person.status == Personnel.Status.DIED:
        raise field_error("personnel", "person_deceased", "This person is deceased; the file is closed to changes.")
    if expect_from is not None and str(person.org_unit_id) != expect_from:
        raise StaleRequest()
    if dest.pk == person.org_unit_id:
        raise field_error("org_unit", "same_unit", "The person is already assigned to that unit.")
    try:
        check_assignment(dest, person.rank)
    except RuleError as e:
        raise field_error(e.field, e.code, "That assignment is not allowed.")
    if CommandAppointment.objects.filter(personnel=person, ended_at__isnull=True).exists():
        raise field_error("personnel", "has_open_appointment", "End this person's command appointments before the transfer.")
    clean = {"personnel": str(person.pk), "from_unit": str(person.org_unit_id), "org_unit": str(dest.pk),
             "effective_date": _day(payload.get("effective_date"), "effective_date").isoformat(),
             "reason": str(payload.get("reason") or "")[:200]}
    summary = f"Transfer {person.full_name} ({person.service_number or 'no service number'}): {person.org_unit.name_en} -> {dest.name_en}"[:300]
    return person, dest, clean, summary


def _is_uuid(value):
    import uuid
    try:
        uuid.UUID(str(value))
        return True
    except (ValueError, AttributeError, TypeError):
        return False


# ------------------------------------------------------------------ appointment handlers
class _DryRun(Exception):
    """Raised inside a transaction so a trial run of the real rules writes nothing."""


def _person_and_unit(actor, code, payload):
    from apps.personnel.models import Personnel

    person = Personnel.objects.select_related("org_unit", "rank", "branch").filter(pk=str(payload["personnel"])).first() \
        if _is_uuid(payload.get("personnel")) else None
    if person is None or not scope.can(actor, code, unit=person.org_unit):
        raise field_error("personnel", "personnel_not_found", "That person cannot be used.")
    return person


def _authority(req_or_none, order_ref, officer, order_date):
    return f"{order_ref} ({officer}, {order_date})"[:150]


def _check_appointment_add(actor, code, payload, order=("", "", ""), dry=True):
    """Run the real appointment rules. dry=True rolls everything back (used when proposing); dry=False writes (on approval)."""
    from apps.personnel import appointments as appt_svc
    from apps.personnel.models import AppointmentType
    from apps.personnel.services import RuleError

    person = _person_and_unit(actor, code, payload)
    unit = OrganizationalUnit.objects.filter(pk=str(payload.get("org_unit") or "")).first() if _is_uuid(payload.get("org_unit")) else None
    atype = AppointmentType.objects.filter(pk=str(payload.get("appointment_type") or "")).first() if _is_uuid(payload.get("appointment_type")) else None
    if unit is None or not scope.can(actor, code, unit=unit):
        raise field_error("org_unit", "org_unit_invalid", "That unit cannot be used.")
    if atype is None:
        raise field_error("appointment_type", "appointment_type_invalid", "That appointment cannot be used.")
    start = _day(payload.get("effective_from"), "effective_from")
    end = _day(payload.get("effective_to"), "effective_to") if payload.get("effective_to") else None
    clean = {"personnel": str(person.pk), "org_unit": str(unit.pk), "appointment_type": str(atype.pk),
             "effective_from": start.isoformat(), "effective_to": end.isoformat() if end else None}
    summary = f"Appoint {person.full_name} as {atype.name_en}, {unit.name_en}"[:300]
    authority = _authority(None, *order)
    try:
        with transaction.atomic():
            appt = appt_svc.create(actor, person, unit, atype, start, end, authority)
            if dry:
                raise _DryRun()
            return appt, person, unit, atype, clean, summary
    except _DryRun:
        return None, person, unit, atype, clean, summary
    except RuleError as e:
        raise field_error(e.field, e.code, "That appointment is not allowed.")


def _check_appointment_end(actor, code, payload):
    from apps.personnel.models import CommandAppointment

    person = _person_and_unit(actor, code, payload)
    appt = CommandAppointment.objects.select_related("appointment_type", "org_unit", "role_assignment__user").filter(
        pk=str(payload.get("appointment") or ""), personnel=person).first() if _is_uuid(payload.get("appointment")) else None
    if appt is None or not scope.can(actor, code, unit=appt.org_unit):
        raise field_error("appointment", "appointment_not_found", "That appointment cannot be used.")
    if appt.ended_at is not None:
        raise field_error("appointment", "appointment_ended", "That appointment has already ended.")
    reason = str(payload.get("reason") or "").strip()[:300]
    if not reason:
        raise field_error("reason", "reason_required", "Say why the appointment ends.")
    clean = {"personnel": str(person.pk), "appointment": str(appt.pk), "reason": reason}
    summary = f"End appointment: {person.full_name} as {appt.appointment_type.name_en}, {appt.org_unit.name_en}"[:300]
    return person, appt, clean, summary


def _validate(actor, kind, payload):
    if kind == ChangeRequest.Kind.TRANSFER:
        _, dest, clean, summary = _check_transfer(actor, PROPOSE, payload)
        return dest, clean, summary
    if kind == ChangeRequest.Kind.APPOINTMENT_ADD:
        _, _, unit, _, clean, summary = _check_appointment_add(actor, PROPOSE, payload)
        return unit, clean, summary
    if kind == ChangeRequest.Kind.APPOINTMENT_END:
        _, appt, clean, summary = _check_appointment_end(actor, PROPOSE, payload)
        return appt.org_unit, clean, summary
    raise field_error("kind", "unknown_kind", "That kind of request is not supported.")


def _apply(req, actor, request):
    if req.kind in (ChangeRequest.Kind.APPOINTMENT_ADD, ChangeRequest.Kind.APPOINTMENT_END):
        return _apply_appointments(req, actor, request)
    if req.kind == ChangeRequest.Kind.TRANSFER:
        from apps.personnel.services import add_history

        p = req.payload
        person, dest, _, _ = _check_transfer(actor, APPROVE, p, expect_from=p["from_unit"])
        old_unit = person.org_unit
        reason = f"Order {req.order_ref} ({req.issuing_officer}, {req.order_date.isoformat()})"
        if p.get("reason"):
            reason += f": {p['reason']}"
        updated = versioned_update(person, {"org_unit": dest, "branch": dest.branch}, person.version)
        add_history(updated, "org_unit", str(old_unit.pk), str(dest.pk), old_unit.name_en, dest.name_en,
                    date.fromisoformat(p["effective_date"]), reason, actor)
        record("personnel.transfer", request=request, actor=actor, entity_type="personnel", entity_id=updated.pk,
               metadata={"from": str(old_unit.pk), "to": str(dest.pk), "effective_date": p["effective_date"],
                         "change_request": str(req.pk), "order_ref": req.order_ref})


# ------------------------------------------------------------------ lifecycle
def _apply_appointments(req, actor, request):
    from apps.personnel import appointments as appt_svc
    from apps.personnel.services import RuleError

    p = req.payload
    if req.kind == ChangeRequest.Kind.APPOINTMENT_ADD:
        order = (req.order_ref, req.issuing_officer, req.order_date.isoformat())
        appt, person, unit, atype, _, _ = _check_appointment_add(actor, APPROVE, p, order=order, dry=False)
        record("personnel.appointment_created", request=request, actor=actor, entity_type="personnel", entity_id=person.pk,
               metadata={"appointment": str(appt.pk), "type": atype.code, "unit": unit.code, "effective_from": p["effective_from"],
                         "access_linked": False, "change_request": str(req.pk), "order_ref": req.order_ref})
    else:
        try:
            _, appt, _, _ = _check_appointment_end(actor, APPROVE, p)
        except Exception as exc:  # the appointment ended or disappeared since the request was made
            if getattr(exc, "detail", None) is not None and "appointment" in getattr(exc, "detail", {}):
                raise StaleRequest()
            raise
        reason = f"{p['reason']} (order {req.order_ref})"[:300]
        try:
            revoked = appt_svc.end(actor, appt, reason)
        except RuleError:
            raise StaleRequest()
        record("personnel.appointment_ended", request=request, actor=actor, entity_type="personnel", entity_id=p["personnel"],
               metadata={"appointment": str(appt.pk), "access_revoked": revoked, "change_request": str(req.pk), "order_ref": req.order_ref})


def _meta(req):
    return {"kind": req.kind, "order_ref": req.order_ref, "status": req.status}


def _order_fields(order_ref, issuing_officer, order_date):
    order_ref, issuing_officer = (order_ref or "").strip(), (issuing_officer or "").strip()
    if not order_ref or len(order_ref) > 150:
        raise field_error("order_ref", "order_required", "The order reference is required.")
    if not issuing_officer or len(issuing_officer) > 150:
        raise field_error("issuing_officer", "issuing_officer_required", "The issuing officer is required.")
    order_day = _day(order_date, "order_date") if order_date else None
    if order_day is None:
        raise field_error("order_date", "order_required", "The order date is required.")
    return order_ref, issuing_officer, order_day


@transaction.atomic
def propose(actor, request, *, kind, payload, order_ref, issuing_officer, order_date):
    order_ref, issuing_officer, order_day = _order_fields(order_ref, issuing_officer, order_date)
    if not isinstance(payload, dict):
        raise field_error("payload", "invalid_payload", "Invalid.")
    unit, clean, summary = _validate(actor, kind, payload)
    req = ChangeRequest.objects.create(
        kind=kind, summary=summary, payload=clean, unit=unit, order_ref=order_ref, issuing_officer=issuing_officer,
        order_date=order_day, proposed_by=actor, proposed_by_username=actor.username)
    record("change_request.propose", request=request, entity_type="change_request", entity_id=req.pk, metadata=_meta(req))
    if scope.can(actor, APPROVE):  # the super administrator's own entry applies at once, and says so
        _decide_approve(req, actor, request, req.version, "", self_approved=True)
        req.refresh_from_db()
    return req


def _locked(req):
    return ChangeRequest.objects.select_for_update().get(pk=req.pk)


class UseBatch(APIException):
    status_code = 409
    default_detail = "This request is part of a batch. Decide the batch as a whole."
    default_code = "use_batch"


def _no_batch(req):
    if req.batch_id:
        raise UseBatch()


def _withdraw(req, actor, request, expected):
    req = _locked(req)
    if req.proposed_by_id != actor.pk:
        raise PermissionDenied("Only the proposer can withdraw a request.", code="not_proposer")
    if req.status != S.PENDING:
        raise InvalidState()
    req = versioned_update(req, {"status": S.WITHDRAWN, "decided_at": timezone.now()}, expected)
    record("change_request.withdraw", request=request, entity_type="change_request", entity_id=req.pk, metadata=_meta(req))
    return req


def _start_review(req, actor, request, expected):
    req = _locked(req)
    if req.status != S.PENDING:
        raise InvalidState()
    req = versioned_update(req, {"status": S.IN_REVIEW, "review_started_at": timezone.now()}, expected)
    record("change_request.start_review", request=request, entity_type="change_request", entity_id=req.pk, metadata=_meta(req))
    return req


def _reject(req, actor, request, expected, note):
    req = _locked(req)
    if req.status not in (S.PENDING, S.IN_REVIEW):
        raise InvalidState()
    if not (note or "").strip():
        raise field_error("note", "note_required", "Say why the request is rejected.")
    req = versioned_update(req, {"status": S.REJECTED, "decided_by": actor, "decided_by_username": actor.username,
                                 "decided_at": timezone.now(), "decision_note": note.strip()[:500]}, expected)
    record("change_request.reject", request=request, entity_type="change_request", entity_id=req.pk, metadata=_meta(req))
    return req


@transaction.atomic
def withdraw(req, actor, request, expected):
    _no_batch(req)
    return _withdraw(req, actor, request, expected)


@transaction.atomic
def start_review(req, actor, request, expected):
    _no_batch(req)
    return _start_review(req, actor, request, expected)


def _decide_approve(req, actor, request, expected, note, self_approved=False):
    req = _locked(req)
    if req.status not in (S.PENDING, S.IN_REVIEW):
        raise InvalidState()
    if req.proposed_by_id == actor.pk and not self_approved:
        record("access.denied", request=request, actor=actor, outcome="denied", entity_type="change_request",
               entity_id=req.pk, metadata={"reason": "self_approval"})
        raise PermissionDenied("You cannot approve your own request.", code="self_approval_forbidden")
    _apply(req, actor, request)
    req = versioned_update(req, {"status": S.APPROVED, "decided_by": actor, "decided_by_username": actor.username,
                                 "decided_at": timezone.now(), "decision_note": (note or "")[:500],
                                 "self_approved": self_approved}, expected)
    record("change_request.approve", request=request, actor=actor, entity_type="change_request", entity_id=req.pk,
           metadata={**_meta(req), "self_approved": self_approved})
    return req


def _deny_self_approval(request, actor, entity_id, **extra):
    """Written OUTSIDE the decision's transaction, so the denial is kept even though the decision is rolled back."""
    record("access.denied", request=request, actor=actor, outcome="denied", entity_type="change_request", entity_id=entity_id,
           metadata={"reason": "self_approval", **extra})
    raise PermissionDenied("You cannot approve your own request.", code="self_approval_forbidden")


def approve(req, actor, request, expected, note):
    _no_batch(req)
    if req.proposed_by_id == actor.pk:
        _deny_self_approval(request, actor, req.pk)
    with transaction.atomic():
        return _decide_approve(req, actor, request, expected, note)


@transaction.atomic
def reject(req, actor, request, expected, note):
    _no_batch(req)
    return _reject(req, actor, request, expected, note)


# ------------------------------------------------------------------ bulk transfer (one order, many people, decided together)
BULK_MAX = 200


class BulkInvalid(Exception):
    """Nothing was created: `rows` lists what is wrong with which row."""

    def __init__(self, rows):
        super().__init__("bulk_invalid")
        self.rows = rows


class BatchItemFailed(APIException):
    status_code = 409
    default_code = "batch_item_failed"
    default_detail = "One request in the batch can no longer be applied; nothing was changed."


def _flat(detail):
    out = []
    items = detail.items() if isinstance(detail, dict) else [("", detail)]
    for field, value in items:
        for e in (value if isinstance(value, (list, tuple)) else [value]):
            out.append({"field": field, "code": getattr(e, "code", "invalid")})
    return out


def _resolve_person(actor, item):
    from apps.personnel.models import Personnel

    if not isinstance(item, dict):
        raise field_error("personnel", "personnel_not_found", "That person cannot be used.")
    if item.get("personnel"):
        return str(item["personnel"])
    number = str(item.get("service_number") or "").strip()
    if not number:
        raise field_error("service_number", "personnel_not_found", "That person cannot be used.")
    found = [p for p in Personnel.objects.select_related("org_unit").filter(service_number__iexact=number)
             if scope.can(actor, PROPOSE, unit=p.org_unit)]
    if not found:
        raise field_error("service_number", "personnel_not_found", "That person cannot be used.")
    if len(found) > 1:
        raise field_error("service_number", "ambiguous_service_number", "More than one person has that service number.")
    return str(found[0].pk)


@transaction.atomic
def propose_bulk_transfer(actor, request, *, items, order_ref, issuing_officer, order_date, org_unit=None, effective_date=None, reason=""):
    """One Army order moving many people. Every row is checked first; if any row is wrong NOTHING is created. The requests share a
    batch id and are approved, rejected or withdrawn as a whole (a super administrator's own entry applies the whole batch at once)."""
    import uuid

    order_ref, issuing_officer, order_day = _order_fields(order_ref, issuing_officer, order_date)
    if not isinstance(items, list) or not items:
        raise field_error("items", "items_required", "Add at least one person.")
    if len(items) > BULK_MAX:
        raise field_error("items", "too_many_rows", f"At most {BULK_MAX} people at a time.")
    prepared, errors, seen = [], [], set()
    for row, item in enumerate(items, start=1):
        try:
            person_id = _resolve_person(actor, item)
            if person_id in seen:
                raise field_error("personnel", "duplicate_person", "That person appears twice.")
            seen.add(person_id)
            if ChangeRequest.objects.filter(kind=ChangeRequest.Kind.TRANSFER, status__in=(S.PENDING, S.IN_REVIEW),
                                            payload__personnel=person_id).exists():
                raise field_error("personnel", "already_pending", "A transfer for that person is already waiting for a decision.")
            payload = {"personnel": person_id, "org_unit": (item.get("org_unit") if isinstance(item, dict) else None) or org_unit,
                       "effective_date": effective_date, "reason": reason}
            _, dest, clean, summary = _check_transfer(actor, PROPOSE, payload)
            prepared.append((dest, clean, summary))
        except ValidationError as exc:
            errors.append({"row": row, "errors": _flat(exc.detail)})
    if errors:
        raise BulkInvalid(errors)
    batch = uuid.uuid4()
    created = []
    for dest, clean, summary in prepared:
        req = ChangeRequest.objects.create(
            kind=ChangeRequest.Kind.TRANSFER, summary=summary, payload=clean, unit=dest, order_ref=order_ref,
            issuing_officer=issuing_officer, order_date=order_day, proposed_by=actor, proposed_by_username=actor.username, batch_id=batch)
        record("change_request.propose", request=request, entity_type="change_request", entity_id=req.pk, metadata={**_meta(req), "batch": str(batch)})
        created.append(req)
    record("change_request.bulk_propose", request=request, entity_type="change_request", metadata={"batch": str(batch), "count": len(created), "order_ref": order_ref})
    if scope.can(actor, APPROVE):
        for req in created:
            _decide_approve(req, actor, request, req.version, "", self_approved=True)
    return list(ChangeRequest.objects.filter(batch_id=batch).order_by("created_at", "id"))


def decide_batch(actor, request, *, batch, action, expected_count, note=""):
    if action == "approve" and _is_uuid(batch) and scope.can(actor, APPROVE) and \
            ChangeRequest.objects.filter(batch_id=batch, proposed_by=actor, status__in=(S.PENDING, S.IN_REVIEW)).exists():
        _deny_self_approval(request, actor, None, batch=str(batch))
    with transaction.atomic():
        return _decide_batch(actor, request, batch=batch, action=action, expected_count=expected_count, note=note)


def _decide_batch(actor, request, *, batch, action, expected_count, note=""):
    """approve / reject / start_review (super administrator) or withdraw (the proposer) for a whole batch, atomically.
    `expected_count` is how many open requests the person was looking at; a different number means the batch changed."""
    if not _is_uuid(batch):
        raise field_error("batch", "batch_invalid", "Unknown batch.")
    if action in ("approve", "reject", "start_review"):
        if not scope.can(actor, APPROVE):
            raise PermissionDenied("You do not have permission to do that.", code="permission_denied")
    elif action == "withdraw":
        if not scope.can(actor, PROPOSE):
            raise PermissionDenied("You do not have permission to do that.", code="permission_denied")
    else:
        raise field_error("action", "unknown_action", "Unknown action.")
    reqs = list(ChangeRequest.objects.select_for_update().filter(batch_id=batch).order_by("created_at", "id"))
    allowed = (S.PENDING, S.IN_REVIEW) if action in ("approve", "reject") else (S.PENDING,)
    todo = [r for r in reqs if r.status in allowed]
    if not todo:
        raise InvalidState()
    try:
        if int(expected_count) != len(todo):
            raise StaleRequest("The batch changed. Reload and check it again.")
    except (TypeError, ValueError):
        raise field_error("count", "count_required", "Send the number of requests you reviewed.")
    for r in todo:
        try:
            if action == "approve":
                _decide_approve(r, actor, request, r.version, note)
            elif action == "reject":
                _reject(r, actor, request, r.version, note)
            elif action == "start_review":
                _start_review(r, actor, request, r.version)
            else:
                _withdraw(r, actor, request, r.version)
        except ValidationError as exc:
            code = (_flat(exc.detail) or [{"code": "invalid"}])[0]["code"]
            raise BatchItemFailed(f"{r.summary} ({code}). Nothing was changed.")
        except StaleRequest:
            raise BatchItemFailed(f"{r.summary} (stale_request). Nothing was changed.")
    record(f"change_request.batch_{action}", request=request, entity_type="change_request",
           metadata={"batch": str(batch), "count": len(todo)})
    return list(ChangeRequest.objects.filter(batch_id=batch).order_by("created_at", "id"))
