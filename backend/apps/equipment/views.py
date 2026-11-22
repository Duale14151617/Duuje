import uuid

from django.db.models import Q
from django.http import Http404, HttpResponse
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record, record_read
from apps.core import crypto
from apps.core.concurrency import require_version
from apps.core.errors import field_error
from apps.core.params import json_body
from apps.vehicles.models import Vehicle

from . import services as svc
from .models import EquipmentItem, EquipmentPhoto, MountedWeaponCategory

READ = ("vehicles.view", "weapons.view", "equipment.manage")  # the catalogue is reference data: anyone who reads vehicles or weapons may read it


class _Page(PageNumberPagination):
    page_size = 25
    max_page_size = 100
    page_size_query_param = "page_size"


def _wcat(c):
    return {"id": str(c.pk), "code": c.code, "name_en": c.name_en, "name_so": c.name_so, "active": c.active, "sort_order": c.sort_order}


def _classification(i):
    if i.kind == EquipmentItem.Kind.VEHICLE_MODEL and i.vehicle_category_id:
        c = i.vehicle_category
        return {"id": str(c.pk), "code": c.code, "name_en": c.name_en, "name_so": c.name_so, "group": c.group}
    if i.weapon_category_id:
        return _wcat(i.weapon_category)
    return None


def brief(i):
    """Small form used by vehicles and armament rows."""
    return {"id": str(i.pk), "code": i.code, "name": i.name, "kind": i.kind, "verification": i.verification}


def _out(i, photo_id=None):
    return {**brief(i), "classification": _classification(i), "manufacturer": i.manufacturer, "description": i.description,
            "verification_note": i.verification_note, "verified_by": i.verified_by_username or None, "verified_at": i.verified_at,
            "source_ref": i.source_ref, "active": i.active, "photo_id": photo_id, "version": i.version}


def _photo_out(p):
    return {"id": str(p.pk), "caption": p.caption, "content_type": p.content_type, "size_bytes": p.size_bytes, "uploaded_at": p.uploaded_at, "uploaded_by": p.uploaded_by_username}


def _uid(v):
    try:
        return str(uuid.UUID(str(v)))
    except (ValueError, TypeError):
        return None


