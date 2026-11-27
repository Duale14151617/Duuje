"""Scheduled report API: manage schedules, send a test, and the token-protected trigger an outside scheduler can call."""
import hmac

from django.conf import settings
from django.db import transaction
from django.http import Http404, HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record, record_read
from apps.core.concurrency import require_version
from apps.core.errors import field_error
from apps.core.negotiation import IgnoreNegotiation
from apps.core.params import json_body
from apps.organization.models import OrganizationalUnit
from apps.vehicles.views import _uid

from . import alerts, services, unitreport
from .models import ReportSchedule

MANAGE = "schedules.manage"
F = ReportSchedule.Frequency
REPORT_KINDS = {"strength", "unit"}  # "unit" = the unit report, emailed as a PDF attachment


def _int(data, name, lo, hi, default):
    v = data.get(name, default)
    if isinstance(v, bool) or not isinstance(v, int) or not (lo <= v <= hi):
        raise field_error(name, "out_of_range", f"Use a whole number from {lo} to {hi}.")
    return v


def _out(s):
    return {
        "id": str(s.pk), "name": s.name, "report": s.report, "enabled": s.enabled, "version": s.version,
        "org_unit": {"id": str(s.org_unit_id), "code": s.org_unit.code, "name_en": s.org_unit.name_en, "name_so": s.org_unit.name_so},
        "frequency": s.frequency, "weekday": s.weekday, "day_of_month": s.day_of_month, "send_hour": s.send_hour,
        "period_days": s.period_days,
        "recipients": [{"id": str(u.pk), "full_name": u.full_name, "username": u.username} for u in s.recipients.all()],
        "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None,
        "last_run_at": s.last_run_at.isoformat() if s.last_run_at else None,
        "last_status": s.last_status, "last_detail": s.last_detail, "timezone": str(services.tz()),
    }


def _recipients(data, unit):
    raw = data.get("recipients", [])
    if not isinstance(raw, list) or len(raw) > services.MAX_RECIPIENTS:
        raise field_error("recipients", "invalid", f"Choose up to {services.MAX_RECIPIENTS} recipients.")
    ids = [_uid(x) for x in raw]
    if any(i is None for i in ids):
        raise field_error("recipients", "invalid", "Invalid recipient.")
    allowed = {str(u.pk): u for u in services.eligible_recipients(unit)}
    if any(i not in allowed for i in ids):
        raise field_error("recipients", "not_eligible", "Each recipient needs a verified email and access to this area's personnel report.")
    return [allowed[i] for i in dict.fromkeys(ids)]


class ReportScheduleViewSet(viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {"list": (MANAGE, "any"), "create": (MANAGE, "any"), "partial_update": (MANAGE, "unit"), "remove": (MANAGE, "unit"),
                      "send_now": (MANAGE, "unit"), "recipients": (MANAGE, "any")}
    lookup_value_regex = "[0-9a-fA-F-]{36}"
    http_method_names = ["get", "post", "patch", "head", "options"]  # like every other viewset here: no PUT or DELETE verbs

    def scope_unit(self, obj):
        return obj.org_unit

    def get_queryset(self):
        q = scope.unit_scope_q(self.request.user, MANAGE, "org_unit__")
        qs = ReportSchedule.objects.select_related("org_unit", "created_by").prefetch_related("recipients")
        return qs.none() if q is None else qs.filter(q)

    def list(self, request):
        return Response({"results": [_out(s) for s in self.get_queryset()], "enabled": getattr(settings, "SCHEDULED_REPORTS_ENABLED", True)})

    @action(detail=False, methods=["get"])
    def recipients(self, request):
        uid = _uid(request.query_params.get("unit"))
        unit = OrganizationalUnit.objects.filter(pk=uid).first() if uid else None
        if unit is None or not scope.can(request.user, MANAGE, unit=unit):
            raise Http404
        return Response({"results": [{"id": str(u.pk), "full_name": u.full_name, "username": u.username} for u in services.eligible_recipients(unit)]})

    def _apply(self, s, data, unit):
        name = str(data.get("name", s.name) or "").strip()
        if not name or len(name) > 120:
            raise field_error("name", "required", "Give the schedule a name (120 characters at most).")
        freq = data.get("frequency", s.frequency)
        if freq not in {f.value for f in F}:
            raise field_error("frequency", "invalid", "Choose daily, weekly or monthly.")
        report = data.get("report", s.report)
        if report not in REPORT_KINDS:
            raise field_error("report", "invalid", "Choose the strength summary or the unit report (PDF).")
        s.name, s.frequency, s.org_unit, s.report = name, freq, unit, report
        s.weekday = _int(data, "weekday", 0, 6, s.weekday)
        s.day_of_month = _int(data, "day_of_month", 1, 28, s.day_of_month)
        s.send_hour = _int(data, "send_hour", 0, 23, s.send_hour)
        s.period_days = _int(data, "period_days", 1, 90, s.period_days)
        if "enabled" in data:
            s.enabled = bool(data["enabled"])

    def create(self, request):
        data = json_body(request)
        uid = _uid(data.get("org_unit"))
        unit = OrganizationalUnit.objects.filter(pk=uid).first() if uid else None
        if unit is None or not scope.can(request.user, MANAGE, unit=unit) or not scope.can(request.user, "personnel.view", unit=unit):
            raise Http404
        recips = _recipients(data, unit)
        s = ReportSchedule(created_by=request.user, org_unit=unit)
        self._apply(s, data, unit)
        with transaction.atomic():
            s.next_run_at = services.compute_next(s) if s.enabled else None
            s.save()
            s.recipients.set(recips)
        record("schedule.create", request=request, entity_type="report_schedule", entity_id=s.pk, metadata={"recipients": len(recips)})
        return Response(_out(s), status=201)

    def partial_update(self, request, pk=None):
        s = self.get_object()
        data = json_body(request)
        if require_version(data) != s.version:
            raise field_error("version", "version_conflict", "Someone else changed this schedule. Reload and try again.")
        recips = _recipients(data, s.org_unit) if "recipients" in data else None
        self._apply(s, data, s.org_unit)
        s.version += 1
        with transaction.atomic():
            s.next_run_at = services.compute_next(s) if s.enabled else None
            s.save()
            if recips is not None:
                s.recipients.set(recips)
        record("schedule.update", request=request, entity_type="report_schedule", entity_id=s.pk)
        return Response(_out(s))

    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):  # a POST action rather than the DELETE verb; removes the schedule (never any personnel data)
        s = self.get_object()
        sid = s.pk
        s.delete()
        record("schedule.delete", request=request, entity_type="report_schedule", entity_id=sid)
        return Response(status=204)

    @action(detail=True, methods=["post"], url_path="send-now")
    def send_now(self, request, pk=None):
        """{"to_me": true} sends a test to the caller only (needs a verified email); otherwise sends to every recipient now."""
        s = self.get_object()
        to_me = bool(json_body(request).get("to_me", True))
        only = None
        if to_me:
            if not request.user.email or request.user.email_verified_at is None:
                raise field_error("email", "email_unverified", "Verify your own email address first (Account page).")
            only = request.user
        status, detail = services.run(s, only_to=only, actor=request.user)
        s.refresh_from_db()
        return Response({"status": status, "detail": detail, "schedule": _out(s)})


