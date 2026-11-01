"""Counts of security-relevant events for cron/monitoring. Exits 2 when a threshold is exceeded."""
import json
import sys
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.audit.models import AuditEvent


class Command(BaseCommand):
    help = "Print a JSON summary of recent security events; non-zero exit when thresholds are exceeded."

    def add_arguments(self, parser):
        parser.add_argument("--minutes", type=int, default=15)
        parser.add_argument("--max-failed-logins", type=int, default=50)
        parser.add_argument("--max-lockouts", type=int, default=5)
        parser.add_argument("--max-denied", type=int, default=100)
        parser.add_argument("--max-exports", type=int, default=10)

    def handle(self, *args, **o):
        since = timezone.now() - timedelta(minutes=o["minutes"])
        ev = AuditEvent.objects.filter(occurred_at__gte=since)
        report = {
            "window_minutes": o["minutes"],
            "failed_logins": ev.filter(action="auth.login", outcome="failure").count(),
            "lockouts": ev.filter(action="auth.login", metadata__reason__icontains="locked").count(),
            "denied": ev.filter(outcome="denied").count(),
            "exports": ev.filter(action__in=["personnel.export", "report.summary_export"], outcome="success").count(),
            "password_resets": ev.filter(action="auth.password_reset", outcome="success").count(),
            "accounts_disabled": ev.filter(action="user.disable").count(),
        }
        breaches = [name for name, limit in (("failed_logins", o["max_failed_logins"]), ("lockouts", o["max_lockouts"]),
                                             ("denied", o["max_denied"]), ("exports", o["max_exports"])) if report[name] > limit]
        report["breaches"] = breaches
        self.stdout.write(json.dumps(report))
        if breaches:
            sys.exit(2)
