"""Vehicle registry business rules. Every multi-step change runs in one transaction on a locked row, writes an append-only
VehicleEvent and an audit event, and is only reported as successful once saved."""
import hashlib
import re
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Exists, OuterRef, Q, Subquery, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.audit.services import record
from apps.core import crypto
from apps.core.concurrency import VersionConflict
from apps.core.errors import field_error
from apps.core.middleware import get_correlation_id
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING

from .models import (MaintenanceRecord, Vehicle, VehicleArmament, VehicleCategory, VehicleCounter, VehicleDocument, VehicleEvent,
                     VehicleSpecification, VehicleStatusType)

V = Vehicle


def valid_statuses():
    """Codes a user may set: active configured statuses, except decommissioned (its own approval workflow)."""
    return set(VehicleStatusType.objects.filter(active=True).exclude(code="decommissioned").values_list("code", flat=True))


def unavailable_codes():
    return list(VehicleStatusType.objects.filter(available=False).exclude(code="decommissioned").values_list("code", flat=True))


def is_available(code):
    return not VehicleStatusType.objects.filter(code=code, available=False).exists()


CONDITIONS = {c.value for c in V.Condition}
MAINT_KINDS = {k.value for k in MaintenanceRecord.Kind}
DOC_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_DOC_BYTES = 5 * 1024 * 1024
# Status a maintenance record puts a vehicle into while it is open.
KIND_STATUS = {"service": V.Status.UNDER_MAINTENANCE, "repair": V.Status.UNDER_REPAIR, "inspection": V.Status.AWAITING_INSPECTION}


PLATE_PREFIX = {"state": "GD", "private": "PL"}  # state property -> GD---, private -> PL---
OWNERSHIPS = set(PLATE_PREFIX)


def plate_key(plate):
    key = re.sub(r"[\s\-]", "", (plate or "")).upper()
    return key or None


def _actor(request):
    u = getattr(request, "user", None)
    return u if u is not None and u.is_authenticated else None


def _text(d, name, limit, required=False):
    v = d.get(name)
    v = "" if v is None else str(v).strip()
    if required and not v:
        raise field_error(name, "required", "This field is required.")
    if len(v) > limit:
        raise field_error(name, "too_long", "Too long.")
    return v


def _date(value, name, required=False):
    if value in (None, ""):
        if required:
            raise field_error(name, "required", "This field is required.")
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise field_error(name, "invalid_date", "Use YYYY-MM-DD.")


def effective_unit(vehicle):
    return vehicle.org_unit


def snapshot(v):
    return {"org_unit": str(v.org_unit_id), "driver": str(v.driver_id) if v.driver_id else None,
            "custodian": str(v.custodian_id) if v.custodian_id else None, "location": v.location, "status": v.status,
            "condition": v.condition, "plate": v.plate, "plate_status": v.plate_status, "ownership": v.ownership, "category": str(v.category_id),
            "reference_model": v.reference_model.code if v.reference_model_id else None,
            "vehicle_type": v.vehicle_type, "make": v.make, "model": v.model, "year": v.year, "notes": v.notes}


def _event(request, vehicle, kind, before=None, after=None, reason="", authority_ref="", effective_date=None):
    actor = _actor(request)
    ev = VehicleEvent.objects.create(
        vehicle=vehicle, kind=kind, before=before or {}, after=after or {}, reason=reason, authority_ref=authority_ref,
        effective_date=effective_date, actor_id=getattr(actor, "pk", None), actor_username=getattr(actor, "username", "") or "",
        correlation_id=get_correlation_id() or "")
    record(f"vehicle.{kind}", request=request, entity_type="vehicle", entity_id=vehicle.pk,
           metadata={"vehicle_id": vehicle.vehicle_id, "before": before or {}, "after": after or {}, "authority_ref": authority_ref})
    return ev


def _next_vehicle_id():
    counter, _ = VehicleCounter.objects.select_for_update().get_or_create(name="vehicle")
    counter.last += 1
    counter.save(update_fields=["last"])
    return f"VEH-{counter.last:06d}"


def _lock(vehicle_pk, expected_version):
    v = V.objects.select_for_update().get(pk=vehicle_pk)
    if v.version != expected_version:
        raise VersionConflict()
    return v


def _save(v, **changes):
    for k, val in changes.items():
        setattr(v, k, val)
    v.version += 1
    v.save()
    return v


def category_by(value):
    try:
        cat = VehicleCategory.objects.filter(pk=value, active=True).first()
    except (ValueError, TypeError, Exception):
        cat = None
    if cat is None and value:
        cat = VehicleCategory.objects.filter(code=str(value), active=True).first()
    if cat is None:
        raise field_error("category", "category_unknown", "Unknown or inactive vehicle category.")
    return cat


