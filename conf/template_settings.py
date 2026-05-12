from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / "subdir".
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_runtime_env_file():
    env_file = os.environ.get("PATHOCORE_ENV_FILE")
    env_path = Path(env_file) if env_file else BASE_DIR / ".env"
    if not env_path.is_file():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


_load_runtime_env_file()


# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/3.2/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = "PLACEHOLDER"


# SECURITY WARNING: don"t run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "localserverip", "dns_url"]

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core.apps.CoreConfig",
    "rest_framework",
    "drf_spectacular",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "pathocore_api.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "pathocore_api.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "USER": "djangouser",
        "PASSWORD": "djangopass",
        "PORT": "djangoport",
        "NAME": "pathocore_api",
        "HOST": "djangohost",
    },
}

# Password validation
# https://docs.djangoproject.com/en/3.2/ref/settings/#auth-password-validators

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

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.api.authentication.KeycloakJWTAuthentication",
    ]
    + (
        ["core.api.authentication.LegacyBasicOrSessionAuthentication"]
        if os.environ.get("PATHOCORE_ENABLE_LEGACY_BASIC_AUTH", "true").lower()
        in ("1", "true", "yes", "on")
        else []
    ),
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

PATHOCORE_ENABLE_LEGACY_BASIC_AUTH = os.environ.get(
    "PATHOCORE_ENABLE_LEGACY_BASIC_AUTH", "true"
).lower() in ("1", "true", "yes", "on")

# Keycloak setup
KEYCLOAK_ISSUER = os.environ.get("KEYCLOAK_ISSUER", "").strip()
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "").strip()
KEYCLOAK_AUDIENCE = os.environ.get("KEYCLOAK_AUDIENCE", "").strip()
KEYCLOAK_JWKS_URL = os.environ.get("KEYCLOAK_JWKS_URL", "").strip()
KEYCLOAK_JWKS_CACHE_TTL_SECONDS = int(
    os.environ.get("KEYCLOAK_JWKS_CACHE_TTL_SECONDS", "300")
)
KEYCLOAK_JWKS_TIMEOUT_SECONDS = int(
    os.environ.get("KEYCLOAK_JWKS_TIMEOUT_SECONDS", "5")
)

SPECTACULAR_SETTINGS = {
    "TITLE": "PathoCore API",
    "DESCRIPTION": (
        "PathoCore API for schema management, sample ingestion, metadata ingestion, "
        "and search/discovery endpoints used by multiple client projects "
        "(e.g. mepram, relecov, redlabra).\n\n"
        "Authentication: Bearer JWT issued by Keycloak.\n"
        "Authorization: project scope is derived from the standard `groups` claim "
        "using Keycloak group paths such as "
        "`/use-cases/<use-case>/labs/<lab>/<view|admin>`.\n"
        "Legacy Basic/Session authentication can remain enabled temporarily "
        "during migration."
    ),
    "VERSION": "v1",
    "CONTACT": {
        "name": "PathoCore API Team",
    },
    "SERVE_INCLUDE_SCHEMA": True,
    # OTHER SETTINGS
    "GENERIC_ADDITIONAL_PROPERTIES": "dict",
    "COMPONENT_SPLIT_REQUEST": True,
    "SORT_OPERATIONS": False,
    "SECURITY": [{"bearerAuth": []}]
    + ([{"basicAuth": []}] if PATHOCORE_ENABLE_LEGACY_BASIC_AUTH else []),
    # Keep /v1 in real URLs but hide it in Swagger paths for readability.
    "SCHEMA_PATH_PREFIX": "/v1",
    "SCHEMA_PATH_PREFIX_TRIM": True,
    # Important for Swagger "Try it out": trimmed paths like "/schema"
    # must be executed against the "/v1" server base.
    "SERVERS": [{"url": "/v1", "description": "PathoCore API v1"}],
    "TAGS": [
        {
            "name": "Schemas",
            "description": (
                "Upload, list and inspect JSON Schemas. "
                "Schema upload is admin-only and project-scoped."
            ),
        },
        {
            "name": "Samples",
            "description": (
                "Create and list samples. "
                "Sample creation is admin-only; listing honors project scope."
            ),
        },
        {
            "name": "Sample Metadata",
            "description": (
                "Ingest metadata for a sample and query metadata values "
                "using property/value filters."
            ),
        },
        {
            "name": "Sample History",
            "description": (
                "Inspect state transitions and errors recorded per sample."
            ),
        },
    ],
}

#  enable the use of frames within HTML documents
X_FRAME_OPTIONS = "SAMEORIGIN"


# Internationalization
# https://docs.djangoproject.com/en/3.2/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_L10N = True

USE_TZ = False

ASGI_APPLICATION = "pathocore_api.asgi.application"

# Swagger settings
SWAGGER_SETTINGS = {
    "SECURITY_DEFINITIONS": {
        "basic": {"type": "basic"},
        "bearerAuth": {"type": "apiKey", "name": "Authorization", "in": "header"},
    }
}

#  Media settings
MEDIA_URL = "/documents/"
MEDIA_ROOT = "documents/"

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.2/howto/static-files/

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "static/")

# Redirect to home URL after login (Default redirects to /accounts/profile/)
LOGIN_REDIRECT_URL = "/intranet/"

# Default primary key field type
# https://docs.djangoproject.com/en/3.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
