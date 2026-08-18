"""Django settings rendered by the BU-ISCIII deployment library.

This is an application-owned template. Keep the exact Django applications and
project behavior here; deployment-specific values are replaced from the
selected production or test installation settings file.
"""

import json
import os
from pathlib import Path


def env_bool(name, default=False):
    """Read a conventional boolean environment variable."""
    value = os.environ.get(name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name, default=""):
    """Read a comma-separated environment variable as a clean list."""
    return [
        item.strip()
        for item in os.environ.get(name, default).split(",")
        if item.strip()
    ]


def env_json(name, default):
    """Read a JSON environment value, falling back to a safe default."""
    value = os.environ.get(name, default)
    if not isinstance(value, str):
        return value
    if not value:
        return []
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return []


BASE_DIR = Path(__file__).resolve().parent.parent

# The renderer replaces this complete line and preserves the existing generated
# value during upgrades. Never commit a real production secret here.
SECRET_KEY = "PLACEHOLDER"
DEBUG = djangodebug
ALLOWED_HOSTS = [
    host.strip() for host in "djangoallowedhosts".split(",") if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip() for origin in "djangocsrftrustedorigins".split(",") if origin.strip()
]

# Add every local and third-party Django application used by the project.
# Application ordering can affect template overrides and startup behavior.
# Prefer an explicit AppConfig path when the application provides one:
#     "your_app.apps.YourAppConfig",
INSTALLED_APPS = [
    # Application-specific examples:
    # "your_app",
    # "rest_framework",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
    "rest_framework",
    "drf_spectacular",
    "django_crontab",
    # Required by the standard --script_before/--script_after deployment hooks.
    "django_extensions",
]

# Optional application display metadata. Define the exact structure consumed
# by the project; this is not a standard Django setting.
# APPS_NAMES = [
#     ["your_app", "Human-readable application name"],
# ]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "conf.urls"
WSGI_APPLICATION = "conf.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Add application-owned template directories when needed:
        # "DIRS": [BASE_DIR / "documents" / "service_templates"],
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "django.template.context_processors.i18n",
            ],
        },
    }
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "djangodbname",
        "USER": "djangouser",
        "PASSWORD": "djangopass",
        "HOST": "djangohost",
        "PORT": "djangoport",
        "CONN_MAX_AGE": dbconnmaxage,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_L10N = True
USE_TZ = False

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "static"
MEDIA_URL = "/documents/"
MEDIA_ROOT = BASE_DIR / "documents"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = "emailhostserver"
EMAIL_PORT = emailport
EMAIL_HOST_USER = "emailhostuser"
EMAIL_HOST_PASSWORD = "emailhostpassword"
EMAIL_USE_TLS = emailhosttls
DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", settingsconf_DEFAULT_FROM_EMAIL
)

# Keep the same CRONJOBS structure used by RELECOV Platform and iSkyLIMS.
# Containers render these jobs for Supercronic; bare-metal installations can
# register them with `python manage.py crontab add`.
LOG_CRONTAB_FILE = BASE_DIR / "logs" / "crontab.log"
CRONJOBS = [
    (
        "0 12 * * 5",
        "core.cron.refresh_databrowser_caches",
        f">>{LOG_CRONTAB_FILE}",
    ),
]
CRONTAB_COMMAND_SUFFIX = "2>&1"

# Optional upload limit in bytes. Django's default is 2.5 MiB.
# DATA_UPLOAD_MAX_MEMORY_SIZE = 10_000_000

# Apache overwrites this header before forwarding requests to Django.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Add application/framework-specific settings below, for example REST framework
# authentication, Swagger, Crispy Forms, logging or cleanup policies.

# Generic values generated for Django services that declare "API": true.
# Application code decides which CORS, throttling and documentation packages
# consume them; the deployment standard does not force a specific API library.
# Available from the standard API settings when PathoCore adopts CORS
# middleware. Defining the value alone would not enforce a CORS policy.
# API_CORS_ALLOWED_ORIGINS = env_list(
#     "API_CORS_ALLOWED_ORIGINS", settingsconf_API_CORS_ALLOWED_ORIGINS
# )
API_THROTTLE_RATE = os.environ.get("API_THROTTLE_RATE", settingsconf_API_THROTTLE_RATE)
# Available from the standard API settings when PathoCore implements a
# configurable public/authenticated/staff documentation access policy.
# API_DOCS_REQUIRE_STAFF = env_bool(
#     "API_DOCS_REQUIRE_STAFF", settingsconf_API_DOCS_REQUIRE_STAFF
# )

