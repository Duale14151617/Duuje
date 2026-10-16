from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record
from apps.core.concurrency import require_version, versioned_update
from apps.core.errors import field_error
from apps.core.negotiation import IgnoreNegotiation
from apps.core.params import uuid_param
from apps.organization.models import OrganizationalUnit

from . import profile as profile_svc
from . import services as svc
from .models import ImportBatch, Personnel
from .serializers import (HistorySerializer, PersonnelCreateSerializer, PersonnelSerializer,
                          PersonnelUpdateSerializer, RankChangeSerializer, StatusChangeSerializer,
                          TransferSerializer)


def _filter(qs, request):
    p = request.query_params
    if p.get("q"):
        digits = svc.normalize_phone(p["q"])
        cond = Q(full_name__icontains=p["q"]) | Q(service_number__icontains=p["q"])
        if digits:
            cond |= Q(phone_key__contains=digits)
        qs = qs.filter(cond)
    for param, field in (("branch", "branch"), ("rank", "rank")):
        value = uuid_param(request, param)
        if value:
            qs = qs.filter(**{field: value})
    unit_id = uuid_param(request, "org_unit")
    if unit_id:
        unit = OrganizationalUnit.objects.filter(pk=unit_id).first()
        qs = qs.filter(org_unit__path__startswith=unit.path) if unit else qs.none()
    if p.get("status"):
        qs = qs.filter(status=p["status"])
    return qs


def _scoped(user, code):
    q = scope.unit_scope_q(user, code, "org_unit__")
    return Personnel.objects.none() if q is None else Personnel.objects.filter(q)


def _rule_to_400(exc):
    return field_error(exc.field, exc.code)


class PersonnelViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    throttle_scope = None  # set per action for imports/exports
    serializer_class = PersonnelSerializer
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": ("personnel.view", "any"), "retrieve": ("personnel.view", "unit"),
        "history": ("personnel.view", "unit"),
        "photo": ("personnel.view", "unit"), "photo_upload": ("personnel.manage", "unit"),
        "profile": ("personnel.manage", "unit"),
        "create": ("personnel.manage", "any"), "partial_update": ("personnel.manage", "unit"),
        "transfer": ("personnel.manage", "unit"), "change_rank": ("personnel.manage", "unit"),
        "change_status": ("personnel.manage", "unit"),
        "import_preview": ("personnel.import", "any"), "import_commit": ("personnel.import", "any"),
        "export": ("personnel.export", "any"),
    }

    def scope_unit(self, obj):
        return obj.org_unit

    def get_queryset(self):
        # Scope lives in the queryset: out-of-scope people are simply not found.
        return _filter(_scoped(self.request.user, "personnel.view"), self.request).select_related(
            "branch", "org_unit", "rank")

    def _out(self, person):
        person = Personnel.objects.select_related("branch", "org_unit", "rank").get(pk=person.pk)
        return Response(PersonnelSerializer(person).data)

    # --- create / edit ---------------------------------------------------
    def create(self, request, *args, **kwargs):
        ser = PersonnelCreateSerializer(data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        with transaction.atomic():
            person = svc.create_personnel(
                request.user, full_name=d["full_name"], phone=d.get("phone", ""), service_number=d.get("service_number"),
                org_unit=d["org_unit"], rank=d["rank"], status=d["status"], effective_date=d.get("effective_date"))
            record("personnel.create", request=request, entity_type="personnel", entity_id=person.pk,
                   metadata={"unit": str(person.org_unit_id), "duplicate_confirmed": bool(d.get("confirm_duplicate"))})
        resp = self._out(person)
        resp.status_code = 201
        return resp

    def partial_update(self, request, *args, **kwargs):
        person = self.get_object()
        ser = PersonnelUpdateSerializer(person, data=request.data, partial=True, context={"request": request})
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            person = ser.save()
            record("personnel.update", request=request, entity_type="personnel", entity_id=person.pk,
                   metadata={"fields": sorted(k for k in ser.validated_data if k != "confirm_duplicate")})
        return self._out(person)

    # --- tracked changes (each writes effective-dated history) -----------
    def _workflow(self, request, serializer_cls, field, audit_action):
        person = self.get_object()
        ser = serializer_cls(person, data=request.data, context={"request": request})
        ser.is_valid(raise_exception=True)
        expected = require_version(request.data)
        d = ser.validated_data
        day = d.get("effective_date") or date.today()
        reason = d.get("reason", "")
        with transaction.atomic():
            if field == "org_unit":
                new = d["org_unit"]
                changes = {"org_unit": new, "branch": new.branch}
                old_ref, new_ref, old_l, new_l = str(person.org_unit_id), str(new.pk), person.org_unit.name_en, new.name_en
            elif field == "rank":
                new = d["rank"]
                changes = {"rank": new}
                old_ref, new_ref = str(person.rank_id), str(new.pk)
                old_l, new_l = svc.rank_label(person.rank), svc.rank_label(new)
            else:
                changes = {"status": d["status"]}
                old_ref, new_ref, old_l, new_l = person.status, d["status"], person.status, d["status"]
            updated = versioned_update(person, changes, expected)
            svc.add_history(updated, field, old_ref, new_ref, old_l, new_l, day, reason, request.user)
            record(audit_action, request=request, entity_type="personnel", entity_id=updated.pk,
                   metadata={"from": old_ref, "to": new_ref, "effective_date": day.isoformat()})
        return self._out(updated)

    @action(detail=True, methods=["post"])
    def transfer(self, request, pk=None):
        return self._workflow(request, TransferSerializer, "org_unit", "personnel.transfer")

    @action(detail=True, methods=["post"], url_path="change-rank")
    def change_rank(self, request, pk=None):
        return self._workflow(request, RankChangeSerializer, "rank", "personnel.change_rank")

    @action(detail=True, methods=["post"], url_path="change-status")
    def change_status(self, request, pk=None):
        return self._workflow(request, StatusChangeSerializer, "status", "personnel.change_status")

    @action(detail=True, methods=["get"])
    def history(self, request, pk=None):
        person = self.get_object()
        return Response(HistorySerializer(person.history.all(), many=True).data)

    # --- sensitive profile: photo, blood type, weapon ID, emergency contact (encrypted at rest) ----------
    @action(detail=True, methods=["get", "patch"])
    def profile(self, request, pk=None):
        person = self.get_object()
        if request.method == "PATCH":
            ser = profile_svc.ProfileSerializer(data=request.data, partial=True)
            ser.is_valid(raise_exception=True)
            fields = profile_svc.save(person, ser.validated_data)
            record("personnel.profile_update", request=request, entity_type="personnel", entity_id=person.pk,
                   metadata={"fields": fields})  # field names only, never values
        else:
            record("personnel.profile_view", request=request, entity_type="personnel", entity_id=person.pk)
        return Response(profile_svc.read(person))

    @action(detail=True, methods=["get"], content_negotiation_class=IgnoreNegotiation)
    def photo(self, request, pk=None):
        person = self.get_object()
        jpeg = profile_svc.read_photo(person)
        if jpeg is None:
            return HttpResponse(status=404)
        resp = HttpResponse(jpeg, content_type="image/jpeg")
        resp["Cache-Control"] = "private, no-store"
        resp["Content-Disposition"] = 'inline; filename="photo.jpg"'
        return resp

    @action(detail=True, methods=["post"], url_path="photo/upload", parser_classes=[MultiPartParser])
    def photo_upload(self, request, pk=None):
        person = self.get_object()
        upload = request.FILES.get("photo")
        if upload is None:
            raise field_error("photo", "photo_required", "Choose a photo.")
        profile_svc.save_photo(person, profile_svc.process_photo(upload))
        record("personnel.photo_update", request=request, entity_type="personnel", entity_id=person.pk)
        return Response({"has_photo": True})

    # --- safe import: preview -> commit -----------------------------------
    @action(detail=False, methods=["post"], url_path="import/preview", parser_classes=[MultiPartParser], throttle_scope="bulk")
    def import_preview(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            raise field_error("file", "file_required", "Choose a CSV file.")
        try:
            rows = svc.parse_csv(upload)
        except svc.RuleError as exc:
            raise _rule_to_400(exc)
        results = svc.validate_import_rows(request.user, rows)
        valid = sum(1 for r in results if not r["errors"])
        with transaction.atomic():
            batch = ImportBatch.objects.create(
                created_by=request.user, rows=rows, total=len(rows), valid_count=valid,
                expires_at=timezone.now() + timedelta(hours=1))
            record("personnel.import_preview", request=request, entity_type="import_batch", entity_id=batch.pk,
                   metadata={"rows": len(rows), "valid": valid})
        return Response({
            "batch_id": str(batch.pk), "total": len(rows), "valid": valid, "can_commit": valid == len(rows),
            "rows": [{"row": r["row"], "errors": r["errors"]} for r in results],  # no personal data echoed back
        })

    @action(detail=False, methods=["post"], url_path="import/commit", throttle_scope="bulk")
    def import_commit(self, request):
        batch_id = request.data.get("batch_id")
        try:
            batch = ImportBatch.objects.filter(
                pk=batch_id, created_by=request.user, status=ImportBatch.Status.PREVIEW,
                expires_at__gt=timezone.now()).first()
        except (ValueError, Exception):  # malformed id
            batch = None
        if batch is None:
            return Response({"code": "batch_not_found", "detail": "Preview not found or expired."}, status=404)
        rows = batch.rows
        results = svc.validate_import_rows(request.user, rows)  # re-check: data and scope may have changed
        if any(r["errors"] for r in results):
            return Response({"code": "import_has_errors", "detail": "Fix the file and preview again.",
                             "rows": [{"row": r["row"], "errors": r["errors"]} for r in results]}, status=409)
        with transaction.atomic():
            created = svc.commit_import(request.user, rows, results)
            ImportBatch.objects.filter(pk=batch.pk).update(status=ImportBatch.Status.COMMITTED, rows=[])
            record("personnel.import_commit", request=request, entity_type="import_batch", entity_id=batch.pk,
                   metadata={"created": created})
        return Response({"created": created})

    # --- controlled export ---------------------------------------------------
    @action(detail=False, methods=["get"], content_negotiation_class=IgnoreNegotiation, throttle_scope="bulk")
    def export(self, request):
        if not settings.PERSONNEL_EXPORT_ENABLED:
            record("personnel.export", request=request, outcome="denied", entity_type="personnel",
                   metadata={"reason": "export_disabled"})
            raise PermissionDenied("Exports are not enabled.", code="export_disabled")
        qs = _filter(_scoped(request.user, "personnel.export"), request)
        count = qs.count()
        if count > 5000:
            return Response({"code": "export_too_large", "detail": "Narrow the filters."}, status=400)
        body = svc.export_csv(qs)
        record("personnel.export", request=request, entity_type="personnel", metadata={
            "rows": count, "filters": {k: v for k, v in request.query_params.items() if k != "page"}})
        resp = HttpResponse(body, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="personnel.csv"'
        resp["Cache-Control"] = "no-store"
        return resp
