from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.models import RoleAssignment
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record
from apps.core.concurrency import require_version, versioned_update
from apps.core.errors import field_error
from apps.core.negotiation import IgnoreNegotiation
from apps.core.params import uuid_param
from apps.organization.models import OrganizationalUnit

from . import appointments as appt_svc
from . import death as death_svc
from . import profile as profile_svc
from . import records
from . import services as svc
from .models import AppointmentType, CommandAppointment, ImportBatch, Personnel
from .serializers import (AppointmentCreateSerializer, AppointmentEndSerializer, DeathReportSerializer, DeathWithdrawSerializer, HistorySerializer, PersonnelCreateSerializer, PersonnelSerializer,
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
    if p.get("no_supervisor") == "1":
        qs = qs.filter(supervisor__isnull=True)
    return qs


def _scoped(user, code):
    q = scope.unit_scope_q(user, code, "org_unit__")
    return Personnel.objects.none() if q is None else Personnel.objects.filter(q)


def _team(user):
    """Rows a `personnel.view_team` holder may see: their own record plus the people who report directly to them.

    The assignment's unit/branch limits and the Police / CID gates still apply (same engine as every other read), so a
    member can never reach a record their assignment could not reach. Nobody is found when the account is not linked to a
    personnel record: no link, no access."""
    q = scope.unit_scope_q(user, "personnel.view_team", "org_unit__")
    if q is None:
        return Personnel.objects.none()
    me = Personnel.objects.filter(account_id=user.pk).values_list("pk", flat=True).first()
    if me is None:
        return Personnel.objects.none()
    return Personnel.objects.filter(q).filter(Q(pk=me) | Q(supervisor_id=me))


def _readable(user):
    """Everything this user may read: unit-wide `personnel.view` scope, plus the own-record / direct-subordinate rows."""
    base = _scoped(user, "personnel.view")
    if not scope.has_anywhere(user, "personnel.view_team"):
        return base
    return Personnel.objects.filter(Q(pk__in=base.values("pk")) | Q(pk__in=_team(user).values("pk")))


def _brief(p):
    return {"id": str(p.pk), "full_name": p.full_name, "service_number": p.service_number,
            "rank": {"id": str(p.rank_id), "code": p.rank.code, "name_en": p.rank.name_en, "name_so": p.rank.name_so}}


def _reporting(user, person):
    """Reporting-line details for the detail screen. Only people who may read this person's unit see them, and each
    linked person is shown only if the viewer may read *that* person's unit too (otherwise just a marker)."""
    def seen(p):
        return scope.can(user, "personnel.view", unit=p.org_unit) or scope.can(user, "personnel.manage", unit=p.org_unit)
    if not seen(person):
        return {}
    sup = person.supervisor
    subs = list(person.subordinates.select_related("rank", "org_unit").order_by("-rank__sort_order", "full_name")[:100])
    out = {
        "supervisor": None if sup is None else (_brief(sup) if seen(sup) else {"id": str(sup.pk), "restricted": True}),
        "subordinates": [_brief(x) for x in subs if seen(x)],
    }
    if scope.can(user, "personnel.manage", unit=person.org_unit):
        out["account_username"] = person.account.username if person.account_id else None
    return out


def _detail(request, person):
    data = dict(PersonnelSerializer(person).data)
    data.update(_reporting(request.user, person))
    return data


def _audit_team_read(request, person, what):
    """Reading a subordinate's file through the team rule (not own file, not unit-wide access) is always audited."""
    user = request.user
    if person.account_id != user.pk and not scope.can(user, "personnel.view", unit=person.org_unit):
        record("personnel.view_subordinate", request=request, entity_type="personnel", entity_id=person.pk,
               metadata={"what": what})


def _rule_to_400(exc):
    return field_error(exc.field, exc.code)


VIEW = ("personnel.view", "personnel.view_team")  # unit-wide reader, or own-record + direct-subordinates reader


class PersonnelViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    throttle_scope = None  # set per action for imports/exports
    serializer_class = PersonnelSerializer
    permission_classes = [ScopedPermission]
    permission_map = {
        "list": (VIEW, "any"), "retrieve": (VIEW, "unit"),
        "history": (VIEW, "unit"),
        "photo": (VIEW, "unit"), "supervisor_candidates": ("personnel.manage", "unit"),
        "reporting_lines": ("personnel.manage", "any"), "photo_upload": ("personnel.manage", "unit"),
        "profile": ("personnel.manage", "unit"),
        "create": ("personnel.manage", "any"), "partial_update": ("personnel.manage", "unit"),
        "transfer": ("personnel.manage", "unit"), "change_rank": ("personnel.manage", "unit"),
        "change_status": ("personnel.manage", "unit"),
        "import_preview": ("personnel.import", "any"), "import_commit": ("personnel.import", "any"),
        "export": ("personnel.export", "any"),
        "cross_search": ("search.cross_service", "any"),
        "disciplinary": ("disciplinary.view", "unit"), "disciplinary_add": ("disciplinary.manage", "unit"),
        "appointment_types": (VIEW, "any"), "appointment_list": (VIEW, "any"), "person_appointments": (VIEW, "unit"),
        "appointment_add": ("personnel.appointments_manage", "unit"), "appointment_end": ("personnel.appointments_manage", "unit"),
        "death": (VIEW, "unit"), "death_report": ("personnel.record_death", "unit"),
        "death_confirm": ("personnel.confirm_death", "unit"),
        "death_withdraw": (("personnel.record_death", "personnel.confirm_death"), "unit"),
        # Death evidence may be attached by whoever reports the death; every other category still needs documents.manage.
        "documents": ("documents.view", "unit"), "document_upload": (("documents.manage", "personnel.record_death", "attendance.record"), "unit"),
        "document_download": ("documents.view", "unit"), "document_withdraw": ("documents.manage", "unit"),
    }

    def scope_unit(self, obj):
        return obj.org_unit

    def get_queryset(self):
        # Scope lives in the queryset: out-of-scope people are simply not found.
        return _filter(_readable(self.request.user), self.request).select_related(
            "branch", "org_unit", "rank")

    def retrieve(self, request, *args, **kwargs):
        person = self.get_object()
        _audit_team_read(request, person, "record")
        return Response(_detail(request, person))

    def _out(self, person):
        person = Personnel.objects.select_related("branch", "org_unit", "rank").get(pk=person.pk)
        return Response(_detail(self.request, person))

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
        if person.status == Personnel.Status.DIED:
            raise field_error("status", "person_deceased", "This person is deceased; the file is closed to changes.")
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
            if field == "status" and new_ref in ("retired", "discharged"):  # authority ends with service
                ended, revoked = appt_svc.end_all_for(request.user, updated, f"Status changed to {new_ref}")
                if ended:
                    record("personnel.appointments_ended", request=request, entity_type="personnel", entity_id=updated.pk,
                           metadata={"count": ended, "access_revoked": revoked, "reason": new_ref})
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
        _audit_team_read(request, person, "history")
        return Response(HistorySerializer(person.history.all(), many=True).data)

    # --- command appointments (separate from rank, assignment and application role) --------------------------
    @action(detail=False, methods=["get"], url_path="appointment-types")
    def appointment_types(self, request):
        rows = AppointmentType.objects.filter(active=True).select_related("unit_type")
        return Response({"results": [{"id": str(t.pk), "code": t.code, "name_en": t.name_en, "name_so": t.name_so,
                                      "unit_type": t.unit_type.code if t.unit_type_id else None,
                                      "exclusive": t.exclusive} for t in rows]})

    @action(detail=False, methods=["get"], url_path="appointments")
    def appointment_list(self, request):
        """Appointments of people the caller may read. ?org_unit=<id> (that unit and below), ?current=1."""
        qs = CommandAppointment.objects.filter(personnel__in=_readable(request.user).values("pk")).select_related(
            "appointment_type", "org_unit", "personnel__rank")
        unit = uuid_param(request, "org_unit")
        if unit:
            base = OrganizationalUnit.objects.filter(pk=unit).first()
            qs = qs.filter(org_unit__path__startswith=base.path) if base else qs.none()
        if request.query_params.get("current") == "1":
            qs = qs.filter(ended_at__isnull=True)
        return Response({"results": [appt_svc.out(a, with_person=True) for a in qs[:200]]})

    @action(detail=True, methods=["get"], url_path="appointments")
    def person_appointments(self, request, pk=None):
        person = self.get_object()
        _audit_team_read(request, person, "appointments")
        rows = person.appointments.select_related("appointment_type", "org_unit")
        return Response({"results": [appt_svc.out(a) for a in rows]})

    @action(detail=True, methods=["post"], url_path="appointments/add")
    def appointment_add(self, request, pk=None):
        person = self.get_object()
        ser = AppointmentCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        unit = OrganizationalUnit.objects.filter(pk=d["org_unit"]).first()
        atype = AppointmentType.objects.filter(pk=d["appointment_type"]).first()
        if unit is None or not scope.can(request.user, "personnel.appointments_manage", unit=unit):
            raise field_error("org_unit", "org_unit_invalid", "That unit cannot be used.")  # unknown and out-of-scope read alike
        if atype is None:
            raise field_error("appointment_type", "appointment_type_invalid", "That appointment cannot be used.")
        assignment = None
        if d.get("role_assignment"):
            assignment = RoleAssignment.objects.select_related("user").filter(pk=d["role_assignment"]).first()
            if assignment is None:
                raise field_error("role_assignment", "assignment_mismatch", "That access cannot be linked.")
        with transaction.atomic():
            try:
                appt = appt_svc.create(request.user, person, unit, atype, d["effective_from"], d.get("effective_to"),
                                       d.get("authority_ref", ""), assignment)
            except svc.RuleError as exc:
                raise _rule_to_400(exc)
            record("personnel.appointment_created", request=request, entity_type="personnel", entity_id=person.pk,
                   metadata={"appointment": str(appt.pk), "type": atype.code, "unit": unit.code,
                             "effective_from": d["effective_from"].isoformat(), "access_linked": assignment is not None})
        appt = CommandAppointment.objects.select_related("appointment_type", "org_unit").get(pk=appt.pk)
        return Response(appt_svc.out(appt), status=201)

    @action(detail=True, methods=["post"], url_path=r"appointments/(?P<appointment_id>[0-9a-f-]{36})/end")
    def appointment_end(self, request, pk=None, appointment_id=None):
        person = self.get_object()
        ser = AppointmentEndSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        appt = person.appointments.select_related("appointment_type", "org_unit", "role_assignment__user").filter(pk=appointment_id).first()
        if appt is None or not scope.can(request.user, "personnel.appointments_manage", unit=appt.org_unit):
            return Response({"code": "not_found", "detail": "Not found."}, status=404)
        with transaction.atomic():
            try:
                revoked = appt_svc.end(request.user, appt, ser.validated_data["reason"])
            except svc.RuleError as exc:
                raise _rule_to_400(exc)
            record("personnel.appointment_ended", request=request, entity_type="personnel", entity_id=person.pk,
                   metadata={"appointment": str(appt.pk), "access_revoked": revoked})
        appt.refresh_from_db()
        return Response(appt_svc.out(appt))

    # --- death: report -> evidence -> confirm (death is a status, never a deletion) -------------------------
    @action(detail=True, methods=["get"], url_path="death")
    def death(self, request, pk=None):
        person = self.get_object()
        can_act = any(scope.can(request.user, c, unit=person.org_unit)
                      for c in ("personnel.record_death", "personnel.confirm_death"))
        evid = death_svc.evidence_list(person) if can_act else None
        recs = person.death_records.all()
        return Response({"results": [death_svc.record_out(r, evid if r.state != "withdrawn" else None) for r in recs]})

    @action(detail=True, methods=["post"], url_path="death/report")
    def death_report(self, request, pk=None):
        person = self.get_object()
        ser = DeathReportSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            try:
                rec = death_svc.report(request.user, person, ser.validated_data["date_of_death"], ser.validated_data["note"])
            except svc.RuleError as exc:
                raise _rule_to_400(exc)
            record("personnel.death_reported", request=request, entity_type="personnel", entity_id=person.pk,
                   metadata={"death_record": str(rec.pk), "date_of_death": rec.date_of_death.isoformat()})
        return Response(death_svc.record_out(rec, death_svc.evidence_list(person)), status=201)

    @action(detail=True, methods=["post"], url_path="death/confirm")
    def death_confirm(self, request, pk=None):
        person = self.get_object()
        expected = require_version(request.data)
        rec = person.death_records.filter(state="reported").first()
        if rec is None:
            raise field_error("state", "death_not_pending", "There is no death report waiting for confirmation.")
        with transaction.atomic():
            try:
                updated, closed = death_svc.confirm(request.user, person, rec, expected)
            except svc.RuleError as exc:
                raise _rule_to_400(exc)
            record("personnel.death_confirmed", request=request, entity_type="personnel", entity_id=person.pk,
                   metadata={"death_record": str(rec.pk), "date_of_death": rec.date_of_death.isoformat(),
                             "reported_by": rec.reported_by_username, "account_closed": closed,
                             "evidence_count": death_svc.evidence(person).count()})
        return self._out(updated)

    @action(detail=True, methods=["post"], url_path="death/withdraw")
    def death_withdraw(self, request, pk=None):
        person = self.get_object()
        ser = DeathWithdrawSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        rec = person.death_records.filter(state="reported").first()
        if rec is None:
            raise field_error("state", "death_not_pending", "There is no death report that can be withdrawn.")
        with transaction.atomic():
            death_svc.withdraw(request.user, rec, ser.validated_data["reason"])
            record("personnel.death_withdrawn", request=request, entity_type="personnel", entity_id=person.pk,
                   metadata={"death_record": str(rec.pk)})
        return Response({"results": [death_svc.record_out(r) for r in person.death_records.all()]})

    # --- reporting lines -------------------------------------------------
    @action(detail=True, methods=["get"], url_path="supervisor-candidates")
    def supervisor_candidates(self, request, pk=None):
        """People the editor may pick as this person's supervisor: same service, active, strictly senior, in the editor's
        reach. The rules are the server's (check_supervisor), so the screen never offers a choice the save would refuse."""
        person = self.get_object()
        if not person.rank.active:
            return Response([])
        qs = _filter(_scoped(request.user, "personnel.view"), request).filter(
            branch_id=person.branch_id, status="active", rank__active=True,
            rank__sort_order__gt=person.rank.sort_order).exclude(pk=person.pk)
        rows = qs.select_related("rank").order_by("-rank__sort_order", "full_name")[:20]
        return Response([_brief(x) for x in rows])

    @action(detail=False, methods=["post"], url_path="reporting-lines", parser_classes=[MultiPartParser],
            throttle_scope="bulk")
    def reporting_lines(self, request):
        """Set supervisors / link logins for many existing people from a CSV (service_number, supervisor_service_number,
        account_username). dry_run=true (default) only reports; dry_run=false applies, all-or-nothing, and re-checks
        everything first because data and scope may have changed since the preview."""
        upload = request.FILES.get("file")
        if upload is None:
            raise field_error("file", "file_required", "Choose a CSV file.")
        try:
            rows = svc.parse_lines_csv(upload)
        except svc.RuleError as exc:
            raise _rule_to_400(exc)
        results = svc.validate_reporting_rows(request.user, rows)
        bad = [r for r in results if r["errors"]]
        report = [{"row": r["row"], "errors": r["errors"]} for r in results]
        apply = str(request.data.get("dry_run", "true")).lower() in ("false", "0", "no")
        if not apply:
            record("personnel.reporting_lines_preview", request=request, entity_type="personnel",
                   metadata={"rows": len(rows), "valid": len(rows) - len(bad)})
            return Response({"total": len(rows), "valid": len(rows) - len(bad), "can_commit": not bad, "rows": report})
        if bad:
            return Response({"code": "import_has_errors", "detail": "Fix the file and preview again.", "rows": report}, status=409)
        with transaction.atomic():
            changed = svc.apply_reporting_rows(request.user, results)
            record("personnel.reporting_lines", request=request, entity_type="personnel", metadata={"updated": changed})
        return Response({"total": len(rows), "valid": len(rows), "updated": changed})

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
        _audit_team_read(request, person, "photo")
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

    # --- disciplinary history: append-only, encrypted, every view and change audited ----------------------
    @action(detail=True, methods=["get"], url_path="disciplinary")
    def disciplinary(self, request, pk=None):
        person = self.get_object()
        items = records.list_disciplinary(person)
        record("disciplinary.view", request=request, entity_type="personnel", entity_id=person.pk,
               metadata={"count": len(items)})  # never any of the text
        return Response({"results": items})

    @action(detail=True, methods=["post"], url_path="disciplinary/add")
    def disciplinary_add(self, request, pk=None):
        """New entry, or - when `corrects` names an earlier entry - a correction. Entries are never edited or deleted."""
        person = self.get_object()
        ser = records.DisciplinaryInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            row = records.add_disciplinary(person, request.user, ser.validated_data)
            record("disciplinary.correct" if row.corrects_id else "disciplinary.add", request=request,
                   entity_type="personnel", entity_id=person.pk,
                   metadata={"record": str(row.pk), "corrects": str(row.corrects_id) if row.corrects_id else None})
        return Response({"id": str(row.pk)}, status=201)

    # --- service documents: upload / list / download / withdraw (encrypted, audited) ------------------------
    @action(detail=True, methods=["get"], url_path="documents")
    def documents(self, request, pk=None):
        person = self.get_object()
        items = records.list_documents(person)
        record("document.list", request=request, entity_type="personnel", entity_id=person.pk,
               metadata={"count": len(items)})
        return Response({"results": items})

    @action(detail=True, methods=["post"], url_path="documents/upload", parser_classes=[MultiPartParser])
    def document_upload(self, request, pk=None):
        person = self.get_object()
        ser = records.DocumentInputSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        # Besides documents.manage, two narrow rights may attach ONE kind of document: death evidence (whoever reports a death)
        # and attendance support (whoever records attendance). Every other category still needs documents.manage.
        narrow = {"death_evidence": "personnel.record_death", "attendance_support": "attendance.record"}
        cat = ser.validated_data["category"]
        if not scope.can(request.user, "documents.manage", unit=person.org_unit) and not (
                cat in narrow and scope.can(request.user, narrow[cat], unit=person.org_unit)):
            record("access.denied", request=request, outcome="denied", entity_type="personnel", entity_id=person.pk,
                   metadata={"action": "document_upload", "permission": "documents.manage"})
            raise PermissionDenied("You may attach only the kind of document your role allows.")
        upload = request.FILES.get("file")
        if upload is None:
            raise field_error("file", "file_required", "Choose a file.")
        raw, ctype = records.read_upload(upload)
        with transaction.atomic():
            doc = records.add_document(person, request.user, ser.validated_data, raw, ctype)
            record("document.upload", request=request, entity_type="personnel", entity_id=person.pk,
                   metadata={"document": str(doc.pk), "category": doc.category, "bytes": doc.size_bytes})
        return Response(records.document_out(doc), status=201)

    @action(detail=True, methods=["get"], url_path=r"documents/(?P<doc_id>[^/.]+)/download",
            content_negotiation_class=IgnoreNegotiation)
    def document_download(self, request, pk=None, doc_id=None):
        person = self.get_object()
        doc = records.get_document(person, doc_id)
        if doc is None:
            return HttpResponse(status=404)
        try:
            raw, filename = records.read_document(doc)
        except ValueError:  # stored bytes no longer match their checksum: report it, never serve it
            record("document.download", request=request, outcome="failure", entity_type="personnel",
                   entity_id=person.pk, metadata={"document": str(doc.pk), "reason": "checksum_mismatch"})
            return HttpResponse(status=500)
        record("document.download", request=request, entity_type="personnel", entity_id=person.pk,
               metadata={"document": str(doc.pk), "bytes": len(raw)})
        resp = HttpResponse(raw, content_type=doc.content_type)
        resp["Content-Disposition"] = f'attachment; filename="{filename}"'
        resp["Cache-Control"] = "private, no-store"
        resp["X-Content-Type-Options"] = "nosniff"
        return resp

    @action(detail=True, methods=["post"], url_path=r"documents/(?P<doc_id>[^/.]+)/withdraw")
    def document_withdraw(self, request, pk=None, doc_id=None):
        person = self.get_object()
        doc = records.get_document(person, doc_id)
        if doc is None:
            return Response({"code": "not_found", "detail": "Not found."}, status=404)
        if doc.category == "death_evidence" and person.status == Personnel.Status.DIED:
            raise field_error("document", "death_evidence_locked", "Evidence for a confirmed death cannot be withdrawn.")
        ser = records.WithdrawSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        with transaction.atomic():
            records.withdraw_document(doc, request.user, ser.validated_data["reason"])
            record("document.withdraw", request=request, entity_type="personnel", entity_id=person.pk,
                   metadata={"document": str(doc.pk)})
        return Response({"withdrawn": True})

    # --- cross-service search (Army + Police in one query) -------------------------------------------------
    @action(detail=False, methods=["get"], url_path="search")
    def cross_search(self, request):
        """One database query over every service. Needs `search.cross_service`, and still returns only people the caller may
        see: the personnel scope (branch limits, Police gate, restricted CID units) is applied to the same queryset, so a
        user can never find a record here that the personnel list would hide."""
        text = (request.query_params.get("q") or "").strip()
        if len(text) < 2:
            raise field_error("q", "q_too_short", "Type at least 2 characters.")
        base = _filter(_scoped(request.user, "personnel.view"), request)
        counts = {row["branch__code"]: row["n"] for row in base.order_by().values("branch__code").annotate(n=Count("pk"))}
        total = sum(counts.values())
        rows = base.select_related("branch", "org_unit", "rank").order_by("branch__code", "full_name")[:50]
        record("personnel.cross_search", request=request, entity_type="personnel",
               metadata={"query_length": len(text), "total": total})  # never the search text itself
        return Response({"counts": counts, "total": total, "truncated": total > 50,
                         "results": PersonnelSerializer(rows, many=True).data})

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
