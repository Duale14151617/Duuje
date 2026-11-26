from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


def _db_ok():
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
        return True
    except Exception:
        return False


def _cache_ok():
    try:
        cache.set("health", "1", 5)
        return cache.get("health") == "1"
    except Exception:
        return False


def _migrations_ok():
    try:
        executor = MigrationExecutor(connection)
        return not executor.migration_plan(executor.loader.graph.leaf_nodes())
    except Exception:
        return False


class _Public(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = []  # monitors poll these


class LiveView(_Public):
    """Process is up. Touches nothing else."""

    def get(self, request):
        return JsonResponse({"status": "ok"})


class ReadyView(_Public):
    """Safe to receive traffic. Reports only booleans: no versions, hosts or error text."""

    def get(self, request):
        checks = {"database": _db_ok(), "cache": _cache_ok(), "migrations": _migrations_ok()}
        ok = all(checks.values())
        return JsonResponse({"status": "ok" if ok else "degraded", "checks": checks}, status=200 if ok else 503)


class SystemStatusView(APIView):
    """Footer facts for signed-in users: is the system healthy, which version is running, who to contact. Booleans and short strings
    only. The version and build are deliberately not on the public health or profile endpoints."""

    def get(self, request):
        healthy = _db_ok() and _cache_ok()
        return Response({"status": "operational" if healthy else "degraded", "version": settings.APP_VERSION,
                         "build": settings.APP_BUILD, "support": settings.SUPPORT_CONTACT})


# What the login page and header call this deployment. Public, read-only, no secrets.
PROFILES = {
    "army": {"name_en": "Puntland Defence Forces HQ", "name_so": "Puntland Defence Forces HQ", "short_name": "ARMY HQ"},
}


class ProfileView(_Public):
    def get(self, request):
        profile = getattr(settings, "ARMYHQ_PROFILE", "army")
        return JsonResponse({"profile": profile, **PROFILES.get(profile, PROFILES["army"])})


class HealthCheckView(APIView):
    """Setup health check for user administrators: what is configured, working, or has quietly stopped. No secrets."""

    def get(self, request):
        from apps.accounts import scope
        from apps.core import health
        if not scope.can(request.user, "users.view"):
            raise PermissionDenied()
        return Response(health.run())


class TestEmailView(APIView):
    """Send one test message to the caller's own verified address (the only way to know email really arrives)."""
    throttle_scope = "mfa"

    def post(self, request):
        from django.core.mail import send_mail
        from apps.accounts import scope
        from apps.audit.services import record
        if not scope.can(request.user, "users.view"):
            raise PermissionDenied()
        user = request.user
        if not (user.email and user.email_verified_at):
            return Response({"code": "email_not_verified", "detail": "Confirm your own email address first (Account page)."}, status=409)
        try:
            send_mail("Puntland Defence Forces HQ: test message", "This is a test from the system health check. If you can read it, email works.",
                      None, [user.email], fail_silently=False)
        except Exception:
            record("system.test_email", request=request, outcome="failure")
            return Response({"code": "send_failed", "detail": "The message could not be sent. Check the email settings."}, status=502)
        record("system.test_email", request=request)
        return Response({"sent_to": user.email})


class BackupHeartbeatView(APIView):
    """POST with header X-Cron-Token = BACKUP_HEARTBEAT_TOKEN, sent by the nightly backup job when it succeeds. 404 unless the token is set."""

    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_scope = "docverify"

    def post(self, request):
        import hmac
        from django.http import Http404
        from apps.core import health
        token = getattr(settings, "BACKUP_HEARTBEAT_TOKEN", "")
        given = request.headers.get("X-Cron-Token", "")
        if not token or len(token) < 24 or not hmac.compare_digest(given.encode(), token.encode()):
            raise Http404
        health.record_beat("backup", str(request.data.get("detail", "") if hasattr(request.data, "get") else ""))
        return Response(status=204)
