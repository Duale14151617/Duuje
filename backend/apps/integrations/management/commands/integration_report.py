"""Review and monitoring report for integration clients. Run from cron or by hand; exits 2 when attention is needed."""
import json
import sys
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts import scope as acl
from apps.analytics.services import SECTION_PERMISSION
from apps.audit.models import AuditEvent
from apps.integrations.models import IntegrationCall, IntegrationClient


class Command(BaseCommand):
    help = "JSON summary of integration clients: expiring, unused, recently failing. Non-zero exit when attention is needed."

    def add_arguments(self, parser):
        parser.add_argument("--expiring-days", type=int, default=14)
        parser.add_argument("--stale-days", type=int, default=60)
        parser.add_argument("--minutes", type=int, default=60, help="window for failure counts")
        parser.add_argument("--max-auth-failures", type=int, default=20)

    def handle(self, *args, **o):
        now = timezone.now()
        window = now - timedelta(minutes=o["minutes"])
        rows, live = [], []
        for c in IntegrationClient.objects.select_related("org_unit", "created_by").order_by("name"):
            state = c.unusable_reason(now) or "active"
            recent = IntegrationCall.objects.filter(client=c, at__gte=window)
            rows.append({
                "name": c.name, "key_prefix": c.key_prefix, "status": state, "scopes": c.scopes, "unit": c.org_unit.code,
                "expires_at": c.expires_at.isoformat(), "last_used_at": c.last_used_at.isoformat() if c.last_used_at else None,
                "created_by": c.created_by_username, "calls_in_window": recent.count(),
                "denied_in_window": recent.exclude(outcome="success").count()})
            if state == "active":
                live.append(c)
        expiring = [c.key_prefix for c in live if c.expires_at <= now + timedelta(days=o["expiring_days"])]
        stale_before = now - timedelta(days=o["stale_days"])
        stale = [c.key_prefix for c in live if (c.last_used_at or c.created_at) < stale_before]
        # A key must not outlive the access of the person who issued it (SECURITY_REVIEW_v2.0.md, R2).
        lost = []
        for c in live:
            creator = c.created_by
            if creator is None or not creator.is_active or not all(
                    acl.can(creator, SECTION_PERMISSION[sec], unit=c.org_unit) for sec in c.scopes if sec in SECTION_PERMISSION):
                lost.append(c.key_prefix)
        failures = AuditEvent.objects.filter(action="integration.auth_failed", occurred_at__gte=window).count()
        report = {"window_minutes": o["minutes"], "active": len(live), "expiring_soon": expiring, "unused_for_review": stale, "creator_access_lost": lost,
                  "auth_failures": failures, "clients": rows}
        attention = bool(expiring or stale or lost or failures > o["max_auth_failures"])
        report["needs_attention"] = attention
        self.stdout.write(json.dumps(report))
        if attention:
            sys.exit(2)
