import json
import threading
import time
from dataclasses import dataclass, field
from urllib.error import URLError
from urllib.request import urlopen

import jwt
from django.conf import settings
from rest_framework.authentication import BasicAuthentication
from rest_framework.authentication import SessionAuthentication
from rest_framework.authentication import get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from core.api.utils import access_control

_JWKS_CACHE = {"expires_at": 0.0, "keys_by_kid": {}}
_JWKS_CACHE_LOCK = threading.Lock()


@dataclass
class KeycloakClaims:
    raw_token: str
    payload: dict
    authorization: dict = field(default_factory=dict)
    project_access: list[dict] = field(default_factory=list)
    authorization_model: object | None = None

    @property
    def subject(self):
        return str(self.payload["sub"])

    @property
    def username(self):
        return str(self.payload.get("preferred_username") or self.payload["sub"])

    @property
    def groups(self):
        return _normalize_groups(self.payload.get("groups"))

    @property
    def projects(self):
        if self.project_access:
            return self.project_access
        if self.authorization_model is not None:
            return self.authorization_model.to_project_access()
        return access_control.build_project_access(
            projects_claim=self.payload.get("projects"),
            groups_claim=self.payload.get("groups"),
        )

    @property
    def superuser(self):
        return bool(self.authorization.get("superuser", False))


@dataclass
class KeycloakTokenUser:
    subject: str
    username: str
    groups: list[str] = field(default_factory=list)
    projects: list[dict] = field(default_factory=list)
    authorization: dict = field(default_factory=dict)
    authorization_model: object | None = None
    token_payload: dict = field(default_factory=dict)
    auth_provider: str = "keycloak"
    is_staff: bool = False
    is_superuser: bool = False

    @property
    def id(self):
        return self.subject

    @property
    def pk(self):
        return self.subject

    @property
    def is_authenticated(self):
        return True

    @property
    def is_active(self):
        return True

    @property
    def is_anonymous(self):
        return False

    def __str__(self):
        return self.username or self.subject

    def can(self, project, lab=None, role="view"):
        if self.authorization_model is not None:
            return self.authorization_model.can(project, lab=lab, role=role)
        return access_control.user_can(self, project, lab_id=lab, role=role)


class KeycloakJWTAuthentication:
    www_authenticate_realm = "api"

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth:
            return None
        if auth[0].lower() != b"bearer":
            return None
        if len(auth) != 2:
            raise AuthenticationFailed("Invalid bearer token header")
        try:
            token = auth[1].decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AuthenticationFailed("Invalid bearer token header") from exc

        claims = decode_and_validate_keycloak_token(token)
        user = KeycloakTokenUser(
            subject=claims.subject,
            username=claims.username,
            groups=claims.groups,
            projects=claims.projects,
            authorization=claims.authorization,
            authorization_model=claims.authorization_model,
            token_payload=claims.payload,
            is_staff=claims.superuser,
            is_superuser=claims.superuser,
        )
        return user, claims.payload

    def authenticate_header(self, request):
        return f'Bearer realm="{self.www_authenticate_realm}"'

    def _decode_token(self, token):
        return decode_and_validate_keycloak_token(token).payload


class LegacyBasicOrSessionAuthentication:
    def __init__(self):
        self.session_auth = SessionAuthentication()
        self.basic_auth = BasicAuthentication()

    def authenticate(self, request):
        user_auth_tuple = self.session_auth.authenticate(request)
        if user_auth_tuple is not None:
            return user_auth_tuple
        return self.basic_auth.authenticate(request)

    def authenticate_header(self, request):
        return self.basic_auth.authenticate_header(request)


class AdminBasicOrSessionAuthentication:
    def __init__(self):
        self.session_auth = SessionAuthentication()
        self.basic_auth = BasicAuthentication()

    def authenticate(self, request):
        user_auth_tuple = self.session_auth.authenticate(request)
        if user_auth_tuple is not None:
            return user_auth_tuple if _is_admin_user(user_auth_tuple[0]) else None

        user_auth_tuple = self.basic_auth.authenticate(request)
        if user_auth_tuple is not None:
            return user_auth_tuple if _is_admin_user(user_auth_tuple[0]) else None
        return None

    def authenticate_header(self, request):
        return self.basic_auth.authenticate_header(request)


def build_api_authentication_classes():
    classes = [AdminBasicOrSessionAuthentication, KeycloakJWTAuthentication]
    if getattr(settings, "PATHOCORE_ENABLE_LEGACY_BASIC_AUTH", True):
        classes.append(LegacyBasicOrSessionAuthentication)
    return classes


API_AUTHENTICATION_CLASSES = build_api_authentication_classes()


