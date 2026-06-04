import json
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.parse import urlencode
from urllib.request import Request
from urllib.request import urlopen

from django.conf import settings


class KeycloakAdminError(RuntimeError):
    pass


class KeycloakAdminConfigError(KeycloakAdminError):
    pass


def provision_approved_user(access_request, group_path):
    token = _get_admin_token()
    user = _find_user(token, access_request.username, access_request.email)
    if user is None:
        user_id = _create_user(token, access_request)
    else:
        user_id = user["id"]
        _enable_user(token, user_id, access_request)

    if getattr(settings, "KEYCLOAK_ADMIN_SEND_ACTION_EMAILS", True):
        _send_execute_actions_email(token, user_id)

    group = _get_group_by_path(token, group_path)
    _join_group(token, user_id, group["id"])
    return {"user_id": user_id, "group_id": group["id"], "group_path": group_path}


def revoke_approved_user_access(access_request, group_path):
    token = _get_admin_token()
    user_id = access_request.keycloak_user_id
    if not user_id:
        user = _find_user(token, access_request.username, access_request.email)
        if user is None:
            raise KeycloakAdminError(
                "Unable to revoke access because the Keycloak user was not found"
            )
        user_id = user["id"]

    group = _get_group_by_path(token, group_path)
    _leave_group(token, user_id, group["id"])
    return {"user_id": user_id, "group_id": group["id"], "group_path": group_path}


def _get_admin_token():
    config = _get_config()
    token_url = (
        f"{config['base_url']}/realms/"
        f"{quote(config['token_realm'], safe='')}/protocol/openid-connect/token"
    )
    if config["client_secret"]:
        payload = {
            "grant_type": "client_credentials",
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
        }
    else:
        if not config["username"] or not config["password"]:
            raise KeycloakAdminConfigError(
                "Keycloak admin credentials are not configured"
            )
        payload = {
            "grant_type": "password",
            "client_id": config["client_id"],
            "username": config["username"],
            "password": config["password"],
        }

    response = _request_json(
        "POST",
        token_url,
        data=urlencode(payload).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        expected_statuses=(200,),
    )
    token = response.get("access_token")
    if not token:
        raise KeycloakAdminError("Keycloak admin token response has no access_token")
    return token


def _find_user(token, username, email):
    users = _request_json(
        "GET",
        _admin_url(
            "users",
            query={"username": username, "exact": "true"},
        ),
        token=token,
        expected_statuses=(200,),
    )
    for user in users:
        if user.get("username") == username:
            return user

    users = _request_json(
        "GET",
        _admin_url("users", query={"email": email, "exact": "true"}),
        token=token,
        expected_statuses=(200,),
    )
    for user in users:
        if str(user.get("email", "")).lower() == email.lower():
            return user
    return None


def _create_user(token, access_request):
    payload = _user_payload(access_request)
    response_headers = _request(
        "POST",
        _admin_url("users"),
        token=token,
        payload=payload,
        expected_statuses=(201,),
    ).headers
    location = response_headers.get("Location", "")
    user_id = location.rstrip("/").split("/")[-1] if location else ""
    if not user_id:
        user = _find_user(token, access_request.username, access_request.email)
        if not user:
            raise KeycloakAdminError("Unable to resolve created Keycloak user id")
        return user["id"]
    return user_id


def _enable_user(token, user_id, access_request):
    _request(
        "PUT",
        _admin_url(f"users/{quote(user_id, safe='')}"),
        token=token,
        payload=_user_payload(access_request),
        expected_statuses=(204,),
    )


def _user_payload(access_request):
    return {
        "username": access_request.username,
        "email": access_request.email,
        "firstName": access_request.first_name,
        "lastName": access_request.last_name,
        "enabled": True,
        "emailVerified": False,
        "requiredActions": ["UPDATE_PASSWORD", "VERIFY_EMAIL"],
        "attributes": {
            "pathocore_access_request_id": [str(access_request.pk)],
            "pathocore_requested_use_case": [access_request.requested_use_case],
            "pathocore_requested_lab": [access_request.requested_lab or ""],
            "pathocore_requested_role": [access_request.requested_role],
        },
    }


