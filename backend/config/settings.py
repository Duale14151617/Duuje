"""ARMY HQ settings. Every secret comes from environment variables."""
import base64
import hashlib
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY is required when DJANGO_DEBUG is off.")
    SECRET_KEY = "dev-only-insecure-key-never-use-in-production-0123456789abcdef"

# Fernet key used to encrypt MFA secrets at rest.
FIELD_ENCRYPTION_KEY = os.environ.get("FIELD_ENCRYPTION_KEY", "")
if not FIELD_ENCRYPTION_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY is required when DJANGO_DEBUG is off.")
    FIELD_ENCRYPTION_KEY = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()).decode()

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1" if DEBUG else "")
# Render injects this hostname automatically; include it without a self-referencing Blueprint variable.
render_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
if render_hostname and render_hostname not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_hostname)
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
TRUST_PROXY_HEADERS = env_bool("TRUST_PROXY_HEADERS", False)
if TRUST_PROXY_HEADERS:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "drf_spectacular",
    "apps.core",
    "apps.organization",
    "apps.accounts",
    "apps.ranks",
    "apps.personnel",
    "apps.workflows",
    "apps.logistics",
    "apps.training",
    "apps.audit",
    "apps.dashboard",
    "apps.analytics",
    "apps.integrations",
]

MIDDLEWARE = [
    "apps.core.middleware.CorrelationIdMiddleware",
    "apps.core.middleware.SecurityHeadersMiddleware",
    "apps.core.middleware.RequestSizeLimitMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.SessionEpochMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

# The Render demo image copies the Vite build here. WhiteNoise serves the built
# frontend assets from /assets/* while Django serves the SPA index at / and routes.
WHITENOISE_ROOT = BASE_DIR / "frontend_dist"
WHITENOISE_MIMETYPES = {".webmanifest": "application/manifest+json"}


def _whitenoise_headers(headers, path, url):
    """Installable-app files must always be revalidated so a new version reaches devices promptly."""
    if url in ("/sw.js", "/manifest.webmanifest", "/offline.html", "/offline.css", "/offline.js", "/index.html"):
        headers["Cache-Control"] = "no-cache"


WHITENOISE_ADD_HEADERS_FUNCTION = _whitenoise_headers
WSGI_APPLICATION = "config.wsgi.application"
AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

if env_bool("USE_SQLITE", False):
    if not DEBUG:
        raise ImproperlyConfigured("USE_SQLITE is for local development and tests only.")
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "armyhq"),
            "USER": os.environ.get("POSTGRES_USER", "armyhq_app"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
            "OPTIONS": {"sslmode": os.environ.get("POSTGRES_SSLMODE", "prefer")},
        }
    }

# Database-backed cache so login throttling is shared between gunicorn workers.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "django_cache",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 12}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Sessions and cookies
SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_AGE = int(os.environ.get("SESSION_IDLE_SECONDS", "1800"))
SESSION_ABSOLUTE_SECONDS = int(os.environ.get("SESSION_ABSOLUTE_SECONDS", "43200"))  # hard cap regardless of activity
MAX_REQUEST_BYTES = int(os.environ.get("MAX_REQUEST_BYTES", "2000000"))
if not DEBUG:  # __Host- cookies: Secure, Path=/, no Domain, so subdomains cannot overwrite them
    SESSION_COOKIE_NAME = "__Host-armyhq-session"
    CSRF_COOKIE_NAME = "__Host-armyhq-csrf"
SESSION_SAVE_EVERY_REQUEST = True  # sliding idle timeout
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_HTTPONLY = True  # the SPA gets its token from /auth/csrf/
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SECURE_HSTS_SECONDS = 0 if DEBUG else 31536000
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

# Without this DRF trusts a client-supplied X-Forwarded-For for throttling, which lets attackers rotate it
# to dodge rate limits. 0 = use the socket address; behind exactly N trusted proxies set NUM_PROXIES=N.
NUM_PROXIES = int(os.environ.get("NUM_PROXIES", "1")) if TRUST_PROXY_HEADERS else 0

