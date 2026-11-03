from datetime import date

from django.db import transaction
from django.db.models import Q
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record
from apps.core.concurrency import require_version
from apps.core.errors import field_error
from apps.core.params import uuid_param
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel

from . import services as svc
from .models import Course, TrainingRecord
from .serializers import (CourseSerializer, PersonBriefSerializer, StatusInputSerializer, TrainingCreateSerializer,
                          TrainingEditSerializer, TrainingRecordSerializer)


def _date(request, name):
    value = request.query_params.get(name)
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        raise field_error(name, "invalid_date")


class CourseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                    mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = CourseSerializer
    queryset = Course.objects.all()
    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    pagination_class = None
    permission_map = {
        "list": (("training.view", "training.configure"), "any"), "retrieve": (("training.view", "training.configure"), "any"),
        "create": ("training.configure", "global"), "partial_update": ("training.configure", "global"),
    }

    @transaction.atomic
    def perform_create(self, serializer):
        obj = serializer.save()
        record("course.create", request=self.request, entity_type="course", entity_id=obj.pk, metadata={"code": obj.code})

    @transaction.atomic
    def perform_update(self, serializer):
        obj = serializer.save()
        record("course.update", request=self.request, entity_type="course", entity_id=obj.pk)


class TrainingRecordViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = TrainingRecordSerializer
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": ("training.view", "unit"), "retrieve": ("training.view", "unit"),
        "create": ("training.manage", "any"), "partial_update": ("training.manage", "unit"),
        "set_status": ("training.manage", "unit"),
    }

    def scope_unit(self, obj):
        return obj.personnel.org_unit

    def get_queryset(self):
        q = scope.unit_scope_q(self.request.user, "training.view", "personnel__org_unit__")
        if q is None:
            return TrainingRecord.objects.none()
        qs = TrainingRecord.objects.filter(q).select_related("course", "personnel__org_unit")
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if uuid_param(self.request, "course"):
            qs = qs.filter(course=uuid_param(self.request, "course"))
        if uuid_param(self.request, "personnel"):
            qs = qs.filter(personnel=uuid_param(self.request, "personnel"))
        unit_id = uuid_param(self.request, "org_unit")
        if unit_id:
            unit = OrganizationalUnit.objects.filter(pk=unit_id).first()
            qs = qs.filter(personnel__org_unit__path__startswith=unit.path) if unit else qs.none()
        return qs

    def _out(self, rec, status=200):
        return Response(TrainingRecordSerializer(self.get_queryset().get(pk=rec.pk)).data, status=status)

    def create(self, request, *args, **kwargs):
        # Resolve the person through the caller's own training.manage scope: unknown and out-of-scope look identical.
        ser = TrainingCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        mq = scope.unit_scope_q(request.user, "training.manage", "org_unit__")
        person = Personnel.objects.filter(mq, pk=d["personnel"]).select_related("org_unit").first() if mq is not None else None
        if person is None:  # unknown and out-of-scope are indistinguishable
            record("access.denied", request=request, outcome="denied", entity_type="training_record",
                   metadata={"permission": "training.manage"})
            raise field_error("personnel", "person_not_found")
        rec = svc.enroll(request, person, d["course"], d["start_date"], d.get("end_date"), d["notes"])
        return self._out(rec, 201)

    def partial_update(self, request, *args, **kwargs):
        rec = self.get_object()
        ser = TrainingEditSerializer(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        return self._out(svc.edit(request, rec, dict(ser.validated_data), require_version(request.data)))

    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, pk=None):
        rec = self.get_object()
        ser = StatusInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        return self._out(svc.set_status(request, rec, d["status"], d.get("completed_on"), require_version(request.data)))


class TrainingPeopleViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Minimal roster lookup so training staff can pick a person without any personnel-record access."""

    serializer_class = PersonBriefSerializer
    permission_classes = [ScopedPermission]
    permission_map = {"list": ("training.manage", "any")}

    def get_queryset(self):
        q = scope.unit_scope_q(self.request.user, "training.manage", "org_unit__")
        if q is None:
            return Personnel.objects.none()
        qs = Personnel.objects.filter(q, status__in=["active", "on_leave"]).select_related("org_unit")
        term = self.request.query_params.get("q", "").strip()
        return qs.filter(Q(full_name__icontains=term)) if term else qs


class TrainingSummaryViewSet(viewsets.GenericViewSet):
    queryset = TrainingRecord.objects.none()
    pagination_class = None
    permission_classes = [ScopedPermission]
    permission_map = {"list": ("training.report", "any")}

    def list(self, request):
        return Response(svc.summary(request.user, {
            "course": uuid_param(request, "course"), "from": _date(request, "from"), "to": _date(request, "to")}))