def reference_model_by(value):
    """Catalogue entry (a vehicle model) by id or code. Empty means none. Never guessed from make/model text."""
    if value in (None, ""):
        return None
    from apps.equipment.models import EquipmentItem
    item = EquipmentItem.objects.filter(code=str(value).lower(), active=True, kind="vehicle_model").first()
    if item is None:
        try:
            item = EquipmentItem.objects.filter(pk=value, active=True, kind="vehicle_model").first()
        except Exception:
            item = None
    if item is None:
        raise field_error("reference_model", "reference_unknown", "Unknown or inactive catalogue model.")
    return item


def _person(value, field, user, perm_unit_check):
    """Resolve a Personnel reference; must exist, be serving, and be inside the actor's reach (else it reads as unknown)."""
    if value in (None, ""):
        return None
    try:
        p = Personnel.objects.select_related("org_unit").filter(pk=value).first()
    except Exception:
        p = None
    if p is None or not perm_unit_check(p.org_unit):
        raise field_error(field, "person_unknown", "Unknown person.")
    if p.status in NOT_SERVING:
        raise field_error(field, "person_not_serving", "That person is not serving.")
    return p


def _ownership(value, default=V.Ownership.STATE):
    value = default if value in (None, "") else value
    if value not in OWNERSHIPS:
        raise field_error("ownership", "invalid_ownership", "Choose state property or private.")
    return value


def _plate(plate, plate_status, ownership=V.Ownership.STATE):
    plate = (plate or "").strip()
    if plate_status not in {c.value for c in V.PlateStatus}:
        plate_status = V.PlateStatus.REGISTERED if plate else V.PlateStatus.UNKNOWN
    if plate_status == V.PlateStatus.REGISTERED and not plate_key(plate):
        raise field_error("plate", "required", "Give the plate, or mark the plate as none/unknown.")
    if plate_status != V.PlateStatus.REGISTERED:
        plate = ""
    else:
        prefix = PLATE_PREFIX[ownership]
        plate = plate.upper()
        if not plate_key(plate).startswith(prefix):
            raise field_error("plate", "plate_prefix", f"A {'state property' if ownership == 'state' else 'private'} vehicle plate must start with {prefix} (for example {prefix}-123).")
    return plate, plate_key(plate), plate_status


def _year(d):
    y = d.get("year")
    if y in (None, ""):
        return None
    if not isinstance(y, int) or isinstance(y, bool) or not 1900 <= y <= date.today().year + 1:
        raise field_error("year", "invalid_year", "Invalid year.")
    return y


@transaction.atomic
def register(request, d, unit, can_reach):
    ref = reference_model_by(d.get("reference_model"))
    if ref is not None and not d.get("category") and ref.vehicle_category_id:
        d = {**d, "category": ref.vehicle_category.code}  # the model's own classification is the default, never overriding a chosen one
    cat = category_by(d.get("category"))
    ownership = _ownership(d.get("ownership"))
    plate, key, pstatus = _plate(d.get("plate"), d.get("plate_status"), ownership)
    status = d.get("status") or V.Status.OPERATIONAL
    if status not in valid_statuses():
        raise field_error("status", "invalid_status", "Invalid status.")
    condition = d.get("condition") or V.Condition.UNKNOWN
    if condition not in CONDITIONS:
        raise field_error("condition", "invalid_condition", "Invalid condition.")
    driver = _person(d.get("driver"), "driver", request.user, can_reach)
    custodian = _person(d.get("custodian"), "custodian", request.user, can_reach)
    if key and V.objects.filter(plate_key=key).exists():
        raise field_error("plate", "plate_in_use", "Another vehicle already has this plate.")
    if driver and V.objects.filter(driver=driver).exists():
        raise field_error("driver", "driver_already_assigned", "That driver is already assigned to another vehicle.")
    try:
        with transaction.atomic():
            v = V.objects.create(
                vehicle_id=_next_vehicle_id(), plate=plate, plate_key=key, plate_status=pstatus, ownership=ownership, category=cat,
                reference_model=ref, vehicle_type=_text(d, "vehicle_type", 60), make=_text(d, "make", 60), model=_text(d, "model", 60), year=_year(d),
                org_unit=unit, driver=driver, custodian=custodian, location=_text(d, "location", 200), status=status,
                condition=condition, acquired_on=_date(d.get("acquired_on"), "acquired_on"),
                acquisition_ref=_text(d, "acquisition_ref", 150), notes=_text(d, "notes", 1000),
                created_by_username=getattr(_actor(request), "username", ""))
    except IntegrityError:
        raise field_error("plate", "conflict", "That plate or driver is already in use.")
    _event(request, v, VehicleEvent.Kind.REGISTERED, after=snapshot(v), authority_ref=_text(d, "authority_ref", 150))
    return v


