"""Run with: python manage.py check --deploy  (fails the release if any ERROR is reported)."""
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


def _db_settings():
    return settings.DATABASES["default"]


@register(Tags.security, deploy=True)
def deployment_checks(app_configs, **kwargs):
    out = []
    if settings.DEBUG:
        out.append(Error("DJANGO_DEBUG is on.", id="armyhq.E001"))
    if len(settings.SECRET_KEY) < 50 or settings.SECRET_KEY.startswith("dev-only"):
        out.append(Error("DJANGO_SECRET_KEY is missing, short or a development key.", id="armyhq.E002"))
    try:
        Fernet(settings.FIELD_ENCRYPTION_KEY.encode())
    except Exception:
        out.append(Error("FIELD_ENCRYPTION_KEY is not a valid Fernet key.", id="armyhq.E003"))
    if not settings.ALLOWED_HOSTS or "*" in settings.ALLOWED_HOSTS:
        out.append(Error("DJANGO_ALLOWED_HOSTS must list explicit host names.", id="armyhq.E004"))
    if not settings.CSRF_TRUSTED_ORIGINS or any(not o.startswith("https://") for o in settings.CSRF_TRUSTED_ORIGINS):
        out.append(Error("DJANGO_CSRF_TRUSTED_ORIGINS must list https:// origins.", id="armyhq.E005"))
    db = _db_settings()
    if "sqlite" in db.get("ENGINE", ""):
        out.append(Error("SQLite is for development only; use PostgreSQL.", id="armyhq.E006"))
    elif (db.get("OPTIONS") or {}).get("sslmode", "prefer") in ("disable", "allow", "prefer"):
        out.append(Warning("POSTGRES_SSLMODE should be 'require' or stronger.", id="armyhq.W001"))
    if not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE:
        out.append(Error("Session/CSRF cookies must be Secure.", id="armyhq.E007"))
    if settings.PERSONNEL_EXPORT_ENABLED or settings.REPORT_EXPORT_ENABLED:
        out.append(Warning("CSV exports are enabled: confirm institutional approval is on file.", id="armyhq.W002"))
    if settings.ENABLE_API_DOCS:
        out.append(Warning("API documentation endpoints are enabled.", id="armyhq.W003"))
    if settings.TRUST_PROXY_HEADERS and settings.NUM_PROXIES < 1:
        out.append(Error("TRUST_PROXY_HEADERS needs NUM_PROXIES >= 1.", id="armyhq.E008"))
    return out
