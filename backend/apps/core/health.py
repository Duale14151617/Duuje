"""The setup health check: one list that says what is configured, what is working and what has quietly stopped.

Read-only and free of secrets: each line is a status (ok / warn / bad) plus a short code the screen turns into a sentence. Nothing here
tests by changing data (the email test is a separate, explicit action).
"""
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from . import crypto
from .models import Heartbeat

BACKUP_STALE_HOURS = 36
CRON_STALE_HOURS = 26


def _line(code, status, **params):
    return {"code": code, "status": status, "params": params}


def _beat(name):
    row = Heartbeat.objects.filter(name=name).first()
    return row.at if row else None


def record_beat(name, detail=""):
    Heartbeat.objects.update_or_create(name=name, defaults={"at": timezone.now(), "detail": detail[:200]})


def _database():
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        return _line("database", "ok")
    except Exception:
        return _line("database", "bad")


def _cache():
    try:
        cache.set("health_probe", "1", 10)
        return _line("cache", "ok" if cache.get("health_probe") == "1" else "bad")
    except Exception:
        return _line("cache", "bad")


def _encryption():
    try:
        return _line("encryption", "ok" if crypto.decrypt(crypto.encrypt("probe")) == "probe" else "bad")
    except Exception:
        return _line("encryption", "bad")


def _email():
    backend = settings.EMAIL_BACKEND
    if backend.endswith("console.EmailBackend") or backend.endswith("locmem.EmailBackend"):
        return _line("email", "warn")  # nothing is really sent: sign-in recovery, alerts and reports by email will not arrive
    return _line("email", "ok")


def _job(code, name, hours):
    at = _beat(name)
    if at is None:
        return _line(code, "warn", never=True)
    stale = timezone.now() - at > timedelta(hours=hours)
    return _line(code, "bad" if stale else "ok", at=at.isoformat())


def _cron():
    token = getattr(settings, "SCHEDULES_CRON_TOKEN", "")
    if not token or len(token) < 24:
        return _line("scheduler", "warn", not_set=True)  # scheduled reports and the daily "due soon" digest cannot run
    return _job("scheduler", "cron", CRON_STALE_HOURS)


def _backup():
    return _job("backup", "backup", BACKUP_STALE_HOURS)


def _admins():
    from apps.accounts.access_review import review
    count = review()["findings"]["few_admins"]["count"]
    return _line("admins", "warn" if count else "ok")


def run():
    lines = [
        _database(), _cache(), _encryption(),
        _line("debug", "bad" if settings.DEBUG else "ok"),
        _line("cookies", "ok" if settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE else "bad"),
        _line("step_up", "ok" if settings.STEP_UP_MFA_REQUIRED else "warn"),
        _line("sample_data", "warn" if getattr(settings, "SAMPLE_DATA_ON", False) else "ok"),
        _email(), _cron(), _backup(), _admins(),
    ]
    order = {"bad": 0, "warn": 1, "ok": 2}
    return {"generated_at": timezone.now().isoformat(), "version": settings.APP_VERSION, "build": settings.APP_BUILD,
            "lines": sorted(lines, key=lambda x: order[x["status"]]),
            "problems": sum(1 for x in lines if x["status"] != "ok")}