class RunDueView(APIView):
    """POST with header X-Cron-Token: for an outside scheduler (cron-job.org, a Render cron job running curl, GitHub Actions...).
    404 unless SCHEDULES_CRON_TOKEN is set. Harmless to call often: only schedules that are due are sent."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = "docverify"

    def post(self, request):
        token = getattr(settings, "SCHEDULES_CRON_TOKEN", "")
        given = request.headers.get("X-Cron-Token", "")
        if not token or len(token) < 24 or not hmac.compare_digest(given.encode(), token.encode()):
            raise Http404
        done = services.run_due()
        from apps.core.health import record_beat
        record_beat("cron")
        from apps.dashboard.digest import send_due_digests
        return Response({"processed": len(done), "results": [{"name": n, "status": st} for n, st, _ in done],
                         "due_digests": send_due_digests(), "silent_tracker_alerts": alerts.check_silent_trackers()})


class UnitReportView(APIView):
    """GET ?unit=<id>&from=YYYY-MM-DD&to=YYYY-MM-DD: the unit report for that unit and everything below it, as a PDF download.
    Each section appears only if the caller may see that kind of information for the unit; a unit the caller can see nothing of is a 404."""

    content_negotiation_class = IgnoreNegotiation

    def get(self, request):
        uid = _uid(request.query_params.get("unit"))
        unit = OrganizationalUnit.objects.filter(pk=uid).first() if uid else None
        if unit is None:
            raise Http404
        try:
            d0, d1 = unitreport.period(request.query_params.get("from"), request.query_params.get("to"))
        except ValueError as e:
            raise field_error("from", "invalid_period", str(e))
        pdf = unitreport.render_pdf([request.user], unit, d0, d1)
        if pdf is None:
            raise Http404
        record_read(request, "unit.report_pdf", entity_type="unit_report", org_unit=unit, count=1)
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="{unitreport.filename(unit, d0, d1)}"'
        resp["Cache-Control"] = "private, no-store"
        resp["X-Content-Type-Options"] = "nosniff"
        return resp


class AlertPreferenceView(APIView):
    """GET: which event alerts this person may choose, and which they have on. PATCH {"kinds": [...]}: set exactly that choice.
    Only kinds the person's own permissions allow are offered; alerts go to a verified email address only."""

    def _state(self, request):
        u = request.user
        on = alerts.wanted_kinds(u)
        return {"email_ok": bool(u.email and u.email_verified_at), "enabled": alerts.enabled(),
                "kinds": [{"kind": k, "title": alerts.KINDS[k][1], "on": k in on} for k in alerts.available_kinds(u)]}

    def get(self, request):
        return Response(self._state(request))

    def patch(self, request):
        data = json_body(request)
        raw = data.get("kinds")
        if not isinstance(raw, list) or any(not isinstance(k, str) for k in raw):
            raise field_error("kinds", "invalid", "Send the list of alerts you want.")
        if any(k not in alerts.KINDS for k in raw):
            raise field_error("kinds", "invalid", "Unknown alert.")
        chosen = alerts.set_kinds(request.user, raw)
        record("alerts.preferences", request=request, entity_type="alert_preference", metadata={"kinds": sorted(chosen)})
        return Response(self._state(request))