def decode_and_validate_keycloak_token(token):
    keycloak_settings = _get_keycloak_settings()
    if (
        not keycloak_settings["issuer"]
        or not keycloak_settings["jwks_url"]
        or not keycloak_settings["audience"]
        or not keycloak_settings["client_id"]
    ):
        missing = [
            env_name
            for env_name, value in (
                ("KEYCLOAK_ISSUER", keycloak_settings["issuer"]),
                ("KEYCLOAK_JWKS_URL", keycloak_settings["jwks_url"]),
                ("KEYCLOAK_AUDIENCE", keycloak_settings["audience"]),
                ("KEYCLOAK_CLIENT_ID", keycloak_settings["client_id"]),
            )
            if not value
        ]
        raise AuthenticationFailed(
            "Keycloak authentication is not configured: missing " + ", ".join(missing)
        )

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthenticationFailed("Invalid token header") from exc

    algorithm = header.get("alg")
    if algorithm != "RS256":
        raise AuthenticationFailed("Unsupported token signing algorithm")

    signing_key = _get_signing_key(
        kid=header.get("kid"),
        jwks_url=keycloak_settings["jwks_url"],
        ttl_seconds=keycloak_settings["jwks_cache_ttl_seconds"],
        timeout_seconds=keycloak_settings["jwks_timeout_seconds"],
    )
    try:
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=keycloak_settings["issuer"],
            audience=keycloak_settings["audience"],
            options={"require": ["iss", "aud", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationFailed("Token has expired") from exc
    except jwt.MissingRequiredClaimError as exc:
        raise AuthenticationFailed(
            f"Token is missing required claim: {exc.claim}"
        ) from exc
    except jwt.InvalidAudienceError as exc:
        raise AuthenticationFailed("Invalid token audience") from exc
    except jwt.InvalidIssuerError as exc:
        raise AuthenticationFailed("Invalid token issuer") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationFailed("Invalid token") from exc

    subject = str(payload.get("sub") or "").strip()
    if not subject:
        raise AuthenticationFailed("Token is missing required claim: sub")

    try:
        authorization_model = access_control.build_user_from_token(payload, strict=True)
    except access_control.GroupParsingError as exc:
        raise AuthenticationFailed(f"Malformed groups claim: {exc}") from exc
    except ValueError as exc:
        raise AuthenticationFailed(str(exc)) from exc

    return KeycloakClaims(
        raw_token=token,
        payload=payload,
        authorization=authorization_model.to_authorization_dict(),
        project_access=authorization_model.to_project_access(),
        authorization_model=authorization_model,
    )


def _normalize_groups(groups):
    if not isinstance(groups, list):
        return []
    return [str(group).strip() for group in groups if str(group).strip()]


def _is_admin_user(user):
    return bool(
        getattr(user, "is_active", False)
        and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))
    )


def _get_keycloak_settings():
    issuer = getattr(settings, "KEYCLOAK_ISSUER", "").strip()
    jwks_url = getattr(settings, "KEYCLOAK_JWKS_URL", "").strip()
    audience = _parse_audience_setting(getattr(settings, "KEYCLOAK_AUDIENCE", ""))
    client_id = getattr(settings, "KEYCLOAK_CLIENT_ID", "").strip()
    return {
        "issuer": issuer,
        "jwks_url": jwks_url,
        "audience": audience,
        "client_id": client_id,
        "jwks_cache_ttl_seconds": int(
            getattr(settings, "KEYCLOAK_JWKS_CACHE_TTL_SECONDS", 300)
        ),
        "jwks_timeout_seconds": int(
            getattr(settings, "KEYCLOAK_JWKS_TIMEOUT_SECONDS", 5)
        ),
    }


def _get_signing_key(kid, jwks_url, ttl_seconds, timeout_seconds):
    now = time.time()
    with _JWKS_CACHE_LOCK:
        if _JWKS_CACHE["expires_at"] <= now:
            _JWKS_CACHE["keys_by_kid"] = _fetch_jwks_keys(
                jwks_url=jwks_url,
                timeout_seconds=timeout_seconds,
            )
            _JWKS_CACHE["expires_at"] = now + ttl_seconds
        keys_by_kid = dict(_JWKS_CACHE["keys_by_kid"])

    if kid and kid in keys_by_kid:
        return keys_by_kid[kid]
    if not kid and len(keys_by_kid) == 1:
        return next(iter(keys_by_kid.values()))
    raise AuthenticationFailed("Unable to match token signing key")


def _fetch_jwks_keys(jwks_url, timeout_seconds):
    try:
        with urlopen(jwks_url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, ValueError) as exc:
        raise AuthenticationFailed("Unable to retrieve Keycloak signing keys") from exc

    keys_by_kid = {}
    for jwk in payload.get("keys", []):
        kid = jwk.get("kid")
        if not kid:
            continue
        try:
            keys_by_kid[kid] = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        except (TypeError, ValueError) as exc:
            raise AuthenticationFailed("Invalid Keycloak signing key payload") from exc
    if not keys_by_kid:
        raise AuthenticationFailed("Keycloak JWKS endpoint returned no signing keys")
    return keys_by_kid


def _parse_audience_setting(value):
    if isinstance(value, (list, tuple, set)):
        audiences = [str(item).strip() for item in value if str(item).strip()]
    else:
        audiences = [item.strip() for item in str(value).split(",") if item.strip()]
    if not audiences:
        return []
    if len(audiences) == 1:
        return audiences[0]
    return audiences
