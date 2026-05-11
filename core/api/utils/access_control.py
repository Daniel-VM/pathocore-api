from django.core.exceptions import PermissionDenied
from django.db.models import Q

import core.config
from core.api.services import authorization


ROLE_VIEW = authorization.ROLE_VIEW
ROLE_ADMIN = authorization.ROLE_ADMIN
GroupParsingError = authorization.GroupParsingError
AuthorizationUser = authorization.AuthorizationUser
ProjectAuthorization = authorization.ProjectAuthorization

build_user_from_token = authorization.build_user_from_token
build_keycloak_authorization = authorization.build_keycloak_authorization
build_project_access = authorization.build_project_access
build_project_permissions = authorization.build_project_permissions

_normalize_project_code = authorization.normalize_identifier
_normalize_role = authorization.normalize_role
_merge_role = authorization.merge_role
_normalize_groups = authorization.normalize_groups


def is_admin_user(user):
    if user is None:
        return False
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


def is_keycloak_user(user):
    return bool(getattr(user, "auth_provider", None) == "keycloak")


def get_authorization_model(user):
    model = getattr(user, "authorization_model", None)
    if model is not None:
        return model
    if not is_keycloak_user(user):
        return None
    groups = getattr(user, "groups", None)
    if not groups:
        return None
    return authorization.build_user_from_groups(
        subject=str(getattr(user, "id", "")),
        username=str(getattr(user, "username", "")),
        groups_claim=groups,
        strict=True,
    )


def user_can(user, project_id, lab_id=None, role=ROLE_VIEW):
    if is_admin_user(user):
        return True

    model = get_authorization_model(user)
    if model is not None:
        return model.can(project_id, lab=lab_id, role=role)

    required_role = _normalize_role(role)
    if required_role is None:
        return False

    if lab_id is None:
        if required_role == ROLE_VIEW:
            return has_project_access(user, project_id)
        return authorization.role_allows(get_project_role(user, project_id), role)

    return authorization.role_allows(
        get_project_lab_role(user, project_id, lab_id),
        role,
    )


def get_project(user, project_id):
    normalized_project_id = _normalize_project_code(project_id)
    if not normalized_project_id:
        return None
    for project in get_user_projects(user):
        if project["id"] == normalized_project_id:
            return project
    return None


def has_project_access(user, project_id):
    if is_admin_user(user):
        return True
    return get_project(user, project_id) is not None


def get_project_labs(user, project_id):
    project = get_project(user, project_id)
    return project.get("labs", []) if project else []


def get_project_role(user, project_id):
    project = get_project(user, project_id)
    return project.get("project_role") if project else None


def get_effective_project_role(user, project_id):
    project = get_project(user, project_id)
    return project.get("effective_role") if project else None


def get_project_lab_role(user, project_id, lab_id):
    project = get_project(user, project_id)
    if not project:
        return None
    normalized_lab_id = _normalize_project_code(lab_id)
    if not normalized_lab_id:
        return None

    role = project.get("project_role")
    for lab_role in project.get("lab_roles", []):
        if lab_role["lab"] == normalized_lab_id:
            role = _merge_role(role, lab_role["role"])
    return role


def has_project_write_access(user, project_id):
    if is_admin_user(user):
        return True
    return get_project_role(user, project_id) == ROLE_ADMIN


def has_project_lab_access(user, project_id, lab_id):
    if is_admin_user(user):
        return True
    return get_project_lab_role(user, project_id, lab_id) is not None


def has_project_lab_write_access(user, project_id, lab_id):
    if is_admin_user(user):
        return True
    return get_project_lab_role(user, project_id, lab_id) == ROLE_ADMIN


def ensure_project_access(user, project_id):
    normalized_project_id = _normalize_project_code(project_id)
    if not normalized_project_id:
        raise PermissionDenied("Project identifier is required")
    if not has_project_access(user, normalized_project_id):
        raise PermissionDenied("You are not allowed to access this project")
    return normalized_project_id


def ensure_project_write_access(user, project_id):
    normalized_project_id = ensure_project_access(user, project_id)
    if not has_project_write_access(user, normalized_project_id):
        raise PermissionDenied("Admin privileges required for this project")
    return normalized_project_id


def ensure_project_lab_access(user, project_id, lab_id):
    normalized_project_id = ensure_project_access(user, project_id)
    normalized_lab_id = _normalize_project_code(lab_id)
    if not normalized_lab_id:
        raise PermissionDenied("Laboratory identifier is required")
    if not has_project_lab_access(user, normalized_project_id, normalized_lab_id):
        raise PermissionDenied("You are not allowed to access this laboratory")
    return normalized_project_id, normalized_lab_id