EDITABLE_TEXT = {"vehicle_type": 60, "make": 60, "model": 60, "notes": 1000, "acquisition_ref": 150}


@transaction.atomic
def edit_details(request, vehicle, d, version):
    """Descriptive fields only. Unit, driver, custodian, location and status have their own audited operations."""
    v = _lock(vehicle.pk, version)
    if v.status == V.Status.DECOMMISSIONED:
        raise field_error("status", "decommissioned", "A decommissioned vehicle is read-only.")
    before = snapshot(v)
    changes = {k: _text(d, k, n) for k, n in EDITABLE_TEXT.items() if k in d}
    if "category" in d:
        changes["category"] = category_by(d["category"])
    if "reference_model" in d:
        changes["reference_model"] = reference_model_by(d["reference_model"])
    if "year" in d:
        changes["year"] = _year(d)
    if "acquired_on" in d:
        changes["acquired_on"] = _date(d["acquired_on"], "acquired_on")
    if "condition" in d:
        if d["condition"] not in CONDITIONS:
            raise field_error("condition", "invalid_condition", "Invalid condition.")
        changes["condition"] = d["condition"]
    ownership = _ownership(d.get("ownership"), default=v.ownership)
    if "ownership" in d:
        changes["ownership"] = ownership
    # Re-check the plate whenever the plate, its status or the ownership changes, so the GD/PL prefix always matches.
    if "plate" in d or "plate_status" in d or ownership != v.ownership:
        # Only an ownership change keeps the stored plate status; a new plate with no status given counts as registered (as before).
        pstatus_in = d.get("plate_status") or (v.plate_status if "plate" not in d and "plate_status" not in d else None)
        plate, key, pstatus = _plate(d.get("plate", v.plate), pstatus_in, ownership)
        if key and V.objects.filter(plate_key=key).exclude(pk=v.pk).exists():
            raise field_error("plate", "plate_in_use", "Another vehicle already has this plate.")
        changes.update(plate=plate, plate_key=key, plate_status=pstatus)
    if not changes:
        raise field_error("body", "nothing_to_change", "Nothing to change.")
    try:
        with transaction.atomic():
            _save(v, **changes)
    except IntegrityError:
        raise field_error("plate", "plate_in_use", "Another vehicle already has this plate.")
    _event(request, v, VehicleEvent.Kind.UPDATED, before=before, after=snapshot(v), reason=_text(d, "reason", 300))
    return v


@transaction.atomic
def transfer(request, vehicle, to_unit, d, version):
    v = _lock(vehicle.pk, version)
    if v.status == V.Status.DECOMMISSIONED:
        raise field_error("status", "decommissioned", "A decommissioned vehicle cannot be transferred.")
    if to_unit.pk == v.org_unit_id:
        raise field_error("org_unit", "same_unit", "The vehicle is already assigned to that unit.")
    authority = _text(d, "authority_ref", 150, required=True)
    before = snapshot(v)
    # A transfer ends the old unit's driver and custodian assignments: they belong to the previous unit.
    _save(v, org_unit=to_unit, driver=None, custodian=None)
    _event(request, v, VehicleEvent.Kind.UNIT_TRANSFER, before=before, after=snapshot(v), reason=_text(d, "reason", 300),
           authority_ref=authority, effective_date=_date(d.get("effective_date"), "effective_date") or timezone.localdate())
    return v


@transaction.atomic
def assign_driver(request, vehicle, d, version, can_reach):
    v = _lock(vehicle.pk, version)
    if v.status == V.Status.DECOMMISSIONED:
        raise field_error("status", "decommissioned", "A decommissioned vehicle is read-only.")
    driver = _person(d.get("driver"), "driver", request.user, can_reach)
    if driver is not None:
        other = V.objects.filter(driver=driver).exclude(pk=v.pk).first()
        if other:
            raise field_error("driver", "driver_already_assigned", f"That driver is already assigned to {other.vehicle_id}.")
    if (driver.pk if driver else None) == v.driver_id:
        raise field_error("driver", "unchanged", "No change.")
    before = snapshot(v)
    try:
        with transaction.atomic():
            _save(v, driver=driver)
    except IntegrityError:
        raise field_error("driver", "driver_already_assigned", "That driver is already assigned to another vehicle.")
    _event(request, v, VehicleEvent.Kind.DRIVER_CHANGE, before=before, after=snapshot(v), reason=_text(d, "reason", 300),
           authority_ref=_text(d, "authority_ref", 150), effective_date=_date(d.get("effective_date"), "effective_date") or timezone.localdate())
    return v


