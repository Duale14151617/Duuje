import csv
import io
from datetime import date

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record
from apps.core.concurrency import require_version, versioned_update
from apps.core.errors import field_error
from apps.core.negotiation import IgnoreNegotiation
from apps.core.params import uuid_param
from apps.organization.models import OrganizationalUnit
from apps.personnel.services import csv_safe

from . import services as svc
from .models import ApprovalAction, Notification, ReportType, Submission
from .serializers import (NotificationSerializer, ReportTypeSerializer, SubmissionDetailSerializer,
                          SubmissionListSerializer, SubmissionWriteSerializer)


class ReportTypeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                        mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = ReportTypeSerializer
    queryset = ReportType.objects.all()
    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = None
    permission_map = {
        "list": (("reports.view", "reports.configure"), "any"),
        "retrieve": (("reports.view", "reports.configure"), "any"),
        "create": ("reports.configure", "global"), "partial_update": ("reports.configure", "global"),
    }

    @transaction.atomic
    def perform_create(self, serializer):
        obj = serializer.save()
        record("report_type.create", request=self.request, entity_type="report_type", entity_id=obj.pk,
               metadata={"code": obj.code})

    @transaction.atomic
    def perform_update(self, serializer):
        obj = serializer.save()
        record("report_type.update", request=self.request, entity_type="report_type", entity_id=obj.pk,
               metadata={"fields": sorted(serializer.validated_data.keys())})


def _parse_date(value, name):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        raise field_error(name, "invalid_date")


class SubmissionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": ("reports.view", "unit"), "retrieve": ("reports.view", "unit"),
        "create": ("reports.submit", "any"), "partial_update": ("reports.submit", "unit"),
        "submit": ("reports.submit", "unit"), "amend": ("reports.submit", "unit"),
        "start_review": ("reports.review", "unit"), "approve": ("reports.review", "unit"),
        "reject": ("reports.review", "unit"), "return_": ("reports.review", "unit"),
    }

    def scope_unit(self, obj):
        return obj.org_unit

    def get_serializer_class(self):
        return SubmissionListSerializer if self.action == "list" else SubmissionDetailSerializer

    def get_queryset(self):
        user = self.request.user
        q = scope.unit_scope_q(user, "reports.view", "org_unit__")  # scope lives in the queryset
        if q is None:
            return Submission.objects.none()
        qs = Submission.objects.filter(q).select_related("report_type", "org_unit", "approved_revision")
        # A commander's periodic report is seen by others (the regional command above) only once it has been posted.
        qs = qs.exclude(Q(report_type__code="unit_situation_report", status="draft") & ~Q(submitter=user))
        if self.action != "list":
            qs = qs.prefetch_related("revisions", "actions")
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if uuid_param(self.request, "report_type"):
            qs = qs.filter(report_type=uuid_param(self.request, "report_type"))
        unit_id = uuid_param(self.request, "org_unit")
        if unit_id:
            unit = OrganizationalUnit.objects.filter(pk=unit_id).first()
            qs = qs.filter(org_unit__path__startswith=unit.path) if unit else qs.none()
        if p.get("mine") == "1":
            qs = qs.filter(submitter=user)
        if p.get("awaiting_review") == "1":
            rq = scope.unit_scope_q(user, "reports.review", "org_unit__")
            qs = qs.filter(rq, status__in=["submitted", "under_review"]).exclude(submitter=user) if rq is not None else qs.none()
        start, end = _parse_date(p.get("from"), "from"), _parse_date(p.get("to"), "to")
        if start:
            qs = qs.filter(period_end__gte=start)
        if end:
            qs = qs.filter(period_start__lte=end)
        return qs

    def _out(self, sub):
        fresh = (Submission.objects.select_related("report_type", "org_unit", "approved_revision")
                 .prefetch_related("revisions", "actions").get(pk=sub.pk))
        return Response(SubmissionDetailSerializer(fresh, context={"request": self.request}).data)

    def create(self, request, *args, **kwargs):
        ser = SubmissionWriteSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        figures = d.get("figures", {})
        if d["report_type"].code == "unit_situation_report":
            from apps.attendance.situation import compute_figures
            figures = compute_figures(request.user, d["org_unit"], d["period_start"], d["period_end"])
        with transaction.atomic():
            sub = Submission.objects.create(
                report_type=d["report_type"], org_unit=d["org_unit"], title=d["title"], period_start=d["period_start"],
                period_end=d["period_end"], body=d.get("body", ""), figures=figures,
                submitter=request.user, submitter_username=request.user.username)  # actor comes from the session only
            ApprovalAction.objects.create(submission=sub, action="create", to_status=sub.status, actor=request.user,
                                          actor_username=request.user.username)
            record("report.create", request=request, entity_type="submission", entity_id=sub.pk,
                   metadata={"type": d["report_type"].code, "unit": str(d["org_unit"].pk)})
        resp = self._out(sub)
        resp.status_code = 201
        return resp

    def partial_update(self, request, *args, **kwargs):
        sub = self.get_object()
        if sub.submitter_id != request.user.pk:
            raise PermissionDenied("Only the submitter can edit.", code="not_owner")
        if sub.status not in svc.EDITABLE:
            raise svc.NotEditable()
        ser = SubmissionWriteSerializer(sub, data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        expected = require_version(request.data)
        changes = {k: v for k, v in ser.validated_data.items() if k not in ("report_type", "org_unit")}
        if sub.report_type.code == "unit_situation_report":
            from apps.attendance.situation import compute_figures
            changes["figures"] = compute_figures(request.user, sub.org_unit, changes.get("period_start", sub.period_start),
                                                 changes.get("period_end", sub.period_end))
        with transaction.atomic():
            updated = versioned_update(sub, changes, expected)
            record("report.edit", request=request, entity_type="submission", entity_id=updated.pk,
                   metadata={"fields": sorted(changes.keys())})
        return self._out(updated)

    def _transition(self, request, name):
        sub = self.get_object()
        updated = svc.perform_transition(request, sub, name, require_version(request.data),
                                         str(request.data.get("comment") or ""))
        return self._out(updated)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._transition(request, "submit")

    @action(detail=True, methods=["post"], url_path="start-review")
    def start_review(self, request, pk=None):
        return self._transition(request, "start_review")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._transition(request, "approve")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._transition(request, "reject")

    @action(detail=True, methods=["post"], url_path="return")
    def return_(self, request, pk=None):
        return self._transition(request, "return")

    @action(detail=True, methods=["post"])
    def amend(self, request, pk=None):
        return self._transition(request, "amend")


class SummaryViewSet(viewsets.GenericViewSet):
    """Approved-content totals by region and consolidated, limited to the caller's scope."""

    throttle_scope = None  # set per action for exports
    queryset = Submission.objects.none()
    pagination_class = None
    permission_classes = [ScopedPermission]
    permission_map = {"list": ("reports.summary", "any"), "export": ("reports.export", "any")}

    def _params(self, request):
        p = {"report_type": uuid_param(request, "report_type")}
        start, end = _parse_date(request.query_params.get("from"), "from"), _parse_date(request.query_params.get("to"), "to")
        p["from"], p["to"] = start, end
        unit_id = uuid_param(request, "org_unit")
        if unit_id:
            unit = OrganizationalUnit.objects.filter(pk=unit_id).first()
            p["unit_path"] = unit.path if unit else "/none/"
        return p

    def list(self, request):
        params = self._params(request)
        data = svc.build_summary(request.user, params)
        keys = sorted({k for b in [data["consolidated"], *data["regions"]] for k in b["totals"]})
        return Response({**data, "figure_keys": keys, "filters": {
            "from": params["from"], "to": params["to"], "report_type": params["report_type"]}})

    @action(detail=False, methods=["get"], content_negotiation_class=IgnoreNegotiation, throttle_scope="bulk")
    def export(self, request):
        if not settings.REPORT_EXPORT_ENABLED:
            record("report.summary_export", request=request, outcome="denied", entity_type="summary",
                   metadata={"reason": "export_disabled"})
            raise PermissionDenied("Exports are not enabled.", code="export_disabled")
        params = self._params(request)
        data = svc.build_summary(request.user, params, code="reports.export")
        keys = sorted({k for b in [data["consolidated"], *data["regions"]] for k in b["totals"]})
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["region_code", "region_name", "submissions", *keys])
        for r in data["regions"]:
            w.writerow([csv_safe(r["region"]["code"]), csv_safe(r["region"]["name_en"]), r["submissions"],
                        *[r["totals"].get(k, 0) for k in keys]])
        w.writerow(["TOTAL", "Consolidated", data["consolidated"]["submissions"],
                    *[data["consolidated"]["totals"].get(k, 0) for k in keys]])
        record("report.summary_export", request=request, entity_type="summary", metadata={
            "regions": len(data["regions"]), "from": str(params["from"] or ""), "to": str(params["to"] or "")})
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="summary.csv"'
        resp["Cache-Control"] = "no-store"
        return resp


class NotificationViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Strictly the caller's own notifications; content is re-authorized at read time."""

    serializer_class = NotificationSerializer

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user).select_related("submission__org_unit")
        if self.request.query_params.get("unread") == "1":
            qs = qs.filter(read_at__isnull=True)
        return qs

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        n = self.get_object()
        if n.read_at is None:
            Notification.objects.filter(pk=n.pk).update(read_at=timezone.now())
        return Response(status=204)

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        Notification.objects.filter(recipient=request.user, read_at__isnull=True).update(read_at=timezone.now())
        return Response(status=204)

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        return Response({"count": Notification.objects.filter(recipient=request.user, read_at__isnull=True).count()})
