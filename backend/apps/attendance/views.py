import uuid
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record as audit
from apps.audit.services import record_read
from apps.core.errors import field_error
from apps.core.params import json_body, uuid_param
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel, PersonnelDocument
from apps.personnel.services import NOT_SERVING
from apps.workflows.models import ApprovalAction, ReportType, Submission

from . import situation
from .models import AbsenceReason, AttendanceRecord

MAX_ROWS = 500
STATUSES = {s.value for s in AttendanceRecord.Status}


def _uid(value):
    """A UUID string, or None for anything else (a malformed id must never become a 500)."""
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _day(value, name):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise field_error(name, "invalid_date", "Use a date like 2026-03-01.")


def _unit(request, value, code):
    """Resolve a unit and check the caller's scope. Unknown and out-of-scope read alike, so ids cannot be probed."""
    unit = OrganizationalUnit.objects.filter(pk=_uid(value)).first() if _uid(value) else None
    if unit is None or not scope.can(request.user, code, unit=unit):
        raise field_error("org_unit", "out_of_scope", "That unit is outside your scope.")
    return unit


def _person_brief(p):
    return {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number, "status": p.status,
            "rank": {"code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so}}


def _rec_out(r):
    return {"id": str(r.pk), "personnel": str(r.personnel_id), "report_date": r.report_date.isoformat(), "status": r.status,
            "reason": r.reason.code if r.reason_id else None, "note": r.note, "document": str(r.document_id) if r.document_id else None,
            "reported_by": r.reported_by_username, "created_at": r.created_at, "amended": r.supersedes_id is not None,
            "amend_reason": r.amend_reason, "superseded_at": r.superseded_at}


def _check_entry(user, unit, e, reasons):
    """Validate one entry; returns (error_code or None, cleaned dict)."""
    if not isinstance(e, dict) or e.get("status") not in STATUSES:
        return "invalid_status", None
    pid = _uid(e.get("personnel"))
    person = Personnel.objects.select_related("org_unit", "rank").filter(pk=pid).first() if pid else None
    if (person is None or not person.org_unit.path.startswith(unit.path)
            or not scope.can(user, "attendance.record", unit=person.org_unit)):
        return "person_unknown", None  # unknown, outside the unit and outside scope read alike
    if person.status in NOT_SERVING:
        return "person_not_serving", None
    reason = None
    if e["status"] == "absent":
        reason = reasons.get(e.get("reason"))
        if reason is None:
            return "reason_required", None
        if reason.requires_document and not e.get("document"):
            return "document_required", None
    doc = None
    if e.get("document"):
        did = _uid(e["document"])
        doc = PersonnelDocument.objects.filter(pk=did, personnel=person, withdrawn_at__isnull=True).first() if did else None
        if doc is None:
            return "document_invalid", None
    return None, {"person": person, "status": e["status"], "reason": reason, "note": str(e.get("note") or "")[:300], "doc": doc}


class AttendanceViewSet(viewsets.ViewSet):
    """Daily attendance and absence reporting for authorized commanders (Taliye Guuto / Taliye Urur by default), plus the
    unit situation report built from saved records. Attendance never changes personnel status."""

    permission_classes = [ScopedPermission]
    permission_map = {
        "list": ("attendance.view", "any"), "reasons": ("attendance.view", "any"), "roll": ("attendance.view", "any"), "records": ("attendance.view", "any"),
        "summary": ("attendance.view", "any"), "situation_preview": ("attendance.view", "any"),
        "record": ("attendance.record", "any"), "amend": ("attendance.record", "any"),
        "situation_report": ("reports.submit", "any"),
    }
    queryset = AttendanceRecord.objects.none()

    def list(self, request):
        """Current attendance records of a unit and below (same as /records/)."""
        return self.records(request)

    @action(detail=False, methods=["get"])
    def reasons(self, request):
        rows = AbsenceReason.objects.filter(active=True)
        return Response({"results": [{"code": r.code, "name_en": r.name_en, "name_so": r.name_so,
                                      "requires_document": r.requires_document} for r in rows]})

    @action(detail=False, methods=["get"])
    def roll(self, request):
        """Everyone serving in the unit (and below) for one day, with that day's current attendance record if any."""
        unit = _unit(request, uuid_param(request, "org_unit"), "attendance.view")
        day = _day(request.query_params.get("date") or timezone.localdate().isoformat(), "date")
        q = scope.unit_scope_q(request.user, "attendance.view", "org_unit__")
        people = (Personnel.objects.filter(q, org_unit__path__startswith=unit.path).exclude(status__in=NOT_SERVING)
                  .select_related("rank", "org_unit").order_by("-rank__sort_order", "full_name")[:1000])
        people = list({p.pk: p for p in people}.values())  # each person once, whatever the scope joins produce
        today = {r.personnel_id: r for r in AttendanceRecord.objects.filter(
            personnel__in=[p.pk for p in people], report_date=day, superseded_at__isnull=True).select_related("reason")}
        record_read(request, "attendance.read_roll", entity_type="attendance", org_unit=unit, count=len(people))
        return Response({"date": day.isoformat(), "org_unit": str(unit.pk), "results": [
            {**_person_brief(p), "unit": {"code": p.org_unit.code, "name_en": p.org_unit.name_en, "name_so": p.org_unit.name_so},
             "attendance": _rec_out(today[p.pk]) if p.pk in today else None} for p in people]})

    @action(detail=False, methods=["get"])
    def records(self, request):
        unit = _unit(request, uuid_param(request, "org_unit"), "attendance.view")
        start = _day(request.query_params.get("from") or "1970-01-01", "from")
        end = _day(request.query_params.get("to") or "2999-12-31", "to")
        qs = AttendanceRecord.objects.filter(org_unit__path__startswith=unit.path, report_date__range=(start, end)).select_related("reason")
        if request.query_params.get("include_superseded") != "1":
            qs = qs.filter(superseded_at__isnull=True)
        pid = uuid_param(request, "personnel")
        if pid:
            qs = qs.filter(personnel_id=pid)
        rows = list(qs[:500])
        record_read(request, "attendance.read_records", entity_type="attendance", org_unit=unit, count=len(rows))
        return Response({"results": [_rec_out(r) for r in rows]})

    @action(detail=False, methods=["post"])
    def record(self, request):
        """Record one day for a unit: {org_unit, date, entries: [{personnel, status, reason?, note?, document?}]}.
        All entries are checked first; if any is wrong nothing is saved. A soldier already recorded that day must be amended."""
        d = json_body(request)
        unit = _unit(request, d.get("org_unit"), "attendance.record")
        day = _day(d.get("date"), "date")
        if day > timezone.localdate():
            raise field_error("date", "future_date", "Attendance cannot be recorded for a future date.")
        entries = d.get("entries")
        if not isinstance(entries, list) or not entries or len(entries) > MAX_ROWS:
            raise field_error("entries", "entries_invalid", "Send between 1 and 500 entries.")
        reasons = {r.code: r for r in AbsenceReason.objects.filter(active=True)}
        clean, errors, seen = [], [], {}
        for i, e in enumerate(entries):
            code, c = _check_entry(request.user, unit, e, reasons)
            if code is None and c["person"].pk in seen:
                code = "duplicate_entry"
            if code:
                errors.append({"index": i, "code": code})
                continue
            seen[c["person"].pk] = i
            c["index"] = i
            clean.append(c)
        existing = set(AttendanceRecord.objects.filter(personnel_id__in=list(seen), report_date=day, superseded_at__isnull=True)
                       .values_list("personnel_id", flat=True))
        errors += [{"index": c["index"], "code": "already_recorded"} for c in clean if c["person"].pk in existing]
        if errors:
            return Response({"code": "attendance_invalid", "detail": "Fix the listed entries; nothing was saved.", "rows": errors}, status=400)
        try:
            with transaction.atomic():
                made = [AttendanceRecord(
                    personnel=c["person"], org_unit=c["person"].org_unit, report_date=day, status=c["status"], reason=c["reason"],
                    note=c["note"], document=c["doc"], reported_by_id=request.user.pk, reported_by_username=request.user.username)
                    for c in clean]
                AttendanceRecord.objects.bulk_create(made)
                counts = {s: sum(1 for m in made if m.status == s) for s in STATUSES}
                audit("attendance.recorded", request=request, entity_type="attendance", entity_id=unit.pk,
                       metadata={"unit": unit.code, "date": day.isoformat(), "count": len(made), **counts})
        except IntegrityError:  # another officer recorded the same soldier at the same moment: the database refuses
            return Response({"code": "attendance_invalid", "detail": "Someone else recorded this day first.",
                             "rows": [{"index": 0, "code": "already_recorded"}]}, status=409)
        return Response({"saved": len(made), **counts}, status=201)

    @action(detail=False, methods=["post"])
    def amend(self, request):
        """Change a recorded day. Writes a new record that supersedes the old one; a reason is required and the old record stays."""
        d = json_body(request)
        rid = _uid(d.get("record"))
        rec = AttendanceRecord.objects.select_related("org_unit", "personnel__rank", "personnel__org_unit").filter(
            pk=rid, superseded_at__isnull=True).first() if rid else None
        if rec is None or not scope.can(request.user, "attendance.record", unit=rec.org_unit):
            return Response({"code": "not_found", "detail": "Not found."}, status=404)
        why = str(d.get("amend_reason") or "").strip()
        if not why:
            raise field_error("amend_reason", "reason_required", "Say why the record is being changed.")
        reasons = {r.code: r for r in AbsenceReason.objects.filter(active=True)}
        code, c = _check_entry(request.user, rec.personnel.org_unit, {**d, "personnel": str(rec.personnel_id)}, reasons)
        if code:
            raise field_error("status", code, "That amendment is not valid.")
        with transaction.atomic():
            AttendanceRecord.objects.filter(pk=rec.pk).update(superseded_at=timezone.now())
            new = AttendanceRecord.objects.create(
                personnel=rec.personnel, org_unit=rec.org_unit, report_date=rec.report_date, status=c["status"], reason=c["reason"],
                note=c["note"], document=c["doc"], reported_by_id=request.user.pk, reported_by_username=request.user.username,
                supersedes=rec, amend_reason=why[:300])
            audit("attendance.amended", request=request, entity_type="attendance", entity_id=rec.personnel_id,
                   metadata={"date": rec.report_date.isoformat(), "from": rec.status, "to": new.status, "record": str(new.pk)})
        return Response(_rec_out(new))

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Daily / monthly / six-monthly / yearly totals for a unit and below, calculated from the saved records."""
        unit = _unit(request, uuid_param(request, "org_unit"), "attendance.view")
        kind = request.query_params.get("period", "day")
        anchor = _day(request.query_params.get("date") or timezone.localdate().isoformat(), "date")
        start, end = situation.period_bounds(kind, anchor)
        figs = situation_figures_attendance(unit, start, end)
        record_read(request, "attendance.read_summary", entity_type="attendance", org_unit=unit)
        return Response({"period": kind, "start": start.isoformat(), "end": end.isoformat(),
                         "org_unit": str(unit.pk), "generated_at": timezone.now(), **figs})

    @action(detail=False, methods=["get"], url_path="situation-preview")
    def situation_preview(self, request):
        unit = _unit(request, uuid_param(request, "org_unit"), "attendance.view")
        start, end = _day(request.query_params.get("from"), "from"), _day(request.query_params.get("to"), "to")
        if end < start:
            raise field_error("to", "period_invalid", "The end must not be before the start.")
        return Response({"start": start.isoformat(), "end": end.isoformat(), "figures": situation.compute_figures(request.user, unit, start, end)})

    @action(detail=False, methods=["post"], url_path="situation-report")
    def situation_report(self, request):
        """Create a DRAFT unit situation report whose figures come from the saved records. It then goes through the normal
        submit -> review -> approve workflow (reports.submit / reports.review, submitter never approves their own)."""
        d = json_body(request)
        unit = _unit(request, d.get("org_unit"), "reports.submit")
        if unit.level not in ("branch_command", "unit") or not unit.active:
            raise field_error("org_unit", "unit_level_invalid", "Choose an active unit.")
        start, end = _day(d.get("period_start"), "period_start"), _day(d.get("period_end"), "period_end")
        if end < start:
            raise field_error("period_end", "period_invalid", "The end must not be before the start.")
        rtype = ReportType.objects.filter(code=situation.SITUATION_REPORT, active=True).first()
        if rtype is None:
            raise field_error("report_type", "not_found", "The situation report type is not configured.")
        figures = situation.compute_figures(request.user, unit, start, end)
        title = (str(d.get("title") or "").strip() or f"{unit.name_en}: situation report {start} to {end}")[:200]
        with transaction.atomic():
            sub = Submission.objects.create(report_type=rtype, org_unit=unit, title=title, period_start=start, period_end=end,
                                            body=str(d.get("body") or "")[:5000], figures=figures, submitter=request.user,
                                            submitter_username=request.user.username)
            ApprovalAction.objects.create(submission=sub, action="create", to_status=sub.status, actor=request.user,
                                          actor_username=request.user.username)
            audit("report.create", request=request, entity_type="submission", entity_id=sub.pk,
                   metadata={"type": rtype.code, "unit": str(unit.pk), "computed": True})
        return Response({"id": str(sub.pk), "status": sub.status, "figures": figures}, status=201)


def situation_figures_attendance(unit, start, end):
    """Attendance totals only (no ammunition), for the summary screen."""
    from django.db.models import Count
    days = (end - start).days + 1
    serving = Personnel.objects.filter(org_unit__path__startswith=unit.path).exclude(status__in=NOT_SERVING).count()
    att = {s: n for s, n in AttendanceRecord.objects.filter(
        org_unit__path__startswith=unit.path, report_date__range=(start, end), superseded_at__isnull=True)
        .values_list("status").annotate(n=Count("id"))}
    recorded = sum(att.values())
    return {"days": days, "serving": serving, "present": att.get("present", 0), "absent": att.get("absent", 0),
            "on_leave": att.get("on_leave", 0), "recorded": recorded, "not_recorded": max(0, serving * days - recorded)}
