import base64
import hashlib
import json

from django.conf import settings
from django.http import JsonResponse
from django_ratelimit.decorators import ratelimit
from django_ratelimit.exceptions import Ratelimited

DISABLED_RATE_VALUES = {"", "0", "off", "none", "false"}


class PathoCoreRatelimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, Ratelimited):
            return None
        return JsonResponse(
            {
                "detail": "Rate limit exceeded.",
                "error": (
                    "Too many API requests. Wait before retrying or contact "
                    "the PathoCore administrators if this limit is too strict."
                ),
            },
            status=429,
        )


def apply_api_ratelimit(view, *, category):
    if not getattr(settings, "PATHOCORE_RATELIMIT_ENABLED", True):
        return view

    rate = _rate_for_category(category)
    if rate is None:
        return view

    return ratelimit(
        group=f"pathocore-api:{category}",
        key=ratelimit_identity_key,
        rate=rate,
        block=True,
    )(view)


def ratelimit_identity_key(group, request):
    authorization = request.META.get("HTTP_AUTHORIZATION", "").strip()
    if authorization:
        return _authorization_key(authorization)
    return f"ip:{_client_ip(request)}"


def _rate_for_category(category):
    rates = getattr(settings, "PATHOCORE_RATELIMIT_RATES", {})
    rate = str(rates.get(category, "")).strip().lower()
    if rate in DISABLED_RATE_VALUES:
        return None
    return rate


def _authorization_key(authorization):
    scheme, _, credentials = authorization.partition(" ")
    scheme = scheme.strip().lower()
    credentials = credentials.strip()

    if scheme == "bearer":
        subject = _jwt_subject(credentials)
        if subject:
            return f"bearer-sub:{subject}"

    if scheme == "basic":
        username = _basic_username(credentials)
        if username:
            return f"basic-user:{username}"

    digest = hashlib.sha256(authorization.encode("utf-8")).hexdigest()
    return f"auth-hash:{digest}"


def _jwt_subject(token):
    parts = token.split(".")
    if len(parts) < 2:
        return ""
    payload = _urlsafe_b64decode(parts[1])
    if payload is None:
        return ""
    try:
        data = json.loads(payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    return str(data.get("sub") or data.get("preferred_username") or "").strip()


def _basic_username(credentials):
    decoded = _urlsafe_b64decode(credentials)
    if decoded is None:
        return ""
    try:
        raw_value = decoded.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    username, _, _ = raw_value.partition(":")
    return username.strip()


def _urlsafe_b64decode(value):
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (ValueError, TypeError):
        return None


def _client_ip(request):
    meta_key = getattr(settings, "PATHOCORE_RATELIMIT_IP_META_KEY", "").strip()
    if meta_key:
        value = request.META.get(meta_key, "").strip()
        if value:
            return value.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR", "")
