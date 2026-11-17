from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from rest_framework.permissions import AllowAny
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


# What the login page and header call this deployment. Public, read-only, no secrets.
PROFILES = {
    "army": {"name_en": "Puntland Defence Forces HQ", "name_so": "Taliska Ciidamada Difaaca Puntland", "short_name": "ARMY HQ"},
    "police": {"name_en": "Puntland Police Force HQ", "name_so": "Taliska Guud ee Booliska Puntland", "short_name": "POLICE HQ"},
}


class ProfileView(_Public):
    def get(self, request):
        profile = getattr(settings, "ARMYHQ_PROFILE", "army")
        return JsonResponse({"profile": profile, **PROFILES.get(profile, PROFILES["army"])})
