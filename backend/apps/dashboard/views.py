from datetime import timedelta

from django.db.models import F
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import scope
from apps.accounts.models import RoleAssignment, User
from apps.audit.models import AuditEvent
from apps.audit.services import record
from apps.logistics.models import Asset, StockLine
from apps.logistics.services import visible_q
from apps.personnel.models import Personnel
from apps.training.models import TrainingRecord
from apps.ranks.models import Rank
from apps.workflows.models import Submission


class DashboardView(APIView):
    """Role-aware: each block appears only if the user's permissions and scope allow it."""

    def get(self, request):
        user = request.user
        codes = scope.permission_codes(user)
        if "dashboard.view" not in codes:
            record("access.denied", request=request, outcome="denied", entity_type="dashboard",
                   metadata={"permission": "dashboard.view"})
            raise PermissionDenied()

        data = {}
        units = scope.scoped_units(user, "org.view")
        if "org.view" in codes:
            data["scope"] = {
                "units_in_scope": units.count(),
                "regions_in_scope": units.filter(level="region").count(),
                "branch_commands_in_scope": units.filter(level="branch_command").count(),
            }
        if "ranks.view" in codes:
            data["ranks"] = {
                "draft": Rank.objects.filter(approval_status="draft").count(),
                "approved": Rank.objects.filter(approval_status="approved").count(),
            }
        if scope.can(user, "users.view"):
            privileged_no_mfa = (
                RoleAssignment.objects.effective().filter(role__is_privileged=True, user__mfa_enabled=False)
                .values("user").distinct().count()
            )
            data["accounts"] = {
                "active": User.objects.filter(is_active=True).count(),
                "disabled": User.objects.filter(is_active=False).count(),
                "privileged_without_mfa": privileged_no_mfa,
            }
        if scope.can(user, "audit.view"):
            since = timezone.now() - timedelta(hours=24)
            recent = AuditEvent.objects.filter(occurred_at__gte=since)
            data["audit"] = {
                "events_24h": recent.count(),
                "failed_logins_24h": recent.filter(action="auth.login", outcome="failure").count(),
                "denied_24h": recent.filter(outcome="denied").count(),
            }
        if "personnel.view" in codes:
            pq = scope.unit_scope_q(user, "personnel.view", "org_unit__")
            people = Personnel.objects.filter(pq) if pq is not None else Personnel.objects.none()
            data["personnel"] = {"total": people.count(), "active": people.filter(status="active").count()}
        if "reports.view" in codes:
            block = {"my_open": Submission.objects.filter(
                submitter=user, status__in=["draft", "returned", "amended"]).count()}
            rq = scope.unit_scope_q(user, "reports.review", "org_unit__")
            if rq is not None:
                block["awaiting_review"] = Submission.objects.filter(
                    rq, status__in=["submitted", "under_review"]).exclude(submitter=user).count()
            data["reports"] = block
        if "logistics.view" in codes or "logistics.restricted" in codes:
            vq = visible_q(user, "org_unit__", "category__")
            data["logistics"] = {
                "low_stock": StockLine.objects.filter(vq, reorder_level__gt=0, quantity__lte=F("reorder_level")).count(),
                "assets_attention": Asset.objects.filter(vq, status__in=["missing", "lost"]).count(),
            }
        if "training.view" in codes:
            tq = scope.unit_scope_q(user, "training.view", "personnel__org_unit__")
            recs = TrainingRecord.objects.filter(tq) if tq is not None else TrainingRecord.objects.none()
            data["training"] = {"in_progress": recs.filter(status="in_progress").count(),
                                "enrolled": recs.filter(status="enrolled").count()}
        return Response(data)