def ensure_project_lab_write_access(user, project_id, lab_id):
    normalized_project_id, normalized_lab_id = ensure_project_lab_access(
        user, project_id, lab_id
    )
    if not has_project_lab_write_access(user, normalized_project_id, normalized_lab_id):
        raise PermissionDenied("Admin privileges required for this laboratory")
    return normalized_project_id, normalized_lab_id


def get_user_projects(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return []

    model = get_authorization_model(user)
    if model is not None:
        return model.to_project_access()

    return build_project_access(
        projects_claim=getattr(user, "projects", None),
        groups_claim=getattr(user, "groups", None),
    )


def get_user_project_permissions(user):
    if user is None or not getattr(user, "is_authenticated", False):
        return {}

    model = get_authorization_model(user)
    if model is not None:
        return model.to_project_permissions()

    return build_project_permissions(
        projects_claim=getattr(user, "projects", None),
        groups_claim=getattr(user, "groups", None),
    )


def get_persisted_user(user):
    if is_keycloak_user(user):
        return None
    return user


def get_user_project_code(user):
    if is_admin_user(user):
        return None
    if user is None or not user.is_authenticated:
        raise PermissionDenied("Authentication credentials were not provided")
    if is_keycloak_user(user):
        projects = get_user_projects(user)
        if not projects:
            raise PermissionDenied("User project scope is not configured")
        if len(projects) > 1:
            raise PermissionDenied(
                "This endpoint requires an explicit project-scoped route"
            )
        return projects[0]["id"]
    profile = getattr(user, "profile", None)
    project_code = _normalize_project_code(getattr(profile, "code_id", None))
    if not project_code:
        raise PermissionDenied("User project scope is not configured")
    return project_code


def validate_allowed_project_name(project_name):
    normalized = _normalize_project_code(project_name)
    if not normalized:
        raise ValueError("schema project_name is required")
    allowed = {
        _normalize_project_code(item)
        for item in getattr(
            core.config,
            "ALLOWED_SCHEMA_PROJECT_NAMES",
            core.config.ALLOWED_SCHEMA_APP_NAMES,
        )
    }
    allowed.discard(None)
    if normalized not in allowed:
        allowed_csv = ", ".join(sorted(allowed))
        raise ValueError(f"schema project_name must be one of: {allowed_csv}")
    return normalized


def validate_allowed_app_name(app_name):
    """Backward-compatible alias."""
    return validate_allowed_project_name(app_name)


def apply_schema_scope(queryset, user):
    if is_admin_user(user):
        return queryset
    project_codes = get_user_project_codes(user)
    return queryset.filter(_project_scope_query("schema_app_name", project_codes))


def apply_sample_scope(queryset, user):
    if is_admin_user(user):
        return queryset
    project_codes = get_user_project_codes(user)
    return queryset.filter(
        _project_scope_query("schema_obj__schema_app_name", project_codes)
    )


def apply_sample_history_scope(queryset, user):
    if is_admin_user(user):
        return queryset
    project_codes = get_user_project_codes(user)
    return queryset.filter(
        _project_scope_query("sample__schema_obj__schema_app_name", project_codes)
    )


def apply_metadata_values_scope(queryset, user):
    if is_admin_user(user):
        return queryset
    project_codes = get_user_project_codes(user)
    return queryset.filter(
        _project_scope_query("sample__schema_obj__schema_app_name", project_codes)
    )


def apply_project_labs_scope(queryset, user, project_id, field_name):
    if get_project_role(user, project_id):
        return queryset
    labs = get_project_labs(user, project_id)
    if not labs:
        return queryset.none()
    return queryset.filter(**{f"{field_name}__in": labs})


def get_user_project_codes(user):
    if is_admin_user(user):
        return []
    if is_keycloak_user(user):
        project_codes = [project["id"] for project in get_user_projects(user)]
        if not project_codes:
            raise PermissionDenied("User project scope is not configured")
        return project_codes
    project_code = get_user_project_code(user)
    return [project_code]


def _project_scope_query(field_name, project_codes):
    project_query = Q()
    for project_code in project_codes:
        project_query |= Q(**{f"{field_name}__iexact": project_code})
    return project_query


def ensure_sample_access(sample_obj, user):
    if sample_obj is None:
        return None
    if is_admin_user(user):
        return sample_obj
    project_codes = set(get_user_project_codes(user))
    schema_obj = sample_obj.schema_obj
    schema_project_code = _normalize_project_code(
        getattr(schema_obj, "schema_app_name", None)
    )
    if schema_project_code not in project_codes:
        raise PermissionDenied("You are not allowed to access this sample")
    return sample_obj


def ensure_sample_write_access(sample_obj, user):
    sample_obj = ensure_sample_access(sample_obj, user)
    project_id = getattr(sample_obj.schema_obj, "schema_app_name", None)
    ensure_project_write_access(user, project_id)
    return sample_obj