@transaction.atomic
def assign_custodian(request, vehicle, d, version, can_reach):
    v = _lock(vehicle.pk, version)
    if v.status == V.Status.DECOMMISSIONED:
        raise field_error("status", "decommissioned", "A decommissioned vehicle is read-only.")
    cust = _person(d.get("custodian"), "custodian", request.user, can_reach)
    if (cust.pk if cust else None) == v.custodian_id:
        raise field_error("custodian", "unchanged", "No change.")
    before = snapshot(v)
    _save(v, custodian=cust)
    _event(request, v, VehicleEvent.Kind.CUSTODIAN_CHANGE, before=before, after=snapshot(v), reason=_text(d, "reason", 300),
           authority_ref=_text(d, "authority_ref", 150), effective_date=_date(d.get("effective_date"), "effective_date") or timezone.localdate())
    return v


@transaction.atomic
def set_location(request, vehicle, d, version):
    v = _lock(vehicle.pk, version)
    if v.status == V.Status.DECOMMISSIONED:
        raise field_error("status", "decommissioned", "A decommissioned vehicle is read-only.")
    loc = _text(d, "location", 200, required=True)
    if loc == v.location:
        raise field_error("location", "unchanged", "No change.")
    before = snapshot(v)
    _save(v, location=loc)
    _event(request, v, VehicleEvent.Kind.LOCATION_CHANGE, before=before, after=snapshot(v), reason=_text(d, "reason", 300))
    return v


@transaction.atomic
def change_status(request, vehicle, d, version):
    v = _lock(vehicle.pk, version)
    to = d.get("status")
    if to not in valid_statuses():
        raise field_error("status", "invalid_status", "Invalid status. Decommissioning has its own approval workflow.")
    if v.status == V.Status.DECOMMISSIONED:
        raise field_error("status", "decommissioned", "A decommissioned vehicle is read-only.")
    if to == v.status:
        raise field_error("status", "unchanged", "No change.")
    reason = _text(d, "reason", 300, required=True)
    if is_available(to) and v.maintenance.filter(state="open").exists():
        raise field_error("status", "open_maintenance", "Close the open maintenance record before returning the vehicle to service.")
    before = snapshot(v)
    changes = {"status": to}
    if "condition" in d:
        if d["condition"] not in CONDITIONS:
            raise field_error("condition", "invalid_condition", "Invalid condition.")
        changes["condition"] = d["condition"]
    _save(v, **changes)
    _event(request, v, VehicleEvent.Kind.STATUS_CHANGE, before=before, after=snapshot(v), reason=reason,
           authority_ref=_text(d, "authority_ref", 150))
    return v


# ---- maintenance -----------------------------------------------------------------------------------------------------------
@transaction.atomic
def add_maintenance(request, vehicle, d, version, can_cost):
    v = _lock(vehicle.pk, version)
    if v.status == V.Status.DECOMMISSIONED:
        raise field_error("status", "decommissioned", "A decommissioned vehicle is read-only.")
    kind = d.get("kind")
    if kind not in MAINT_KINDS:
        raise field_error("kind", "invalid_kind", "Invalid kind.")
    state = d.get("state") or "open"
    if state not in {"open", "completed"}:
        raise field_error("state", "invalid_state", "Invalid state.")
    cost = d.get("cost")
    if cost not in (None, ""):
        if not can_cost:
            raise field_error("cost", "not_permitted", "You may not record costs.")
        try:
            cost = round(float(cost), 2)
        except (TypeError, ValueError):
            raise field_error("cost", "invalid_cost", "Invalid cost.")
        if cost < 0:
            raise field_error("cost", "invalid_cost", "Invalid cost.")
    else:
        cost = None
    performed_on = _date(d.get("performed_on"), "performed_on", required=True)
    next_due = _date(d.get("next_due_date"), "next_due_date")
    if next_due and next_due < performed_on:
        raise field_error("next_due_date", "before_service", "The next due date cannot be before the service date.")
    m = MaintenanceRecord.objects.create(
        vehicle=v, kind=kind, state=state, performed_on=performed_on, reported_issue=_text(d, "reported_issue", 500),
        work_performed=_text(d, "work_performed", 1000), workshop=_text(d, "workshop", 150), next_due_date=next_due,
        cost=cost, currency=_text(d, "currency", 3).upper() if cost is not None else "", reference=_text(d, "reference", 150),
        created_by_username=getattr(_actor(request), "username", ""))
    before = snapshot(v)
    if state == "open":
        _save(v, status=KIND_STATUS[kind])  # a vehicle with an open workshop job is not available for normal use
    else:
        _save(v)  # bump the version so concurrent edits notice
    _event(request, v, VehicleEvent.Kind.MAINTENANCE, before=before, after={**snapshot(v), "maintenance": str(m.pk), "kind": kind, "state": state},
           reason=m.reported_issue[:300], authority_ref=m.reference)
    return v, m


