import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


DEBUG = os.environ.get("DJANGO_DEBUG", "false").lower() == "true"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is not true.")
    SECRET_KEY = "dev-only-insecure-key"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "corsheaders",
    "rest_framework",
    "routing",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# The API is a stateless calculator; nothing is persisted.
DATABASES: dict[str, dict[str, str]] = {}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "truck-routing",
        "OPTIONS": {"MAX_ENTRIES": 20000},
    }
}

USE_TZ = True
TIME_ZONE = "UTC"

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOW_METHODS = ["GET", "POST", "OPTIONS"]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 0 if DEBUG else 86400
CSRF_COOKIE_SECURE = not DEBUG
SILENCED_SYSTEM_CHECKS = [
    # The hosting edge redirects HTTP to HTTPS before requests reach Django.
    "security.W008",
    # Served from a platform subdomain: subdomain and preload HSTS policy belong to the
    # domain owner, not this app.
    "security.W005",
    "security.W021",
]

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "routing.views.exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "plan": os.environ.get("THROTTLE_PLAN", "20/min"),
        "heatmap": os.environ.get("THROTTLE_HEATMAP", "20/min"),
        "geocode": os.environ.get("THROTTLE_GEOCODE", "60/min"),
    },
    # Without a fixed proxy count DRF keys throttles on the whole X-Forwarded-For
    # header, which a client can vary to dodge the limit.
    "NUM_PROXIES": int(os.environ["NUM_PROXIES"]) if os.environ.get("NUM_PROXIES") else None,
}

TOMTOM_API_KEY = os.environ.get("TOMTOM_API_KEY", "")
HEATMAP_MAX_CELLS = int(os.environ.get("HEATMAP_MAX_CELLS", "300"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact_secrets": {"()": "routing.log_redaction.RedactSecretsFilter"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "filters": ["redact_secrets"]},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
