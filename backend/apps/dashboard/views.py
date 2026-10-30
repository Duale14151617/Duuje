import uuid
from collections import defaultdict
from datetime import datetime, time, timedelta

from django.db.models import Count, F, Q
from django.db.models.functions import TruncDate
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
from apps.organization.models import OrganizationalUnit
from apps.personnel.models import Personnel
from apps.training.models import TrainingRecord
from apps.ranks.models import Rank
from apps.workflows.models import Submission


def personnel_by_region(people):
    """Headcount per region for the people the caller may already see (`people` is scope-filtered by the caller).

    A unit's region is the second segment of its materialised path (HQ / region / ...). Units that sit outside any region
    (system headquarters, the Army headquarters command) are grouped into one row with code None."""
    rows = (people.order_by().values("org_unit__path")
            .annotate(total=Count("id"), active=Count("id", filter=Q(status="active"))))
    tally = defaultdict(lambda: [0, 0])
    for r in rows:
        parts = [p for p in r["org_unit__path"].split("/") if p]
        slot = tally[parts[1] if len(parts) > 1 else ""]
        slot[0] += r["total"]
        slot[1] += r["active"]
    regions = {u.pk.hex: u for u in OrganizationalUnit.objects.filter(
        pk__in=[uuid.UUID(k) for k in tally if k], level="region")}
    merged = defaultdict(lambda: [0, 0])
    for key, (total, active) in tally.items():
        slot = merged[key if key in regions else ""]
        slot[0] += total
        slot[1] += active
    out = []
    for key, (total, active) in merged.items():
        region = regions.get(key)
        out.append({"code": region.code if region else None, "name_en": region.name_en if region else "",
                    "name_so": region.name_so if region else "", "total": total, "active": active})
    return sorted(out, key=lambda r: (-r["total"], r["code"] or ""))


def activity_series(days=7):
    """Audit events per local calendar day for the last `days` days (oldest first, today last), zero-filled.
    `issues` counts failed or denied outcomes, a subset of `events`."""
    first = timezone.localdate() - timedelta(days=days - 1)
    since = timezone.make_aware(datetime.combine(first, time.min))
    rows = (AuditEvent.objects.filter(occurred_at__gte=since).annotate(day=TruncDate("occurred_at")).order_by()
            .values("day").annotate(events=Count("id"), issues=Count("id", filter=Q(outcome__in=["failure", "denied"]))))
    by_day = {r["day"]: r for r in rows}
    series = []
    for i in range(days):
        day = first + timedelta(days=i)
        r = by_day.get(day)
        series.append({"date": day.isoformat(), "events": r["events"] if r else 0, "issues": r["issues"] if r else 0})
    return series


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
                "daily": activity_series(7),
            }
        if "personnel.view" in codes:
            pq = scope.unit_scope_q(user, "personnel.view", "org_unit__")
            people = Personnel.objects.filter(pq) if pq is not None else Personnel.objects.none()
            data["personnel"] = {"total": people.count(), "active": people.filter(status="active").count(),
                                 "by_region": personnel_by_region(people)}
        if "reports.view" in codes:
            block = {"my_open": Submission.objects.filter(
                submitter=user, status__in=["draft", "returned", "amended"]).count(),
                     "returned_for_correction": Submission.objects.filter(submitter=user, status="returned").count()}
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
        if scope.can(user, "payroll.view") or scope.can(user, "survivor.view"):
            from apps.payroll.views import payroll_summary  # counts only; individual salaries and family data never appear here
            full = payroll_summary()
            data["payroll"] = full if scope.can(user, "payroll.view") else {
                k: full[k] for k in ("survivor_cases", "beneficiaries_awaiting_verification", "allocations_awaiting_authorization")}
        return Response(data)


class DashboardActivityView(APIView):
    """Audit activity per day for the dashboard chart's range switch: the last 7 (default) or 30 days.
    Same permission as the audit block on the dashboard itself."""

    ALLOWED_DAYS = (7, 30)

    def get(self, request):
        if not scope.can(request.user, "audit.view"):
            record("access.denied", request=request, outcome="denied", entity_type="dashboard",
                   metadata={"permission": "audit.view"})
            raise PermissionDenied()
        try:
            days = int(request.query_params.get("days", 7))
        except (TypeError, ValueError):
            days = 7
        if days not in self.ALLOWED_DAYS:
            days = 7
        return Response({"daily": activity_series(days)})