@transaction.atomic
def complete_maintenance(request, maintenance, d, version, can_cost):
    m = MaintenanceRecord.objects.select_for_update().select_related("vehicle").get(pk=maintenance.pk)
    if m.version != version:
        raise VersionConflict()
    if m.state == "completed":
        raise field_error("state", "already_completed", "This record is already completed.")
    v = V.objects.select_for_update().get(pk=m.vehicle_id)
    work = _text(d, "work_performed", 1000) or m.work_performed
    if not work:
        raise field_error("work_performed", "required", "Describe the work performed.")
    next_due = _date(d.get("next_due_date"), "next_due_date") if "next_due_date" in d else m.next_due_date
    if next_due and next_due < m.performed_on:
        raise field_error("next_due_date", "before_service", "The next due date cannot be before the service date.")
    cost = m.cost
    if d.get("cost") not in (None, ""):
        if not can_cost:
            raise field_error("cost", "not_permitted", "You may not record costs.")
        try:
            cost = round(float(d["cost"]), 2)
        except (TypeError, ValueError):
            raise field_error("cost", "invalid_cost", "Invalid cost.")
        if cost < 0:
            raise field_error("cost", "invalid_cost", "Invalid cost.")
    m.state, m.work_performed, m.next_due_date, m.cost, m.version = "completed", work, next_due, cost, m.version + 1
    if cost is not None and not m.currency:
        m.currency = _text(d, "currency", 3).upper()
    m.save()
    before = snapshot(v)
    still_open = v.maintenance.filter(state="open").exists()
    if not still_open and v.status in (V.Status.UNDER_MAINTENANCE, V.Status.UNDER_REPAIR, V.Status.AWAITING_INSPECTION):
        _save(v, status=V.Status.OPERATIONAL if d.get("return_to_service", True) else v.status)
    else:
        _save(v)
    _event(request, v, VehicleEvent.Kind.MAINTENANCE, before=before, after={**snapshot(v), "maintenance": str(m.pk), "state": "completed"},
           reason=work[:300], authority_ref=m.reference)
    return v, m


# ---- decommissioning (controlled) -------------------------------------------------------------------------------------------
@transaction.atomic
def propose_disposal(request, vehicle, d, version):
    v = _lock(vehicle.pk, version)
    if v.status == V.Status.DECOMMISSIONED:
        raise field_error("status", "decommissioned", "Already decommissioned.")
    if v.disposal_requested_at:
        raise field_error("status", "disposal_pending", "A disposal request is already waiting for approval.")
    reason = _text(d, "reason", 300, required=True)
    authority = _text(d, "authority_ref", 150, required=True)
    before = snapshot(v)
    _save(v, disposal_requested_at=timezone.now(), disposal_requested_by=request.user.username, disposal_reason=reason,
          disposal_authority_ref=authority)
    _event(request, v, VehicleEvent.Kind.DISPOSAL_PROPOSED, before=before, after=snapshot(v), reason=reason, authority_ref=authority)
    return v


@transaction.atomic
def decide_disposal(request, vehicle, d, version, approve):
    v = _lock(vehicle.pk, version)
    if not v.disposal_requested_at:
        raise field_error("status", "no_disposal_request", "There is no disposal request to decide.")
    if v.disposal_requested_by == request.user.username:
        raise field_error("status", "self_approval", "A different authorised user must decide a disposal request.")
    before = snapshot(v)
    if approve:
        _save(v, status=V.Status.DECOMMISSIONED, decommissioned_at=timezone.now(), decommissioned_by=request.user.username,
              driver=None, custodian=None)
        _event(request, v, VehicleEvent.Kind.DECOMMISSIONED, before=before, after=snapshot(v), reason=v.disposal_reason,
               authority_ref=_text(d, "authority_ref", 150) or v.disposal_authority_ref)
    else:
        note = _text(d, "reason", 300, required=True)
        _save(v, disposal_requested_at=None, disposal_requested_by="", disposal_reason="", disposal_authority_ref="")
        _event(request, v, VehicleEvent.Kind.DISPOSAL_REJECTED, before=before, after=snapshot(v), reason=note)
    return v