class EquipmentViewSet(viewsets.GenericViewSet):
    """Equipment Reference Catalogue. Reference data only: it records what equipment is, never who holds it."""

    permission_classes = [ScopedPermission]
    pagination_class = _Page
    parser_classes = [JSONParser, MultiPartParser]
    lookup_value_regex = r"[0-9A-Za-z\-]+"
    permission_map = {
        "list": (READ, "any"), "retrieve": (READ, "any"), "photo_image": (READ, "any"), "weapon_categories": (READ, "any"),
        "create": ("equipment.manage", "global"), "edit": ("equipment.manage", "global"), "specs": ("equipment.manage", "global"),
        "photo_upload": ("equipment.manage", "global"), "photo_withdraw": ("equipment.manage", "global"),
        "weapon_category_create": ("equipment.manage", "global"), "verify": ("equipment.verify", "global"),
    }

    def get_queryset(self):
        return EquipmentItem.objects.select_related("vehicle_category", "weapon_category")

    def get_object(self):
        key = self.kwargs["pk"]
        qs = self.get_queryset()
        obj = qs.filter(pk=_uid(key)).first() if _uid(key) else qs.filter(code=key.lower()).first()
        if obj is None or (not obj.active and not scope.can(self.request.user, "equipment.manage")):
            raise Http404
        return obj

    def _primary_photos(self, ids):
        out = {}
        for p in EquipmentPhoto.objects.filter(item_id__in=ids, withdrawn_at__isnull=True).order_by("uploaded_at").values("id", "item_id"):
            out.setdefault(p["item_id"], str(p["id"]))
        return out

    def list(self, request):
        p, qs = request.query_params, self.get_queryset()
        if not (p.get("include_inactive") == "1" and scope.can(request.user, "equipment.manage")):
            qs = qs.filter(active=True)
        if p.get("q"):
            q = p["q"].strip()[:60]
            qs = qs.filter(Q(name__icontains=q) | Q(manufacturer__icontains=q) | Q(code__icontains=q) | Q(description__icontains=q))
        if p.get("kind") in {k.value for k in EquipmentItem.Kind}:
            qs = qs.filter(kind=p["kind"])
        if p.get("classification"):  # a vehicle category code or a mounted-weapon category code
            qs = qs.filter(Q(vehicle_category__code=p["classification"]) | Q(weapon_category__code=p["classification"]))
        if p.get("verification") in {v.value for v in EquipmentItem.Verification}:
            qs = qs.filter(verification=p["verification"])
        page = self.paginate_queryset(qs.order_by("name"))
        record_read(request, "equipment.read_list", entity_type="equipment_catalogue", count=len(page))
        photos = self._primary_photos([i.pk for i in page])
        return self.get_paginated_response([_out(i, photos.get(i.pk)) for i in page])

    def retrieve(self, request, pk=None):
        i = self.get_object()
        record_read(request, "equipment.read_detail", entity_type="equipment_item", entity_id=i.pk)
        photos = list(i.photos.filter(withdrawn_at__isnull=True))
        vq = scope.unit_scope_q(request.user, "vehicles.view", "org_unit__")
        in_scope = Vehicle.objects.filter(vq, reference_model=i).exclude(status="decommissioned").count() if vq is not None else None
        d = _out(i, str(photos[0].pk) if photos else None)
        d.update({"specs": [{"name": s.name, "value": s.value, "unit": s.unit} for s in i.specs.all()], "photos": [_photo_out(x) for x in photos],
                  "vehicles_in_scope": in_scope, "created_by": i.created_by_username,
                  "capabilities": {"manage": scope.can(request.user, "equipment.manage"), "verify": scope.can(request.user, "equipment.verify")}})
        return Response(d)

    def create(self, request):
        return Response(_out(svc.create_item(request, json_body(request))), status=201)

    @action(detail=True, methods=["post"])
    def edit(self, request, pk=None):
        d = json_body(request)
        return Response(_out(svc.edit_item(request, self.get_object(), d, require_version(d))))

    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        d = json_body(request)
        return Response(_out(svc.verify_item(request, self.get_object(), d, require_version(d))))

    @action(detail=True, methods=["post"])
    def specs(self, request, pk=None):
        d = json_body(request)
        return Response(_out(svc.set_specs(request, self.get_object(), d, require_version(d))))

    @action(detail=True, methods=["post"], url_path="photos/upload")
    def photo_upload(self, request, pk=None):
        p = svc.add_photo(request, self.get_object(), request.data.get("caption"), request.FILES.get("file"))
        return Response(_photo_out(p), status=201)

    @action(detail=True, methods=["get"], url_path=r"photos/(?P<phid>[0-9a-f\-]{36})/image")
    def photo_image(self, request, pk=None, phid=None):
        i = self.get_object()
        p = EquipmentPhoto.objects.filter(pk=phid, item=i, withdrawn_at__isnull=True).first()
        if p is None:
            raise Http404
        record_read(request, "equipment.photo_view", entity_type="equipment_photo", entity_id=p.pk)
        resp = HttpResponse(crypto.decrypt_bytes(bytes(p.content_enc)), content_type=p.content_type)
        resp["X-Content-Type-Options"] = "nosniff"
        resp["Cache-Control"] = "private, max-age=300"
        return resp

    @action(detail=True, methods=["post"], url_path=r"photos/(?P<phid>[0-9a-f\-]{36})/withdraw")
    def photo_withdraw(self, request, pk=None, phid=None):
        i = self.get_object()
        p = EquipmentPhoto.objects.filter(pk=phid, item=i).first()
        if p is None:
            raise Http404
        svc.withdraw_photo(request, p, json_body(request).get("reason"))
        return Response({"ok": True})

    @action(detail=False, methods=["get"], url_path="weapon-categories")
    def weapon_categories(self, request):
        return Response({"results": [_wcat(c) for c in MountedWeaponCategory.objects.filter(active=True)]})

    @weapon_categories.mapping.post
    def weapon_category_create(self, request):
        d = json_body(request)
        code = str(d.get("code") or "").strip().lower()
        name = str(d.get("name_en") or "").strip()
        if not code or len(code) > 40 or not code.replace("_", "").isalnum():
            raise field_error("code", "invalid_code", "Use letters, digits and underscores.")
        if not name:
            raise field_error("name_en", "required", "Give the category a name.")
        if MountedWeaponCategory.objects.filter(code=code).exists():
            raise field_error("code", "code_in_use", "That code is already used.")
        c = MountedWeaponCategory.objects.create(code=code, name_en=name[:120], name_so=str(d.get("name_so") or "")[:120])
        record("equipment.weapon_category_create", request=request, entity_type="mounted_weapon_category", entity_id=c.pk, metadata={"code": code})
        return Response(_wcat(c), status=201)