def _get_group_by_path(token, group_path):
    return _request_json(
        "GET",
        _admin_url(f"group-by-path/{quote(group_path, safe='')}"),
        token=token,
        expected_statuses=(200,),
    )


def _join_group(token, user_id, group_id):
    _request(
        "PUT",
        _admin_url(
            f"users/{quote(user_id, safe='')}/groups/{quote(group_id, safe='')}"
        ),
        token=token,
        expected_statuses=(204,),
    )


def _leave_group(token, user_id, group_id):
    _request(
        "DELETE",
        _admin_url(
            f"users/{quote(user_id, safe='')}/groups/{quote(group_id, safe='')}"
        ),
        token=token,
        expected_statuses=(204,),
    )


def _send_execute_actions_email(token, user_id):
    query = {}
    redirect_uri = getattr(settings, "KEYCLOAK_ADMIN_ACTION_EMAIL_REDIRECT_URI", "")
    if redirect_uri:
        query["redirect_uri"] = redirect_uri
    _request(
        "PUT",
        _admin_url(
            f"users/{quote(user_id, safe='')}/execute-actions-email",
            query=query,
        ),
        token=token,
        payload=["UPDATE_PASSWORD", "VERIFY_EMAIL"],
        expected_statuses=(204,),
    )


def _admin_url(path, query=None):
    config = _get_config()
    url = (
        f"{config['base_url']}/admin/realms/"
        f"{quote(config['realm'], safe='')}/{path.lstrip('/')}"
    )
    if query:
        url = f"{url}?{urlencode(query)}"
    return url


def _get_config():
    issuer = getattr(settings, "KEYCLOAK_ISSUER", "").rstrip("/")
    base_url = getattr(settings, "KEYCLOAK_ADMIN_BASE_URL", "").rstrip("/")
    if not base_url and "/realms/" in issuer:
        base_url = issuer.split("/realms/", 1)[0]
    realm = getattr(settings, "KEYCLOAK_REALM", "").strip()
    if not realm and issuer:
        realm = issuer.rsplit("/", 1)[-1]
    config = {
        "base_url": base_url,
        "realm": realm,
        "token_realm": getattr(settings, "KEYCLOAK_ADMIN_TOKEN_REALM", "master"),
        "client_id": getattr(settings, "KEYCLOAK_ADMIN_CLIENT_ID", "admin-cli"),
        "client_secret": getattr(settings, "KEYCLOAK_ADMIN_CLIENT_SECRET", ""),
        "username": getattr(settings, "KEYCLOAK_ADMIN_USERNAME", ""),
        "password": getattr(settings, "KEYCLOAK_ADMIN_PASSWORD", ""),
        "timeout": int(
            getattr(settings, "KEYCLOAK_ADMIN_REQUEST_TIMEOUT_SECONDS", 10)
        ),
    }
    missing = [key for key in ("base_url", "realm", "token_realm", "client_id") if not config[key]]
    if missing:
        raise KeycloakAdminConfigError(
            "Keycloak admin configuration is incomplete: " + ", ".join(missing)
        )
    return config


def _request_json(method, url, **kwargs):
    response = _request(method, url, **kwargs)
    body = response.read().decode("utf-8")
    return json.loads(body) if body else {}


def _request(
    method,
    url,
    token=None,
    payload=None,
    data=None,
    headers=None,
    expected_statuses=(200,),
):
    config = _get_config()
    request_headers = dict(headers or {})
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    request_data = data
    if payload is not None:
        request_data = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"

    request = Request(
        url,
        data=request_data,
        headers=request_headers,
        method=method,
    )
    try:
        response = urlopen(request, timeout=config["timeout"])
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise KeycloakAdminError(
            f"Keycloak Admin API {method} {url} failed "
            f"with HTTP {exc.code}: {body}"
        ) from exc
    except OSError as exc:
        raise KeycloakAdminError(
            f"Keycloak Admin API {method} {url} failed: {exc}"
        ) from exc

    if response.status not in expected_statuses:
        body = response.read().decode("utf-8", errors="replace")
        raise KeycloakAdminError(
            f"Keycloak Admin API {method} {url} returned "
            f"HTTP {response.status}: {body}"
        )
    return response
