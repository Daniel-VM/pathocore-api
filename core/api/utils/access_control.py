from django.core.exceptions import PermissionDenied

import core.config


def _normalize_project_code(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def is_admin_user(user):
    if user is None:
        return False
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


def get_user_project_code(user):
    if is_admin_user(user):
        return None
    if user is None or not user.is_authenticated:
        raise PermissionDenied("Authentication credentials were not provided")
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
    project_code = get_user_project_code(user)
    return queryset.filter(schema_app_name__iexact=project_code)


def apply_sample_scope(queryset, user):
    if is_admin_user(user):
        return queryset
    project_code = get_user_project_code(user)
    return queryset.filter(schema_obj__schema_app_name__iexact=project_code)


def apply_sample_history_scope(queryset, user):
    if is_admin_user(user):
        return queryset
    project_code = get_user_project_code(user)
    return queryset.filter(sample__schema_obj__schema_app_name__iexact=project_code)


def apply_metadata_values_scope(queryset, user):
    if is_admin_user(user):
        return queryset
    project_code = get_user_project_code(user)
    return queryset.filter(sample__schema_obj__schema_app_name__iexact=project_code)


def ensure_sample_access(sample_obj, user):
    if sample_obj is None:
        return None
    if is_admin_user(user):
        return sample_obj
    project_code = get_user_project_code(user)
    schema_obj = sample_obj.schema_obj
    schema_project_code = _normalize_project_code(
        getattr(schema_obj, "schema_app_name", None)
    )
    if schema_project_code != project_code:
        raise PermissionDenied("You are not allowed to access this sample")
    return sample_obj