# ---- documents --------------------------------------------------------------------------------------------------------------
@transaction.atomic
def add_document(request, vehicle, category, title, upload, maintenance=None):
    if category not in {c.value for c in VehicleDocument.Category}:
        raise field_error("category", "invalid_category", "Invalid category.")
    title = (title or "").strip()
    if not title or len(title) > 150:
        raise field_error("title", "required", "Give the document a title (150 characters at most).")
    if upload is None:
        raise field_error("file", "required", "Choose a file.")
    data = upload.read(MAX_DOC_BYTES + 1)
    if len(data) > MAX_DOC_BYTES:
        raise field_error("file", "too_large", "The file is larger than 5 MB.")
    head = data[:8]
    ctype = ("application/pdf" if head.startswith(b"%PDF") else "image/png" if head.startswith(b"\x89PNG") else
             "image/jpeg" if head[:3] == b"\xff\xd8\xff" else None)  # by content, never by the client-supplied name or type
    if ctype is None:
        raise field_error("file", "unsupported_type", "Only PDF, JPEG or PNG files are accepted.")
    if category == "photograph" and ctype == "application/pdf":
        raise field_error("file", "unsupported_type", "A photograph must be a JPEG or PNG image.")
    doc = VehicleDocument.objects.create(
        vehicle=vehicle, maintenance=maintenance, category=category, title=title, content_enc=crypto.encrypt_bytes(data),
        content_type=ctype, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
        uploaded_by_username=getattr(_actor(request), "username", ""))
    _event(request, vehicle, VehicleEvent.Kind.DOCUMENT, after={"document": str(doc.pk), "category": category, "title": title, "action": "added"})
    return doc


@transaction.atomic
def withdraw_document(request, doc, reason):
    if doc.withdrawn_at:
        raise field_error("document", "already_withdrawn", "Already withdrawn.")
    if not (reason or "").strip():
        raise field_error("reason", "required", "Give a reason.")
    doc.withdrawn_at, doc.withdrawn_by_username, doc.withdrawn_reason = timezone.now(), request.user.username, reason.strip()[:300]
    doc.save(update_fields=["withdrawn_at", "withdrawn_by_username", "withdrawn_reason"])
    _event(request, doc.vehicle, VehicleEvent.Kind.DOCUMENT, after={"document": str(doc.pk), "action": "withdrawn"}, reason=doc.withdrawn_reason)
    return doc


# ---- specifications and mounted armament ---------------------------------------------------------------------------------------
MAX_SPECS = 40


@transaction.atomic
def set_specifications(request, vehicle, d, version):
    v = _lock(vehicle.pk, version)
    if v.status == V.Status.DECOMMISSIONED:
        raise field_error("status", "decommissioned", "A decommissioned vehicle is read-only.")
    rows = d.get("specs")
    if not isinstance(rows, list) or len(rows) > MAX_SPECS:
        raise field_error("specs", "invalid", f"Send a list of at most {MAX_SPECS} specification lines.")
    clean = []
    for n, r in enumerate(rows):
        r = r if isinstance(r, dict) else {}
        clean.append({"name": _text(r, "name", 60, required=True), "value": _text(r, "value", 200, required=True), "unit": _text(r, "unit", 20), "sort_order": n})
    before = [{"name": s.name, "value": s.value, "unit": s.unit} for s in v.specs.all()]
    if before == [{k: c[k] for k in ("name", "value", "unit")} for c in clean]:
        raise field_error("specs", "unchanged", "No change.")
    v.specs.all().delete()
    VehicleSpecification.objects.bulk_create([VehicleSpecification(vehicle=v, **c) for c in clean])
    _save(v)
    _event(request, v, VehicleEvent.Kind.SPECIFICATION, before={"specs": before}, after={"specs": clean}, reason=_text(d, "reason", 300))
    return v


