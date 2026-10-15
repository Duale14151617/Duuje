from django.db import transaction
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record
from apps.core.params import uuid_param

from .models import Rank
from .serializers import RankSerializer


class RankViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin,
                  mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = RankSerializer
    permission_classes = [ScopedPermission]
    http_method_names = ["get", "post", "patch", "head", "options"]
    permission_map = {
        "list": ("ranks.view", "any"), "retrieve": ("ranks.view", "any"),
        "create": ("ranks.manage", "global"), "partial_update": ("ranks.manage", "global"),
        "approve": ("ranks.approve", "global"), "unapprove": ("ranks.approve", "global"),
    }

    def get_queryset(self):
        qs = Rank.objects.select_related("branch")
        p = self.request.query_params
        if uuid_param(self.request, "branch"):
            qs = qs.filter(branch=uuid_param(self.request, "branch"))
        for field in ("category", "approval_status"):
            if p.get(field):
                qs = qs.filter(**{field: p[field]})
        if p.get("active") in ("true", "false"):
            qs = qs.filter(active=p["active"] == "true")
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        obj = serializer.save()
        record("rank.create", request=self.request, entity_type="rank", entity_id=obj.pk,
               metadata={"code": obj.code, "branch": str(obj.branch_id)})

    @transaction.atomic
    def perform_update(self, serializer):
        before = serializer.instance.approval_status
        obj = serializer.save()
        meta = {"fields": sorted(serializer.validated_data.keys())}
        if before == "approved" and obj.approval_status == "draft":
            meta["approval_voided"] = True
        record("rank.update", request=self.request, entity_type="rank", entity_id=obj.pk, metadata=meta)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def approve(self, request, pk=None):
        rank = Rank.objects.select_for_update().get(pk=self.get_object().pk)
        if not rank.name_so.strip():
            record("rank.approve", request=request, outcome="failure", entity_type="rank", entity_id=rank.pk,
                   metadata={"reason": "somali_name_missing"})
            return Response({"code": "somali_name_required",
                             "detail": "A Somali name is required before approval."}, status=409)
        rank.approval_status = Rank.Approval.APPROVED
        rank.approved_by = request.user
        rank.approved_at = timezone.now()
        rank.version += 1
        rank.save(update_fields=["approval_status", "approved_by", "approved_at", "version", "updated_at"])
        record("rank.approve", request=request, entity_type="rank", entity_id=rank.pk)
        return Response(RankSerializer(rank).data)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def unapprove(self, request, pk=None):
        rank = Rank.objects.select_for_update().get(pk=self.get_object().pk)
        rank.approval_status = Rank.Approval.DRAFT
        rank.approved_by = None
        rank.approved_at = None
        rank.version += 1
        rank.save(update_fields=["approval_status", "approved_by", "approved_at", "version", "updated_at"])
        record("rank.unapprove", request=request, entity_type="rank", entity_id=rank.pk)
        return Response(RankSerializer(rank).data)
