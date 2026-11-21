"""Issued documents (ID cards and letters): issue, list, open for printing, revoke, and the public QR check."""

from django.http import Http404
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record, record_read
from apps.core.params import json_body
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel
from apps.vehicles.views import _uid

from . import services
from .models import IssuedDocument

VIEW, ISSUE = "credentials.view", "credentials.issue"


class IssuedDocumentViewSet(viewsets.GenericViewSet):
    permission_classes = [ScopedPermission]
    permission_map = {"list": (VIEW, "any"), "retrieve": (VIEW, "unit"), "id_card": (ISSUE, "any"), "letter": (ISSUE, "any"),
                      "revoke": (ISSUE, "unit")}
    lookup_value_regex = "[0-9a-fA-F-]{36}"

    def scope_unit(self, obj):
        return obj.org_unit

    def get_queryset(self):
        q = scope.unit_scope_q(self.request.user, VIEW, "org_unit__")
        qs = IssuedDocument.objects.select_related("org_unit", "issued_by", "personnel")
        return qs.none() if q is None else qs.filter(q)

    def list(self, request):
        qs = self.get_queryset()
        p = request.query_params
        if p.get("kind") in {k.value for k in IssuedDocument.Kind}:
            qs = qs.filter(kind=p["kind"])
        person = _uid(p.get("personnel"))
        if person:
            qs = qs.filter(personnel_id=person)
        rows = [services.brief(d) for d in qs[:200]]
        record_read(request, "credentials.list", entity_type="issued_document", count=len(rows))
        return Response({"results": rows})

    def retrieve(self, request, pk=None):
        doc = self.get_object()
        record("credentials.open", request=request, entity_type="issued_document", entity_id=doc.pk)
        return Response(services.detail(doc))

    @action(detail=False, methods=["post"], url_path="id-card")
    def id_card(self, request):
        data = json_body(request)
        pid = _uid(data.get("personnel"))
        person = Personnel.objects.select_related("org_unit").filter(pk=pid).first() if pid else None
        if person is None or not scope.can(request.user, ISSUE, unit=person.org_unit):
            raise Http404
        doc = services.issue_id_card(request.user, person)
        record("credentials.issue_id_card", request=request, entity_type="issued_document", entity_id=doc.pk, metadata={"personnel": str(person.pk)})
        return Response(services.detail(doc), status=201)

    @action(detail=False, methods=["post"], url_path="letter")
    def letter(self, request):
        data = json_body(request)
        uid = _uid(data.get("org_unit"))
        unit = OrganizationalUnit.objects.filter(pk=uid).first() if uid else None
        if unit is None or not scope.can(request.user, ISSUE, unit=unit):
            raise Http404
        doc = services.issue_letter(request.user, unit, subject=str(data.get("subject") or ""), body=str(data.get("body") or ""),
                                    recipient=str(data.get("recipient") or ""), signed_title=str(data.get("signed_title") or ""))
        record("credentials.issue_letter", request=request, entity_type="issued_document", entity_id=doc.pk)  # never the letter text
        return Response(services.detail(doc), status=201)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        doc = self.get_object()
        services.revoke(request.user, doc, str(json_body(request).get("reason") or ""))
        record("credentials.revoke", request=request, entity_type="issued_document", entity_id=doc.pk)
        return Response(services.detail(doc))


class VerifyView(APIView):
    """Public: anyone who scans the QR code (no sign-in). Throttled per address; an unknown code is a plain 404."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = "docverify"

    def get(self, request, code):
        code = (code or "").strip().upper()
        doc = IssuedDocument.objects.select_related("personnel").filter(code=code).first() if len(code) == services.CODE_LEN else None
        if doc is None:
            record("credentials.verify", request=request, outcome="denied", entity_type="issued_document", metadata={"result": "unknown"})
            raise Http404
        out = services.public_view(doc)
        record("credentials.verify", request=request, entity_type="issued_document", entity_id=doc.pk, metadata={"result": out["state"]})
        resp = Response(out)
        resp["Cache-Control"] = "no-store"
        return resp