@transaction.atomic
def add_armament(request, vehicle, d, version, can_see_weapon):
    """Record a weapon mounted on or built into the vehicle: a catalogue entry (what it is) and optionally the weapon-register serial."""
    from apps.equipment.models import EquipmentItem
    from apps.logistics.models import Asset
    v = _lock(vehicle.pk, version)
    if v.status == V.Status.DECOMMISSIONED:
        raise field_error("status", "decommissioned", "A decommissioned vehicle is read-only.")
    key = d.get("reference_item")
    item = EquipmentItem.objects.filter(code=str(key).lower(), active=True, kind="mounted_weapon").first() if key else None
    if item is None and key:
        try:
            item = EquipmentItem.objects.filter(pk=key, active=True, kind="mounted_weapon").first()
        except Exception:
            item = None
    if item is None:
        raise field_error("reference_item", "reference_unknown", "Choose a mounted weapon from the catalogue.")
    asset = None
    serial = _text(d, "serial", 64)
    if serial:  # a serial must already exist in the weapon register, inside the caller's reach; it is never created here
        asset = Asset.objects.select_related("org_unit", "category").filter(identifier=serial, category__code__startswith="weapon").first()
        if asset is None or not can_see_weapon(asset.org_unit):
            raise field_error("serial", "serial_unknown", "That serial is not in the weapon register for your units.")
        if VehicleArmament.objects.filter(asset=asset, removed_at__isnull=True).exists():
            raise field_error("serial", "already_mounted", "That weapon is already recorded on a vehicle.")
    m = VehicleArmament.objects.create(vehicle=v, reference_item=item, asset=asset, mount_position=_text(d, "mount_position", 80),
                                       notes=_text(d, "notes", 300), added_by_username=getattr(_actor(request), "username", ""))
    _save(v)
    _event(request, v, VehicleEvent.Kind.ARMAMENT, after={"action": "added", "armament": str(m.pk), "item": item.code, "serial": serial or None,
                                                         "mount_position": m.mount_position})
    return v, m


@transaction.atomic
def remove_armament(request, vehicle, mount, d, version):
    v = _lock(vehicle.pk, version)
    if v.status == V.Status.DECOMMISSIONED:
        raise field_error("status", "decommissioned", "A decommissioned vehicle is read-only.")
    if mount.removed_at:
        raise field_error("armament", "already_removed", "Already removed.")
    reason = _text(d, "reason", 300, required=True)
    mount.removed_at, mount.removed_by_username, mount.removed_reason = timezone.now(), getattr(_actor(request), "username", ""), reason
    mount.save(update_fields=["removed_at", "removed_by_username", "removed_reason"])
    _save(v)
    _event(request, v, VehicleEvent.Kind.ARMAMENT, after={"action": "removed", "armament": str(mount.pk), "item": mount.reference_item.code}, reason=reason)
    return v


# ---- derived figures --------------------------------------------------------------------------------------------------------
def with_due(qs):
    """Annotate each vehicle with its latest recorded next-due date, so overdue is derived from maintenance records."""
    latest = (MaintenanceRecord.objects.filter(vehicle=OuterRef("pk"), next_due_date__isnull=False)
              .order_by("-performed_on", "-created_at").values("next_due_date")[:1])
    return qs.annotate(next_due=Subquery(latest))


def overdue_q(today=None):
    return Q(next_due__lt=today or timezone.localdate()) & ~Q(status=V.Status.DECOMMISSIONED)


def fleet_summary(qs, unit):
    """Totals for `unit` computed from vehicle rows only. A vehicle has exactly one current unit, so direct and subordinate
    figures are disjoint and the combined total counts each vehicle once. Decommissioned vehicles are reported separately and
    never counted in the active fleet."""
    base = with_due(qs.filter(org_unit__path__startswith=unit.path))
    active = base.exclude(status=V.Status.DECOMMISSIONED)
    direct = active.filter(org_unit=unit)
    below = active.exclude(org_unit=unit)

    def tally(q):
        by_cat = list(q.values("category__code", "category__name_en", "category__name_so").annotate(n=Count("pk")).order_by("category__sort_order", "category__code"))
        by_status = dict(q.values_list("status").annotate(n=Count("pk")))
        return {"total": q.count(),
                "by_category": [{"code": r["category__code"], "name_en": r["category__name_en"], "name_so": r["category__name_so"], "count": r["n"]} for r in by_cat],
                "by_status": by_status,
                "without_driver": q.filter(driver__isnull=True).count(),
                "without_custodian": q.filter(custodian__isnull=True).count(),
                "overdue_maintenance": q.filter(overdue_q()).count(),
                "unavailable": q.filter(status__in=unavailable_codes()).count()}

    children = []
    for child in OrganizationalUnit.objects.filter(parent=unit).order_by("path"):
        cq = active.filter(org_unit__path__startswith=child.path)
        children.append({"unit": {"id": str(child.pk), "code": child.code, "name_en": child.name_en, "name_so": child.name_so},
                         "total": cq.count(), "direct": cq.filter(org_unit=child).count()})
    return {"unit": {"id": str(unit.pk), "code": unit.code, "name_en": unit.name_en, "name_so": unit.name_so},
            "total": active.count(), "direct": tally(direct), "subordinate": tally(below), "combined": tally(active),
            "by_child_unit": children, "decommissioned": base.filter(status=V.Status.DECOMMISSIONED).count()}


