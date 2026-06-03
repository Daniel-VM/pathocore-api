from rest_framework.exceptions import AuthenticationFailed
from rest_framework.exceptions import NotAuthenticated
from rest_framework.views import exception_handler


AUTHENTICATION_HELP = {
    "detail": (
        "Authentication is required. Use a Keycloak Bearer token or Django "
        "admin credentials."
    ),
    "keycloak": (
        "Go to the configured Keycloak realm, log in with your credentials, "
        "copy the access token and send it as: Authorization: Bearer <token>."
    ),
    "django_admin": (
        "For local/admin access, use a Django staff or superuser account. "
        "The Docker testing stack creates admin/admin_pass by default."
    ),
}


def pathocore_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    if isinstance(exc, (AuthenticationFailed, NotAuthenticated)):
        original_detail = response.data.get("detail")
        response.data = {
            **AUTHENTICATION_HELP,
            "error": str(original_detail or exc),
        }

    return response
