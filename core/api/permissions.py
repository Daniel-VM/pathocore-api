from rest_framework.permissions import BasePermission

from core.api.utils import access_control


class HasProjectAccess(BasePermission):
    message = "You are not allowed to access this project"

    def has_permission(self, request, view):
        project_id = _project_from_view(request, view)
        if not project_id:
            return False
        return access_control.has_project_access(request.user, project_id)


def _project_from_view(request, view):
    view_kwargs = getattr(view, "kwargs", None) or {}
    parser_kwargs = getattr(request, "parser_context", {}).get("kwargs", {})
    for key in ("project", "project_name"):
        project_id = view_kwargs.get(key) or parser_kwargs.get(key)
        if project_id:
            return project_id
    return None
