"""Detention register: business rules and API. Rows are closed with an outcome or voided with a reason, never deleted. Every write is
audited and also appended to the person's custody log (DetentionEvent). Access: detention.view to read, detention.manage to book in,
log events, release/transfer and void, both narrowed to the caller's unit scope (an out-of-scope record answers 404)."""
from datetime import date, timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import JSONParser
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record, record_read
from apps.core.concurrency import VersionConflict, require_version
from apps.core.errors import field_error
from apps.core.params import json_body
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel
from apps.personnel.services import NOT_SERVING
from apps.vehicles.views import _person_brief, _uid, _unit_brief

from .models import CustodyCell, CustodyFacility, DetentionCounter, DetentionEvent, DetentionRecord, id_key

R = DetentionRecord
E = DetentionEvent
MANUAL_EVENT_KINDS = ("welfare", "medical", "visit", "cell_move", "property", "statement", "note", "review")
EDITABLE = {"detainee_name": 200, "detainee_alias": 200, "id_ref": 80, "address": 200, "arrest_place": 200, "arresting_officer_name": 200,
            "reason": 300, "authority_ref": 150, "property_held": 500, "health_note": 300}  # the cell changes only through a logged cell move


class _Page(PageNumberPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"


# ---- helpers ---------------------------------------------------------------------------------------------------------------
def _text(d, name, limit, required=False):
    v = d.get(name)
    v = "" if v is None else str(v).strip()
    if required and not v:
        raise field_error(name, "required", "This field is required.")
    if len(v) > limit:
        raise field_error(name, "too_long", "Too long.")
    return v


def _when(value, name, default=None):
    if value in (None, ""):
        return default
    dt = parse_datetime(str(value))
    if dt is None:
        raise field_error(name, "invalid_datetime", "Use a date and time such as 2026-11-16T08:30.")
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def _day(value, name):
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise field_error(name, "invalid_date", "Use YYYY-MM-DD.")


def _not_future(dt, name):
    if dt > timezone.now() + timedelta(minutes=5):
        raise field_error(name, "future", "This cannot be in the future.")
    return dt


def _actor(request):
    return getattr(getattr(request, "user", None), "username", "") or ""


def review_hours():
    return int(getattr(settings, "DETENTION_REVIEW_HOURS", 48))


def held_hours(r, now=None):
    end = r.ended_at or (now or timezone.now())
    return max(int((end - r.booked_at).total_seconds() // 3600), 0)


def review_base(r):
    """The review clock restarts at the latest custody review (or the booking, if there has been none)."""
    return max(r.booked_at, r.last_review_at) if r.last_review_at else r.booked_at


def hours_since_review(r, now=None):
    return max(int(((now or timezone.now()) - review_base(r)).total_seconds() // 3600), 0)


def is_overdue(r, now=None):
    return r.status == R.Status.IN_CUSTODY and hours_since_review(r, now) >= review_hours()


def overdue_q(now=None):
    """Rows in custody whose last review (or booking) is at least DETENTION_REVIEW_HOURS old."""
    cut = (now or timezone.now()) - timedelta(hours=review_hours())
    return Q(status="in_custody") & ((Q(last_review_at__isnull=True) & Q(booked_at__lte=cut)) | Q(last_review_at__lte=cut))


def _next_number():
    c, _ = DetentionCounter.objects.select_for_update().get_or_create(name="detention")
    c.last += 1
    c.save(update_fields=["last"])
    return f"DET-{c.last:06d}"


def _log(record_row, kind, request, text="", occurred_at=None):
    return E.objects.create(record=record_row, kind=kind, occurred_at=occurred_at or timezone.now(), text=text, by_username=_actor(request))


def _officer(d):
    raw = d.get("arresting_officer")
    if raw in (None, ""):
        return None
    p = Personnel.objects.filter(pk=_uid(raw)).exclude(status__in=NOT_SERVING).select_related("rank").first() if _uid(raw) else None
    if p is None:
        raise field_error("arresting_officer", "unknown", "Unknown or non-serving person.")
    return p


def _locked(pk, version):
    r = R.objects.select_for_update().get(pk=pk)
    if r.version != version:
        raise VersionConflict()
    return r


def is_custody_station(unit):
    """A unit that can hold or receive people: a police station, or any unit that has a jail center."""
    return bool(unit.unit_type_id and unit.unit_type.code == "POLICE_STATION") or CustodyFacility.objects.filter(org_unit=unit, kind="jail_center").exists()


def _jail_center(d, unit):
    """The jail center that holds the person: the one chosen, else the station's only usable one, else none.

    Only a facility an authorised person has verified as operational can be used. A station with no operational jail center can still
    book an arrest (the register must never refuse one) but the person is then recorded without a verified holding place and shows
    on the oversight dashboard; set DETENTION_REQUIRE_OPERATIONAL_FACILITY=1 to refuse the booking instead."""
    raw = d.get("facility")
    if raw in (None, ""):
        mine = list(CustodyFacility.objects.filter(org_unit=unit, kind="jail_center", active=True, status="operational")[:2])
        if len(mine) == 1:
            return mine[0]
        if getattr(settings, "DETENTION_REQUIRE_OPERATIONAL_FACILITY", False):
            raise field_error("facility", "no_operational_facility", "This station has no verified, operational jail center to hold the person in.")
        return None
    fac = CustodyFacility.objects.filter(pk=_uid(raw)).first() if _uid(raw) else None
    if fac is None or fac.kind != "jail_center" or not fac.active or fac.org_unit_id != unit.pk:
        raise field_error("facility", "invalid_choice", "Choose a jail center of this station.")
    if fac.status != CustodyFacility.Status.OPERATIONAL:
        raise field_error("facility", "not_operational", "This jail center has not been verified as operational.")
    return fac


def _cell(raw, facility, current=None):
    """Lock and check a cell for one more person: it must belong to the facility, be switched on and have room. Returns the cell."""
    cell = CustodyCell.objects.select_for_update().filter(pk=_uid(raw)).first() if _uid(raw) else None
    if cell is None or facility is None or cell.facility_id != facility.pk or not cell.active:
        raise field_error("cell_ref", "invalid_choice", "Choose an active cell of this jail center.")
    if current is not None and cell.pk == current.pk:
        raise field_error("cell_ref", "same_cell", "The person is already in this cell.")
    if R.objects.filter(cell_ref=cell, status=R.Status.IN_CUSTODY).count() >= cell.capacity:
        raise field_error("cell_ref", "cell_full", "This cell is full.")
    return cell


def _check_id_free(key, exclude_pk=None):
    if key and R.objects.filter(id_ref_key=key).exclude(pk=exclude_pk).exists():
        raise field_error("id_ref", "duplicate_active_custody", "A person with this ID number is already in custody. One person cannot be held twice.")


# ---- business rules --------------------------------------------------------------------------------------------------------
def book_in(request, unit, d):
    """Book a person in. The whole booking is one transaction; a race on the same ID number is turned into the duplicate error."""
    try:
        with transaction.atomic():
            return _book_in(request, unit, d)
    except IntegrityError:
        raise field_error("id_ref", "duplicate_active_custody", "A person with this ID number is already in custody. One person cannot be held twice.")


def _book_in(request, unit, d):
    name = _text(d, "detainee_name", 200, required=True)
    reason = _text(d, "reason", 300, required=True)
    sex = d.get("sex") or R.Sex.UNKNOWN
    if sex not in {c.value for c in R.Sex}:
        raise field_error("sex", "invalid_choice", "Choose male, female or not recorded.")
    age = None
    if d.get("age_years") not in (None, ""):
        try:
            age = int(str(d["age_years"]).strip())
        except (TypeError, ValueError):
            raise field_error("age_years", "invalid_number", "Enter a whole number.")
        if age < 0 or age > 120:
            raise field_error("age_years", "invalid_number", "Enter an age between 0 and 120.")
    if not unit.active:
        raise field_error("org_unit", "inactive", "This station is not active.")
    booked = _not_future(_when(d.get("booked_at"), "booked_at", timezone.now()), "booked_at")
    officer = _officer(d)
    facility = _jail_center(d, unit)
    cell = _cell(d["cell_ref"], facility) if d.get("cell_ref") not in (None, "") else None
    key = id_key(_text(d, "id_ref", 80))
    _check_id_free(key)
    r = R.objects.create(register_no=_next_number(), org_unit=unit, facility=facility, cell_ref=cell, id_ref_key=key, detainee_name=name, detainee_alias=_text(d, "detainee_alias", 200), sex=sex,
                         age_years=age, id_ref=_text(d, "id_ref", 80), address=_text(d, "address", 200), booked_at=booked,
                         arrest_place=_text(d, "arrest_place", 200), arresting_officer=officer,
                         arresting_officer_name=_text(d, "arresting_officer_name", 200) or (officer.full_name if officer else ""), reason=reason,
                         authority_ref=_text(d, "authority_ref", 150), cell=cell.code if cell else _text(d, "cell", 60), property_held=_text(d, "property_held", 500),
                         health_note=_text(d, "health_note", 300), created_by_username=_actor(request))
    _log(r, "booked", request, f"Booked in: {reason}", booked)
    record("detention.book", request=request, entity_type="detention_record", entity_id=r.pk, metadata={"register_no": r.register_no, "org_unit": str(unit.pk)})
    if d.get("log_in_ob") in (True, "true", "1", 1, "on"):  # the arrest is also entered in the station's Occurrence Book
        from apps.occurrence.services import log_arrest
        log_arrest(request, r)
    return r


@transaction.atomic
def edit_details(request, row, d, version):
    r = _locked(row.pk, version)
    if r.status == R.Status.VOID:
        raise field_error("state", "void", "A voided record cannot be changed.")
    changed = []
    for name, limit in EDITABLE.items():
        if name in d:
            new = _text(d, name, limit, required=name in ("detainee_name", "reason"))
            if new != getattr(r, name):
                if name == "id_ref" and r.status == R.Status.IN_CUSTODY:
                    _check_id_free(id_key(new), exclude_pk=r.pk)
                    r.id_ref_key = id_key(new)
                setattr(r, name, new)
                changed.append(name)
    if "arresting_officer" in d:
        officer = _officer(d)
        if (officer.pk if officer else None) != r.arresting_officer_id:
            r.arresting_officer = officer
            changed.append("arresting_officer")
    if "sex" in d and d["sex"] != r.sex:
        if d["sex"] not in {c.value for c in R.Sex}:
            raise field_error("sex", "invalid_choice", "Choose male, female or not recorded.")
        r.sex = d["sex"]
        changed.append("sex")
    if not changed:
        return r
    r.version += 1
    r.save()
    _log(r, "corrected", request, "Changed: " + ", ".join(changed))  # field names only; values stay in the record itself
    record("detention.edit", request=request, entity_type="detention_record", entity_id=r.pk, metadata={"register_no": r.register_no, "fields": changed})
    return r


@transaction.atomic
def add_event(request, row, d, version):
    r = _locked(row.pk, version)
    if r.status != R.Status.IN_CUSTODY:
        raise field_error("state", "not_in_custody", "Events can only be added while the person is in custody.")
    kind = d.get("kind")
    if kind not in MANUAL_EVENT_KINDS:
        raise field_error("kind", "invalid_choice", "Choose a welfare check, medical, visit, cell move, property, statement, custody review or note.")
    text = _text(d, "text", 500, required=kind not in ("cell_move", "review"))
    when = _not_future(_when(d.get("occurred_at"), "occurred_at", timezone.now()), "occurred_at")
    if when < r.booked_at:
        raise field_error("occurred_at", "before_booking", "This cannot be earlier than the booking time.")
    if kind == "cell_move":
        if d.get("cell_ref") not in (None, ""):
            cell = _cell(d["cell_ref"], r.facility, current=r.cell_ref)
            r.cell_ref, r.cell = cell, cell.code
        else:
            r.cell_ref, r.cell = None, _text(d, "cell", 60, required=True)
        text = (f"Moved to {r.cell}. " + text).strip()
    elif kind == "property" and d.get("property_held") not in (None, ""):
        r.property_held = _text(d, "property_held", 500)
    elif kind == "review":
        r.last_review_at = when
        text = text or "Custody reviewed; continued holding recorded."
    r.version += 1
    r.save()
    ev = _log(r, kind, request, text, when)
    record("detention.event", request=request, entity_type="detention_record", entity_id=r.pk, metadata={"register_no": r.register_no, "kind": kind})
    return r, ev


def _destination_station(d, r):
    """The receiving station of a station-to-station transfer. It must be another active custody station with a usable jail center."""
    unit = OrganizationalUnit.objects.select_related("unit_type").filter(pk=_uid(d.get("destination_unit"))).first() if _uid(d.get("destination_unit")) else None
    if unit is None:
        raise field_error("destination_unit", "required", "Choose the station the person is moving to.")
    if unit.pk == r.org_unit_id:
        raise field_error("destination_unit", "same_station", "The person is already held at this station.")
    if not unit.active or not is_custody_station(unit):
        raise field_error("destination_unit", "not_a_station", "Choose an active police station.")
    if not CustodyFacility.objects.filter(org_unit=unit, kind="jail_center", active=True, status="operational").exists():
        raise field_error("destination_unit", "no_operational_facility", "That station has no verified, operational jail center to receive the person.")
    return unit


@transaction.atomic
def close_record(request, row, d, version):
    r = _locked(row.pk, version)
    if r.status != R.Status.IN_CUSTODY:
        raise field_error("state", "not_in_custody", "This person is no longer in custody.")
    outcome = d.get("outcome")
    if outcome not in R.RELEASE_OUTCOMES + R.TRANSFER_OUTCOMES:
        raise field_error("outcome", "invalid_choice", "Choose how the person left custody.")
    transfer = outcome in R.TRANSFER_OUTCOMES
    dest_fac = dest_unit = None
    if d.get("destination_facility") not in (None, ""):
        dest_fac = CustodyFacility.objects.filter(pk=_uid(d["destination_facility"])).first() if _uid(d["destination_facility"]) else None
        if outcome != "transfer_prison" or dest_fac is None or dest_fac.kind != "prison" or not dest_fac.active:
            raise field_error("destination_facility", "invalid_choice", "Choose a prison, and only when handing the person to the prison.")
        if dest_fac.status != CustodyFacility.Status.OPERATIONAL:
            raise field_error("destination_facility", "not_operational", "This prison has not been verified. Name the receiving prison in the destination field instead.")
    if outcome == "transfer_station":
        dest_unit = _destination_station(d, r)
    elif d.get("destination_unit") not in (None, ""):
        raise field_error("destination_unit", "invalid_choice", "A receiving station can only be named for a transfer to another station.")
    destination = _text(d, "destination", 200) or (dest_fac.name_en if dest_fac else "") or (dest_unit.name_en if dest_unit else "")
    if transfer and not destination:
        raise field_error("destination", "required", "This field is required.")
    ended = _not_future(_when(d.get("ended_at"), "ended_at", timezone.now()), "ended_at")
    if ended < r.booked_at:
        raise field_error("ended_at", "before_booking", "This cannot be earlier than the booking time.")
    note = _text(d, "outcome_note", 300, required=outcome in ("other", "bail", "court_order"))
    r.status = R.Status.TRANSFERRED if transfer else R.Status.RELEASED
    r.outcome, r.destination, r.outcome_note, r.ended_at, r.ended_by_username = outcome, destination, note, ended, _actor(request)
    r.outcome_ref = _text(d, "outcome_ref", 150)
    r.destination_facility, r.destination_unit = dest_fac, dest_unit
    r.id_ref_key = ""  # no longer in custody: the ID number is free again
    r.version += 1
    r.save()
    label = R.Outcome(outcome).label
    _log(r, "transferred" if transfer else "released", request, label + (f" to {destination}" if destination else "") + (f" (ref {r.outcome_ref})" if r.outcome_ref else "") + (f". {note}" if note else ""), ended)
    record("detention.transfer" if transfer else "detention.release", request=request, entity_type="detention_record", entity_id=r.pk,
           metadata={"register_no": r.register_no, "outcome": outcome, "held_hours": held_hours(r), **({"destination_unit": str(dest_unit.pk)} if dest_unit else {})})
    return r


@transaction.atomic
def receive_record(request, row, d, version):
    """The receiving station takes in a person transferred to it. Opens a new register row (new number, original booking time kept)
    linked to the sending row, which can be received once only."""
    old = _locked(row.pk, version)
    if old.status != R.Status.TRANSFERRED or old.outcome != "transfer_station" or old.destination_unit_id is None:
        raise field_error("state", "not_transfer", "Only a person transferred to another station can be received.")
    if R.objects.filter(transferred_from=old).exists():
        raise field_error("state", "already_received", "This person has already been received.")
    unit = old.destination_unit
    if not unit.active:
        raise field_error("org_unit", "inactive", "This station is not active.")
    received = _not_future(_when(d.get("received_at"), "received_at", timezone.now()), "received_at")
    if received < old.ended_at:
        raise field_error("received_at", "before_transfer", "This cannot be earlier than the time the person left the sending station.")
    facility = _jail_center(d, unit)
    if facility is None:
        raise field_error("facility", "no_operational_facility", "Choose a verified, operational jail center of this station.")
    cell = _cell(d["cell_ref"], facility) if d.get("cell_ref") not in (None, "") else None
    key = id_key(old.id_ref)
    _check_id_free(key)
    try:
        with transaction.atomic():
            new = R.objects.create(
                register_no=_next_number(), org_unit=unit, facility=facility, cell_ref=cell, cell=cell.code if cell else _text(d, "cell", 60),
                detainee_name=old.detainee_name, detainee_alias=old.detainee_alias, sex=old.sex, age_years=old.age_years, id_ref=old.id_ref, id_ref_key=key,
                address=old.address, booked_at=old.booked_at, received_at=received, arrest_place=old.arrest_place, arresting_officer=old.arresting_officer,
                arresting_officer_name=old.arresting_officer_name, reason=old.reason, authority_ref=old.authority_ref, property_held=old.property_held,
                health_note=old.health_note, last_review_at=old.last_review_at, transferred_from=old, created_by_username=_actor(request))
    except IntegrityError:
        raise field_error("state", "already_received", "This person has already been received, or is already in custody.")
    _log(new, "received", request, f"Received from {old.org_unit.name_en} (register {old.register_no})", received)
    record("detention.receive", request=request, entity_type="detention_record", entity_id=new.pk,
           metadata={"register_no": new.register_no, "from_register_no": old.register_no, "from_unit": str(old.org_unit_id), "org_unit": str(unit.pk)})
    return new


@transaction.atomic
def void_record(request, row, d, version):
    r = _locked(row.pk, version)
    if r.status == R.Status.VOID:
        raise field_error("state", "already_void", "This record is already voided.")
    if R.objects.filter(transferred_from=r).exists():
        raise field_error("state", "received", "The receiving station has already taken this person in; void that record instead.")
    reason = _text(d, "reason", 300, required=True)
    r.status, r.voided_at, r.voided_by_username, r.voided_reason = R.Status.VOID, timezone.now(), _actor(request), reason
    r.id_ref_key = ""
    r.version += 1
    r.save()
    _log(r, "voided", request, reason)
    record("detention.void", request=request, entity_type="detention_record", entity_id=r.pk, metadata={"register_no": r.register_no, "reason": reason})
    return r


# ---- serialisers -----------------------------------------------------------------------------------------------------------
def _fac_brief(f):
    return None if f is None else {"id": str(f.pk), "code": f.code, "kind": f.kind, "name_en": f.name_en, "name_so": f.name_so, "status": f.status}


def _cell_brief(c):
    return None if c is None else {"id": str(c.pk), "code": c.code, "name": c.name}


def _out(r, now=None):
    nxt = getattr(r, "received_as", None)
    prev = r.transferred_from
    return {"id": str(r.pk), "register_no": r.register_no, "org_unit": _unit_brief(r.org_unit), "detainee_name": r.detainee_name,
            "detainee_alias": r.detainee_alias, "sex": r.sex, "age_years": r.age_years, "id_ref": r.id_ref, "address": r.address,
            "booked_at": r.booked_at, "arrest_place": r.arrest_place, "arresting_officer": _person_brief(r.arresting_officer),
            "arresting_officer_name": r.arresting_officer_name, "reason": r.reason, "authority_ref": r.authority_ref, "cell": r.cell,
            "cell_ref": _cell_brief(r.cell_ref),
            "facility": _fac_brief(r.facility), "destination_facility": _fac_brief(r.destination_facility),
            "property_held": r.property_held, "health_note": r.health_note, "status": r.status, "ended_at": r.ended_at, "outcome": r.outcome,
            "destination": r.destination, "destination_unit": _unit_brief(r.destination_unit) if r.destination_unit_id else None,
            "outcome_ref": r.outcome_ref, "outcome_note": r.outcome_note, "held_hours": held_hours(r, now), "overdue": is_overdue(r, now),
            "last_review_at": r.last_review_at, "hours_since_review": hours_since_review(r, now) if r.status == R.Status.IN_CUSTODY else None,
            "received_at": r.received_at, "received_from": prev.register_no if prev else None, "received_as": nxt.register_no if nxt else None,
            "awaiting_receipt": bool(r.status == R.Status.TRANSFERRED and r.outcome == "transfer_station" and nxt is None),
            "recorded_by": r.created_by_username, "voided_reason": r.voided_reason if r.status == R.Status.VOID else "", "version": r.version}


def _event_out(e):
    return {"id": str(e.pk), "kind": e.kind, "occurred_at": e.occurred_at, "text": e.text, "by": e.by_username}


REL = ("org_unit", "arresting_officer__rank", "facility", "destination_facility", "cell_ref", "destination_unit", "transferred_from", "received_as")


# ---- API -------------------------------------------------------------------------------------------------------------------
class DetentionViewSet(viewsets.GenericViewSet):
    """Detention register. Reads are audited and narrowed to the caller's unit scope."""

    permission_classes = [ScopedPermission]
    pagination_class = _Page
    parser_classes = [JSONParser]
    lookup_value_regex = r"[0-9a-f\-]{36}"
    permission_map = {"list": ("detention.view", "any"), "retrieve": ("detention.view", "any"), "summary": ("detention.view", "any"),
                      "create": ("detention.manage", "any"), "edit": ("detention.manage", "any"), "event": ("detention.manage", "any"),
                      "close": ("detention.manage", "any"), "void": ("detention.manage", "any"), "receive": ("detention.manage", "any"),
                      "incoming": ("detention.manage", "any"), "stations": ("detention.manage", "any")}

    def _scoped(self):
        q = scope.unit_scope_q(self.request.user, "detention.view", "org_unit__")
        return R.objects.none() if q is None else R.objects.filter(q)

    def _row(self, pk, write=False):
        row = self._scoped().select_related(*REL).filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None or (write and not scope.can(self.request.user, "detention.manage", unit=row.org_unit)):
            raise Http404
        return row

    def _incoming_qs(self):
        q = scope.unit_scope_q(self.request.user, "detention.manage", "destination_unit__")
        if q is None:
            return R.objects.none()
        return R.objects.filter(q, status="transferred", outcome="transfer_station", received_as__isnull=True)

    def _fresh(self, pk):
        return _out(R.objects.select_related(*REL).get(pk=pk))

    def list(self, request):
        p = request.query_params
        qs = self._scoped().select_related(*REL)
        if p.get("status") in {"in_custody", "released", "transferred", "void"}:
            qs = qs.filter(status=p["status"])
        elif p.get("include_void") != "1":
            qs = qs.exclude(status="void")
        if p.get("overdue") == "1":
            qs = qs.filter(overdue_q())
        if _uid(p.get("facility")):
            qs = qs.filter(facility_id=_uid(p["facility"]))
        if _uid(p.get("unit")):
            prefix = OrganizationalUnit.objects.filter(pk=_uid(p["unit"])).values_list("path", flat=True).first()
            qs = qs.filter(org_unit__path__startswith=prefix) if prefix else qs.none()
        if p.get("from"):
            qs = qs.filter(booked_at__date__gte=_day(p["from"], "from"))
        if p.get("to"):
            qs = qs.filter(booked_at__date__lte=_day(p["to"], "to"))
        if p.get("q"):
            s = p["q"].strip()[:60]
            qs = qs.filter(Q(register_no__icontains=s) | Q(detainee_name__icontains=s) | Q(detainee_alias__icontains=s) | Q(reason__icontains=s)
                           | Q(id_ref__icontains=s) | Q(authority_ref__icontains=s))
        page = self.paginate_queryset(qs.order_by("-booked_at"))
        record_read(request, "detention.read_list", entity_type="detention_register", count=len(page))
        now = timezone.now()
        return self.get_paginated_response([_out(r, now) for r in page])

    def retrieve(self, request, pk=None):
        r = self._row(pk)
        record_read(request, "detention.read_record", entity_type="detention_record", entity_id=r.pk, org_unit=r.org_unit)
        return Response({**_out(r), "events": [_event_out(e) for e in r.events.all()]})

    def create(self, request):
        d = json_body(request)
        unit = OrganizationalUnit.objects.filter(pk=_uid(d.get("org_unit"))).first() if _uid(d.get("org_unit")) else None
        if unit is None or not scope.can(request.user, "detention.manage", unit=unit):
            raise field_error("org_unit", "unknown", "Choose the station holding the person.")
        r = book_in(request, unit, d)
        return Response(self._fresh(r.pk), status=201)

    @action(detail=True, methods=["post"])
    def edit(self, request, pk=None):
        d = json_body(request)
        r = edit_details(request, self._row(pk, write=True), d, require_version(d))
        return Response(self._fresh(r.pk))

    @action(detail=True, methods=["post"])
    def event(self, request, pk=None):
        d = json_body(request)
        r, _ev = add_event(request, self._row(pk, write=True), d, require_version(d))
        return Response(self._fresh(r.pk), status=201)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Release or transfer: the person leaves custody with an outcome."""
        d = json_body(request)
        r = close_record(request, self._row(pk, write=True), d, require_version(d))
        return Response(self._fresh(r.pk))

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """The receiving station takes in a person transferred to it. `pk` is the sending station's record."""
        d = json_body(request)
        row = self._incoming_qs().filter(pk=_uid(pk)).first() if _uid(pk) else None
        if row is None:
            raise Http404
        new = receive_record(request, row, d, require_version(d))
        return Response(self._fresh(new.pk), status=201)

    @action(detail=False, methods=["get"])
    def incoming(self, request):
        """People transferred to the caller's stations and not yet received. Only what the receiving desk needs to recognise them."""
        now = timezone.now()
        rows = self._incoming_qs().select_related("org_unit", "destination_unit").order_by("ended_at")
        record_read(request, "detention.read_incoming", entity_type="detention_incoming", count=rows.count())
        return Response({"results": [{"id": str(r.pk), "register_no": r.register_no, "detainee_name": r.detainee_name, "from_unit": _unit_brief(r.org_unit),
                                      "to_unit": _unit_brief(r.destination_unit), "booked_at": r.booked_at, "left_at": r.ended_at, "outcome_ref": r.outcome_ref,
                                      "held_hours": held_hours(r, now), "version": r.version} for r in rows]})

    @action(detail=False, methods=["get"])
    def stations(self, request):
        """Stations a person can be transferred to: active custody stations with a verified, operational jail center."""
        ids = CustodyFacility.objects.filter(kind="jail_center", active=True, status="operational").values_list("org_unit_id", flat=True)
        units = OrganizationalUnit.objects.filter(pk__in=ids, active=True).order_by("path")
        return Response({"results": [{"id": str(u.pk), "code": u.code, "name_en": u.name_en, "name_so": u.name_so} for u in units]})

    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        d = json_body(request)
        r = void_record(request, self._row(pk, write=True), d, require_version(d))
        return Response(self._fresh(r.pk))

    @action(detail=False, methods=["get"])
    def summary(self, request):
        qs = self._scoped().exclude(status="void")
        now = timezone.now()
        today = timezone.localdate()
        held = qs.filter(status="in_custody")
        out = {"in_custody": held.count(), "overdue": qs.filter(overdue_q(now)).count(),
               "booked_today": qs.filter(booked_at__date=today, transferred_from__isnull=True).count(), "left_today": qs.filter(ended_at__date=today).count(),
               "incoming": self._incoming_qs().count(), "review_hours": review_hours()}
        record_read(request, "detention.read_summary", entity_type="detention_summary")
        return Response(out)
