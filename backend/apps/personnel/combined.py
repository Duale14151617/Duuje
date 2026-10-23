"""Combined cross-service report: Army, Navy and Police strength side by side, aggregates only.

Needs `reports.combined` (headquarters-wide: command authority, super_admin). It is computed with exactly the same scope
rules as every other personnel-data report, so:
  * Police counts appear only while POLICE_MODULE_ENABLED is on and only for roles holding `police.cross_access`;
  * restricted units (CID) are left out unless the caller also holds `cid.access`, and the response says so.
No person-level rows are ever returned.
"""
from collections import defaultdict

from django.conf import settings
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.response import Response

from apps.accounts import scope
from apps.accounts.permissions import ScopedPermission
from apps.audit.services import record
from apps.organization.models import OrganizationalUnit, ServiceBranch

from .models import Personnel

SERVING = ~Q(status__in=[Personnel.Status.RETIRED, Personnel.Status.DISCHARGED])


def _named(obj):
    return {"id": str(obj.pk), "code": obj.code, "name_en": obj.name_en, "name_so": obj.name_so}


def build(user) -> dict:
    code = "reports.combined"
    pq = scope.unit_scope_q(user, code, "org_unit__")
    people = Personnel.objects.none() if pq is None else Personnel.objects.filter(pq)

    branches = {b.pk: b for b in ServiceBranch.objects.filter(active=True)}
    regions = {r.pk.hex: r for r in OrganizationalUnit.objects.filter(level=OrganizationalUnit.Level.REGION)}

    status_rows = people.order_by().values("branch_id", "status").annotate(n=Count("pk"))
    rank_rows = people.filter(SERVING).order_by().values("branch_id", "rank__category").annotate(n=Count("pk"))
    place_rows = people.filter(SERVING).order_by().values("branch_id", "org_unit__path").annotate(n=Count("pk"))

    per_branch = {bid: {"total": 0, "serving": 0, "by_status": defaultdict(int), "by_rank_category": defaultdict(int)}
                  for bid in branches}
    for row in status_rows:
        b = per_branch.get(row["branch_id"])
        if b is None:
            continue
        b["total"] += row["n"]
        b["by_status"][row["status"]] += row["n"]
        if row["status"] not in (Personnel.Status.RETIRED, Personnel.Status.DISCHARGED):
            b["serving"] += row["n"]
    for row in rank_rows:
        if row["branch_id"] in per_branch:
            per_branch[row["branch_id"]]["by_rank_category"][row["rank__category"]] += row["n"]

    per_region = defaultdict(lambda: defaultdict(int))  # region hex -> branch code -> serving
    for row in place_rows:
        parts = row["org_unit__path"].strip("/").split("/")
        b = branches.get(row["branch_id"])
        if len(parts) > 1 and b is not None:
            per_region[parts[1]][b.code] += row["n"]

    units = scope.scoped_units(user, "org.view") if scope.has_anywhere(user, "org.view") else OrganizationalUnit.objects.none()
    unit_counts = {row["branch__code"]: row["n"] for row in units.filter(active=True, branch__isnull=False)
                   .order_by().values("branch__code").annotate(n=Count("pk"))}

    out_branches = []
    for bid, b in sorted(per_branch.items(), key=lambda kv: branches[kv[0]].code):
        info = branches[bid]
        if b["total"] == 0 and info.code == "POLICE" and not settings.POLICE_MODULE_ENABLED:
            continue
        out_branches.append({**_named(info), "total": b["total"], "serving": b["serving"],
                             "by_status": dict(b["by_status"]), "by_rank_category": dict(b["by_rank_category"]),
                             "units": unit_counts.get(info.code, 0)})
    out_regions = []
    for hexid, counts in sorted(per_region.items(), key=lambda kv: regions[kv[0]].code if kv[0] in regions else kv[0]):
        if hexid in regions:
            out_regions.append({"region": _named(regions[hexid]), "serving_by_branch": dict(counts), "serving": sum(counts.values())})
    totals = {"total": sum(b["total"] for b in out_branches), "serving": sum(b["serving"] for b in out_branches)}
    return {
        "generated_at": timezone.now().isoformat(),
        "police_module_enabled": settings.POLICE_MODULE_ENABLED,
        # True when restricted units (CID) exist but this caller may not see inside them, so the totals leave them out.
        "excludes_restricted_units": "cid.access" not in scope.permission_codes(user)
        and OrganizationalUnit.objects.filter(restricted=True).exists(),
        "totals": totals, "branches": out_branches, "regions": out_regions,
    }


class CombinedReportViewSet(viewsets.GenericViewSet):
    """Army + Police (+ Navy) strength in one view. Read-only, aggregates only, audited on every view."""

    permission_classes = [ScopedPermission]
    pagination_class = None
    queryset = Personnel.objects.none()
    permission_map = {"list": ("reports.combined", "global")}

    def list(self, request):
        data = build(request.user)
        record("report.combined_view", request=request, entity_type="combined_report",
               metadata={"total": data["totals"]["total"], "branches": [b["code"] for b in data["branches"]]})
        return Response(data)