INSPECTION_WINDOW_DAYS = 30


def fleet_analytics(qs, cost_q=None, today=None):
    """Fleet-wide figures for the vehicles in `qs` (already narrowed to the caller's scope and any chosen unit). Everything is derived
    from vehicle and maintenance rows with a fixed number of grouped queries, whatever the size of the fleet. Maintenance
    expenditure is included only when `cost_q` is given (the caller holds `vehicles.cost` for some units) and counts only the
    maintenance rows of vehicles in units where that permission applies. Decommissioned vehicles are reported apart and never
    counted in the active fleet."""
    today = today or timezone.localdate()
    soon = today + timedelta(days=INSPECTION_WINDOW_DAYS)
    base = with_due(qs)
    active = base.exclude(status=V.Status.DECOMMISSIONED)
    unavailable = unavailable_codes()
    agg = active.aggregate(
        total=Count("pk"),
        under_maintenance=Count("pk", filter=Q(status__in=[V.Status.UNDER_MAINTENANCE, V.Status.UNDER_REPAIR])),
        awaiting_inspection=Count("pk", filter=Q(status=V.Status.AWAITING_INSPECTION)),
        requiring_inspection=Count("pk", filter=Q(status=V.Status.AWAITING_INSPECTION) | Q(next_due__lte=soon)),
        overdue=Count("pk", filter=Q(next_due__lt=today)),
        unavailable=Count("pk", filter=Q(status__in=unavailable)),
        without_driver=Count("pk", filter=Q(driver__isnull=True)),
    )
    total = agg["total"] or 0
    by_group = dict(active.values_list("category__group").annotate(n=Count("pk")))
    by_condition = dict(active.values_list("condition").annotate(n=Count("pk")))
    by_cat = [{"code": r["category__code"], "name_en": r["category__name_en"], "name_so": r["category__name_so"], "group": r["category__group"], "count": r["n"]}
              for r in active.values("category__code", "category__name_en", "category__name_so", "category__group")
              .annotate(n=Count("pk")).order_by("category__sort_order", "category__code")]
    by_model = [{"code": r["reference_model__code"], "name": r["reference_model__name"], "count": r["n"]}
                for r in active.filter(reference_model__isnull=False).values("reference_model__code", "reference_model__name")
                .annotate(n=Count("pk")).order_by("-n", "reference_model__name")]
    out = {
        "by_model": by_model, "without_reference_model": active.filter(reference_model__isnull=True).count(),
        "total": total, "decommissioned": base.filter(status=V.Status.DECOMMISSIONED).count(),
        "by_group": [{"code": g.value, "count": by_group.get(g.value, 0)} for g in VehicleCategory.Group],
        "by_category": by_cat,
        "by_condition": {c.value: by_condition.get(c.value, 0) for c in V.Condition},
        "by_status": dict(active.values_list("status").annotate(n=Count("pk"))),
        "under_maintenance": agg["under_maintenance"], "awaiting_inspection": agg["awaiting_inspection"],
        "requiring_inspection": agg["requiring_inspection"], "overdue_maintenance": agg["overdue"],
        "available": total - agg["unavailable"], "unavailable": agg["unavailable"],
        "available_pct": round(100 * (total - agg["unavailable"]) / total, 1) if total else None,
        "without_driver": agg["without_driver"], "inspection_window_days": INSPECTION_WINDOW_DAYS,
        "expenditure": {"visible": cost_q is not None, "by_currency": []},
    }
    if cost_q is not None:
        recs = MaintenanceRecord.objects.filter(cost_q, cost__isnull=False, vehicle__in=qs.values("pk"))
        start = today.replace(day=1) - timedelta(days=330)
        totals = {r["currency"]: r for r in recs.values("currency").annotate(
            total=Sum("cost"), repair=Sum("cost", filter=Q(kind="repair")), service=Sum("cost", filter=Q(kind="service")),
            inspection=Sum("cost", filter=Q(kind="inspection")))}
        months = {}
        for r in (recs.filter(performed_on__gte=start).annotate(m=TruncMonth("performed_on")).values("currency", "m")
                  .annotate(total=Sum("cost")).order_by("m")):
            months.setdefault(r["currency"], []).append({"month": r["m"].strftime("%Y-%m"), "total": float(r["total"] or 0)})
        out["expenditure"]["by_currency"] = [
            {"currency": cur or "", "total": float(r["total"] or 0), "repair": float(r["repair"] or 0), "service": float(r["service"] or 0),
             "inspection": float(r["inspection"] or 0), "by_month": months.get(cur, [])}
            for cur, r in sorted(totals.items(), key=lambda kv: kv[0] or "")]
    return out
