"""Occurrence Book rules. An entry is numbered per station and year, never edited, corrected by follow-up lines or voided with a reason."""
from django.db import transaction
from django.utils import timezone

from apps.audit.services import record
from apps.core.concurrency import VersionConflict
from apps.core.errors import field_error
from apps.detention.views import _actor, _not_future, _text, _when

from .models import OccurrenceCounter, OccurrenceEntry, OccurrenceFollowUp

E = OccurrenceEntry
CATEGORIES = {c for c, _ in E.Category.choices}
FOLLOW_UP_KINDS = ("update", "correction", "outcome")


def next_number(unit, year):
    """Next OB number for a station and year. Call inside a transaction (the counter row is locked)."""
    c, _ = OccurrenceCounter.objects.select_for_update().get_or_create(org_unit=unit, year=year)
    c.last += 1
    c.save(update_fields=["last"])
    return c.last, f"OB {c.last:04d}/{year}"


def _log(entry, kind, text, by, when=None):
    return OccurrenceFollowUp.objects.create(entry=entry, kind=kind, occurred_at=when or timezone.now(), text=text, by_username=by)


@transaction.atomic
def create_entry(request, unit, d, detention=None):
    category = d.get("category")
    if category not in CATEGORIES:
        raise field_error("category", "invalid_choice", "Choose what kind of entry this is.")
    summary = _text(d, "summary", 300, required=True)
    details = _text(d, "details", 3000)
    occurred = _not_future(_when(d.get("occurred_at"), "occurred_at", timezone.now()), "occurred_at")
    if detention is None and d.get("detention_record") not in (None, ""):
        raise field_error("detention_record", "unsupported", "Link a detention record from the Detention register.")
    year = timezone.localtime(occurred).year
    seq, number = next_number(unit, year)
    entry = E.objects.create(org_unit=unit, ob_year=year, ob_seq=seq, ob_number=number, category=category, occurred_at=occurred,
                             location=_text(d, "location", 200), reported_by=_text(d, "reported_by", 200), summary=summary, details=details,
                             detention_record=detention, recorded_by_username=_actor(request))
    record("occurrence.create", request=request, entity_type="occurrence_entry", entity_id=entry.pk,
           metadata={"ob_number": number, "category": category, "org_unit": str(unit.pk)})  # no names or narrative in audit data
    return entry


def log_arrest(request, det):
    """Enter a booking in the Occurrence Book too (called from the detention register when the officer ticks the box)."""
    return create_entry(request, det.org_unit, {
        "category": "arrest", "occurred_at": det.booked_at.isoformat(), "location": det.arrest_place, "reported_by": "",
        "summary": f"Arrest: {det.detainee_name}, held under {det.register_no}"[:300],
        "details": f"Ground: {det.reason}. Arresting officer: {det.arresting_officer_name or 'not recorded'}."[:3000]}, detention=det)


@transaction.atomic
def add_follow_up(request, row, d, version):
    entry = E.objects.select_for_update().get(pk=row.pk)
    if entry.version != version:
        raise VersionConflict()
    if entry.status == E.Status.VOID:
        raise field_error("state", "void", "A voided entry cannot be changed.")
    kind = d.get("kind") or "update"
    if kind not in FOLLOW_UP_KINDS:
        raise field_error("kind", "invalid_choice", "Choose update, correction or outcome.")
    text = _text(d, "text", 500, required=True)
    when = _not_future(_when(d.get("occurred_at"), "occurred_at", timezone.now()), "occurred_at")
    if when < entry.occurred_at:
        raise field_error("occurred_at", "before_entry", "This cannot be earlier than the entry itself.")
    entry.version += 1
    entry.save(update_fields=["version"])
    _log(entry, kind, text, _actor(request), when)
    record("occurrence.follow_up", request=request, entity_type="occurrence_entry", entity_id=entry.pk, metadata={"ob_number": entry.ob_number, "kind": kind})
    return entry


@transaction.atomic
def void_entry(request, row, d, version):
    entry = E.objects.select_for_update().get(pk=row.pk)
    if entry.version != version:
        raise VersionConflict()
    if entry.status == E.Status.VOID:
        raise field_error("state", "already_void", "This entry is already voided.")
    reason = _text(d, "reason", 300, required=True)
    entry.status, entry.voided_at, entry.voided_by_username, entry.voided_reason = E.Status.VOID, timezone.now(), _actor(request), reason
    entry.version += 1
    entry.save()
    _log(entry, "voided", reason, _actor(request))
    record("occurrence.void", request=request, entity_type="occurrence_entry", entity_id=entry.pk, metadata={"ob_number": entry.ob_number, "reason": reason})
    return entry