REST_FRAMEWORK = {
    "NUM_PROXIES": NUM_PROXIES,
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    # Deny by default: every view must opt in to something weaker.
    "DEFAULT_PERMISSION_CLASSES": ["apps.accounts.permissions.IsFullyAuthenticated"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
        "rest_framework.throttling.ScopedRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "120/min",
        "user": "600/min",
        "login": os.environ.get("THROTTLE_LOGIN", "10/min"),
        "mfa": "10/min",
        "reset": "5/min",
        "bulk": os.environ.get("THROTTLE_BULK", "30/hour"),  # imports and exports
        "integration": os.environ.get("THROTTLE_INTEGRATION", "60/min"),  # per integration client (2.0)
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "ARMY HQ API",
    "DESCRIPTION": "Administrative platform API (draft, synthetic data only).",
    "VERSION": "2.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}
ENABLE_API_DOCS = env_bool("ENABLE_API_DOCS", DEBUG)

# Personnel exports stay off until the institution approves them (see docs/LIMITATIONS.md).
PERSONNEL_EXPORT_ENABLED = env_bool("PERSONNEL_EXPORT_ENABLED", False)

# Puntland Police module. OFF until the institution approves the pilot. When off: no Police ranks/departments are seeded and
# every personnel/report/training/logistics/analytics scope excludes Police units (enforced in apps/accounts/scope.py).
POLICE_MODULE_ENABLED = env_bool("POLICE_MODULE_ENABLED", False)

# Summary exports stay off until approved, like personnel exports.
REPORT_EXPORT_ENABLED = env_bool("REPORT_EXPORT_ENABLED", False)

# --- 2.0 -----------------------------------------------------------------------------------------------------
# Inbound, read-only integration API (aggregate analytics only). OFF until the institution approves each
# integration and its credential holder (see docs/IMPACT_ASSESSMENT_v2.0.md). When off, the /ext/ endpoints
# answer 404 and clients cannot be created, rotated or re-enabled.
INTEGRATIONS_ENABLED = env_bool("INTEGRATIONS_ENABLED", False)
INTEGRATION_MAX_DAYS = int(os.environ.get("INTEGRATION_MAX_DAYS", "365"))  # longest allowed credential lifetime
# Aggregate cells smaller than this are withheld from integration responses (small-number disclosure control).
INTEGRATION_MIN_CELL = int(os.environ.get("INTEGRATION_MIN_CELL", "5"))
# Integration keys may NOT narrow responses with ?unit= unless this is on: repeated per-unit queries are the easiest way
# to reconstruct small groups by subtraction (docs/SECURITY_REVIEW_v2.0.md, R3). Whole-key-scope aggregates are unaffected.
INTEGRATION_ALLOW_UNIT_FILTER = env_bool("INTEGRATION_ALLOW_UNIT_FILTER", False)
# Structural changes (unit-type catalogue: level names, order, parent/child links, strength standards) must go through a
# proposal that a *different* person approves; direct edits of unit types are refused while this is on (docs/STRUCTURE_APPROVAL.md).
STRUCTURE_CHANGES_REQUIRE_APPROVAL = env_bool("STRUCTURE_CHANGES_REQUIRE_APPROVAL", True)
# Failed credential attempts per source address before further attempts are refused for INTEGRATION_FAIL_WINDOW seconds.
INTEGRATION_FAIL_LIMIT = int(os.environ.get("INTEGRATION_FAIL_LIMIT", "20"))
INTEGRATION_FAIL_WINDOW = int(os.environ.get("INTEGRATION_FAIL_WINDOW", "600"))

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = False  # API returns codes; the frontend localises messages.
USE_TZ = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"cid": {"()": "apps.core.logging.CorrelationFilter"},
                "redact": {"()": "apps.core.logging.RedactingFilter"}},
    "formatters": {"std": {"format": "%(asctime)s %(levelname)s [%(correlation_id)s] %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "std", "filters": ["cid", "redact"]}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
}