# Generic relying-party values generated for the application selected by the
# Keycloak add-on. Application authentication code consumes these OIDC values.
OIDC_AUTH_REQUIRED = env_bool("OIDC_AUTH_REQUIRED", settingsconf_OIDC_AUTH_REQUIRED)
OIDC_ISSUER = os.environ.get("OIDC_ISSUER", settingsconf_OIDC_ISSUER)
OIDC_JWKS_URL = os.environ.get("OIDC_JWKS_URL", settingsconf_OIDC_JWKS_URL)
OIDC_AUDIENCE = os.environ.get("OIDC_AUDIENCE", settingsconf_OIDC_AUDIENCE)
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", settingsconf_OIDC_CLIENT_ID)
OIDC_JWKS_CACHE_TTL_SECONDS = int(
    os.environ.get(
        "OIDC_JWKS_CACHE_TTL_SECONDS", settingsconf_OIDC_JWKS_CACHE_TTL_SECONDS
    )
)
OIDC_JWKS_TIMEOUT_SECONDS = int(
    os.environ.get("OIDC_JWKS_TIMEOUT_SECONDS", settingsconf_OIDC_JWKS_TIMEOUT_SECONDS)
)

KEYCLOAK_ADMIN_API_BASE_URL = os.environ.get(
    "KEYCLOAK_ADMIN_API_BASE_URL", settingsconf_KEYCLOAK_ADMIN_API_BASE_URL
)
KEYCLOAK_ADMIN_API_REALM = os.environ.get(
    "KEYCLOAK_ADMIN_API_REALM", settingsconf_KEYCLOAK_ADMIN_API_REALM
)
KEYCLOAK_ADMIN_API_TOKEN_REALM = os.environ.get(
    "KEYCLOAK_ADMIN_API_TOKEN_REALM", settingsconf_KEYCLOAK_ADMIN_API_TOKEN_REALM
)
KEYCLOAK_ADMIN_API_CLIENT_ID = os.environ.get(
    "KEYCLOAK_ADMIN_API_CLIENT_ID", settingsconf_KEYCLOAK_ADMIN_API_CLIENT_ID
)
KEYCLOAK_ADMIN_API_CLIENT_SECRET = os.environ.get(
    "KEYCLOAK_ADMIN_API_CLIENT_SECRET", settingsconf_KEYCLOAK_ADMIN_API_CLIENT_SECRET
)
KEYCLOAK_ADMIN_API_USERNAME = os.environ.get(
    "KEYCLOAK_ADMIN_API_USERNAME", settingsconf_KEYCLOAK_ADMIN_API_USERNAME
)
KEYCLOAK_ADMIN_API_PASSWORD = os.environ.get(
    "KEYCLOAK_ADMIN_API_PASSWORD", settingsconf_KEYCLOAK_ADMIN_API_PASSWORD
)
KEYCLOAK_ADMIN_API_TIMEOUT_SECONDS = int(
    os.environ.get(
        "KEYCLOAK_ADMIN_API_TIMEOUT_SECONDS",
        settingsconf_KEYCLOAK_ADMIN_API_TIMEOUT_SECONDS,
    )
)
KEYCLOAK_ADMIN_API_SEND_ACTION_EMAILS = env_bool(
    "KEYCLOAK_ADMIN_API_SEND_ACTION_EMAILS",
    settingsconf_KEYCLOAK_ADMIN_API_SEND_ACTION_EMAILS,
)
KEYCLOAK_ADMIN_API_ACTION_EMAIL_REDIRECT_URI = os.environ.get(
    "KEYCLOAK_ADMIN_API_ACTION_EMAIL_REDIRECT_URI",
    settingsconf_KEYCLOAK_ADMIN_API_ACTION_EMAIL_REDIRECT_URI,
)

# PathoCore's authentication backend predates the shared deployment contract
# and reads these Django setting names. Keep the application code stable while
# sourcing every token-validation value from the generic OIDC environment.
PATHOCORE_ENABLE_LEGACY_BASIC_AUTH = not OIDC_AUTH_REQUIRED
KEYCLOAK_ISSUER = OIDC_ISSUER
KEYCLOAK_JWKS_URL = OIDC_JWKS_URL
KEYCLOAK_AUDIENCE = OIDC_AUDIENCE
KEYCLOAK_CLIENT_ID = OIDC_CLIENT_ID
KEYCLOAK_JWKS_CACHE_TTL_SECONDS = OIDC_JWKS_CACHE_TTL_SECONDS
KEYCLOAK_JWKS_TIMEOUT_SECONDS = OIDC_JWKS_TIMEOUT_SECONDS

