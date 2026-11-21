import csv
import hashlib
import io
import json
from datetime import date, timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.http import HttpResponse
from django.utils.dateparse import parse_date
from rest_framework import mixins, viewsets
from rest_framework.decorators import action as drf_action

from apps.accounts.permissions import ScopedPermission
from apps.accounts.stepup import require_fresh_mfa
from apps.core.errors import field_error
from apps.core.negotiation import IgnoreNegotiation

from .models import AuditEvent
from .services import record
from .serializers import AuditEventSerializer


class AuditEventViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Read-only. Requires audit.view at headquarters (unscoped) level."""

    serializer_class = AuditEventSerializer
    permission_classes = [ScopedPermission]
    permission_map = {"list": ("audit.view", "global"), "retrieve": ("audit.view", "global"), "export": ("audit.view", "global")}
    EXPORT_MAX = 10000
    throttle_scope = None  # set per action for the export

    def get_queryset(self):
        qs = AuditEvent.objects.all()
        p = self.request.query_params
        for param, field in (("action", "action"), ("entity_type", "entity_type"),
                             ("outcome", "outcome"), ("actor", "actor_username"),
                             ("correlation_id", "correlation_id")):
            if p.get(param):
                qs = qs.filter(**{field: p[param]})
        if p.get("action_prefix"):
            qs = qs.filter(action__startswith=p["action_prefix"])
        if p.get("who"):
            qs = qs.filter(actor_username__icontains=p["who"])
        if p.get("q"):  # one box: part of a person, action, entity type or record id
            qs = qs.filter(Q(actor_username__icontains=p["q"]) | Q(action__icontains=p["q"]) | Q(entity_type__icontains=p["q"])
                           | Q(entity_id__icontains=p["q"]))
        try:
            if p.get("from"):
                qs = qs.filter(occurred_at__gte=p["from"])
            if p.get("to"):
                # a bare date means "up to the end of that day", not "up to its first second"
                end = parse_date(p["to"]) if len(p["to"]) == 10 else None
                qs = qs.filter(occurred_at__lt=end + timedelta(days=1)) if isinstance(end, date) else qs.filter(occurred_at__lte=p["to"])
        except (DjangoValidationError, ValueError, OverflowError):
            raise field_error("from", "invalid_date", "Invalid date.")
        return qs

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        record("audit.read", request=request, entity_type="audit_event",
               metadata={"filters": {k: v for k, v in request.query_params.items() if k != "page"}, "page": request.query_params.get("page", "1")})
        return response

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        record("audit.read", request=request, entity_type="audit_event", entity_id=kwargs.get("pk"))
        return response

    @staticmethod
    def _cell(value):
        """Spreadsheet formula injection: a cell that starts with = + - @ would run as a formula when the file is opened."""
        text = "" if value is None else str(value)
        return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text

    @drf_action(detail=False, methods=["get"], content_negotiation_class=IgnoreNegotiation, throttle_scope="bulk")
    def export(self, request):
        """The filtered events as CSV (newest first, at most EXPORT_MAX rows). Needs a fresh authenticator check. The file's SHA-256 and
        the filters are written to the audit log itself, so a copy handed to an investigator can later be matched to the record."""
        require_fresh_mfa(request)
        qs = self.get_queryset().order_by("-occurred_at", "-id")
        count = qs.count()
        if count > self.EXPORT_MAX:
            return HttpResponse(json.dumps({"code": "export_too_large", "detail": f"More than {self.EXPORT_MAX} events match. Narrow the dates."}),
                                status=400, content_type="application/json")
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["occurred_at_utc", "actor", "action", "outcome", "entity_type", "entity_id", "ip_address", "correlation_id", "metadata"])
        for e in qs.iterator():
            w.writerow([e.occurred_at.isoformat(), self._cell(e.actor_username), e.action, e.outcome, e.entity_type, self._cell(e.entity_id),
                        e.ip_address or "", e.correlation_id, self._cell(json.dumps(e.metadata, sort_keys=True, ensure_ascii=False))])
        body = out.getvalue().encode("utf-8-sig")
        digest = hashlib.sha256(body).hexdigest()
        record("audit.export", request=request, entity_type="audit_event",
               metadata={"rows": count, "sha256": digest, "filters": {k: v for k, v in request.query_params.items() if k != "page"}})
        resp = HttpResponse(body, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="audit-log.csv"'
        resp["Cache-Control"] = "no-store"
        resp["X-Content-SHA256"] = digest
        return resp