# Public endpoint and Keycloak administration behavior remain PathoCore-owned;
# only token validation uses the shared OIDC deployment contract.
PATHOCORE_ENABLE_PUBLIC_READ_ENDPOINTS = env_bool(
    "PATHOCORE_ENABLE_PUBLIC_READ_ENDPOINTS",
    settingsconf_PATHOCORE_ENABLE_PUBLIC_READ_ENDPOINTS,
)
KEYCLOAK_REALM = KEYCLOAK_ADMIN_API_REALM
KEYCLOAK_ADMIN_BASE_URL = KEYCLOAK_ADMIN_API_BASE_URL
KEYCLOAK_ADMIN_TOKEN_REALM = KEYCLOAK_ADMIN_API_TOKEN_REALM
KEYCLOAK_ADMIN_CLIENT_ID = KEYCLOAK_ADMIN_API_CLIENT_ID
KEYCLOAK_ADMIN_CLIENT_SECRET = KEYCLOAK_ADMIN_API_CLIENT_SECRET
KEYCLOAK_ADMIN_USERNAME = KEYCLOAK_ADMIN_API_USERNAME
KEYCLOAK_ADMIN_PASSWORD = KEYCLOAK_ADMIN_API_PASSWORD
KEYCLOAK_ADMIN_REQUEST_TIMEOUT_SECONDS = KEYCLOAK_ADMIN_API_TIMEOUT_SECONDS
KEYCLOAK_ADMIN_SEND_ACTION_EMAILS = KEYCLOAK_ADMIN_API_SEND_ACTION_EMAILS
KEYCLOAK_ADMIN_ACTION_EMAIL_REDIRECT_URI = KEYCLOAK_ADMIN_API_ACTION_EMAIL_REDIRECT_URI

PATHOCORE_ACCESS_REQUEST_USE_CASES = env_json(
    "PATHOCORE_ACCESS_REQUEST_USE_CASES",
    settingsconf_PATHOCORE_ACCESS_REQUEST_USE_CASES,
)
PATHOCORE_ACCESS_REQUEST_ADMIN_EMAILS = env_list(
    "PATHOCORE_ACCESS_REQUEST_ADMIN_EMAILS",
    settingsconf_PATHOCORE_ACCESS_REQUEST_ADMIN_EMAILS,
)

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "core.api.exceptions.pathocore_exception_handler",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.api.authentication.AdminBasicOrSessionAuthentication",
        "core.api.authentication.KeycloakJWTAuthentication",
    ]
    + (
        ["core.api.authentication.LegacyBasicOrSessionAuthentication"]
        if PATHOCORE_ENABLE_LEGACY_BASIC_AUTH
        else []
    ),
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": API_THROTTLE_RATE,
        "user": API_THROTTLE_RATE,
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "PathoCore API",
    "DESCRIPTION": (
        "PathoCore API for schema management, sample ingestion, metadata ingestion, "
        "and search/discovery endpoints used by multiple client projects."
    ),
    "VERSION": "v1",
    "CONTACT": {"name": "PathoCore API Team"},
    "SERVE_INCLUDE_SCHEMA": True,
    "GENERIC_ADDITIONAL_PROPERTIES": "dict",
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
    "SECURITY": [{"bearerAuth": []}, {"adminBasicAuth": []}]
    + ([{"basicAuth": []}] if PATHOCORE_ENABLE_LEGACY_BASIC_AUTH else []),
    "SCHEMA_PATH_PREFIX": "/v1",
    "SCHEMA_PATH_PREFIX_TRIM": True,
    "SERVERS": [{"url": "/v1", "description": "PathoCore API v1"}],
    "TAGS": [
        {"name": "Schemas", "description": "Upload, list and inspect JSON Schemas."},
        {"name": "Samples", "description": "Create and list samples."},
        {"name": "Sample Metadata", "description": "Ingest and query sample metadata."},
        {"name": "Sample History", "description": "Inspect sample state transitions."},
    ],
}

# Compatibility settings retained pending an application-level review.
X_FRAME_OPTIONS = "SAMEORIGIN"
ASGI_APPLICATION = "conf.asgi.application"
SWAGGER_SETTINGS = {
    "SECURITY_DEFINITIONS": {
        "adminBasicAuth": {"type": "basic"},
        "basic": {"type": "basic"},
        "bearerAuth": {"type": "apiKey", "name": "Authorization", "in": "header"},
    }
}
LOGIN_REDIRECT_URL = "/intranet/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
