from django.core.exceptions import PermissionDenied
from django.db.models import Q

import core.config


ROLE_VIEW = "view"
ROLE_ADMIN = "admin"
ROLE_PRECEDENCE = {ROLE_VIEW: 1, ROLE_ADMIN: 2}
ROLE_ALIASES = {"viewer": ROLE_VIEW, ROLE_VIEW: ROLE_VIEW, ROLE_ADMIN: ROLE_ADMIN}
GROUP_ROOT_USE_CASES = "use-cases"
GROUP_SEGMENT_LABS = "labs"
SUPERUSER_GROUP = "/superusers"


class GroupParsingError(ValueError):
    """Raised when a Keycloak groups claim does not follow PathoCore grammar."""


def _normalize_project_code(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def _normalize_role(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return ROLE_ALIASES.get(cleaned)


def _normalize_groups(groups):
    if not isinstance(groups, list):
        return []
    return [str(group).strip() for group in groups if str(group).strip()]


def _normalize_groups_claim(groups_claim, *, strict=False):
    if groups_claim in (None, ""):
        return []
    if not isinstance(groups_claim, list):
        if strict:
            raise GroupParsingError("groups claim must be a list")
        return []

    groups = []
    for group in groups_claim:
        if not isinstance(group, str):
            if strict:
                raise GroupParsingError("groups claim must contain only strings")
            continue
        group = group.strip()
        if not group:
            if strict:
                raise GroupParsingError("groups claim contains an empty group path")
            continue
        groups.append(group)
    return groups


def _merge_role(current, candidate):
    if candidate is None:
        return current
    if current is None:
        return candidate
    if ROLE_PRECEDENCE[candidate] > ROLE_PRECEDENCE[current]:
        return candidate
    return current


def _normalize_role_from_group(role, group):
    normalized = _normalize_role(role)
    if normalized is None:
        raise GroupParsingError(
            f"Unknown role '{role}' in group '{group}'. "
            f"Supported roles are: {ROLE_VIEW}, {ROLE_ADMIN}"
        )
    return normalized


def _empty_group_permissions():
    return {"superuser": False, "projects": {}}


def _parse_keycloak_group(group):
    if not group.startswith("/"):
        raise GroupParsingError(
            f"Malformed group path '{group}': path must start with /"
        )

    path_parts = [segment.strip() for segment in group.split("/") if segment.strip()]
    if path_parts == ["superusers"]:
        return {"kind": "superuser"}

    if len(path_parts) < 3 or path_parts[0].lower() != GROUP_ROOT_USE_CASES:
        raise GroupParsingError(
            f"Malformed group path '{group}'. Expected /use-cases/<project>/<role>, "
            f"/use-cases/<project>/labs/<lab>/<role>, or {SUPERUSER_GROUP}"
        )

    project_id = _normalize_project_code(path_parts[1])
    if not project_id:
        raise GroupParsingError(f"Malformed group path '{group}': project is required")

    if len(path_parts) == 3:
        return {
            "kind": "project",
            "project": project_id,
            "role": _normalize_role_from_group(path_parts[2], group),
        }

    if len(path_parts) == 5 and path_parts[2].lower() == GROUP_SEGMENT_LABS:
        lab_id = _normalize_project_code(path_parts[3])
        if not lab_id:
            raise GroupParsingError(f"Malformed group path '{group}': lab is required")
        return {
            "kind": "lab",
            "project": project_id,
            "lab": lab_id,
            "role": _normalize_role_from_group(path_parts[4], group),
        }

    raise GroupParsingError(
        f"Malformed group path '{group}'. Expected /use-cases/<project>/<role>, "
        f"/use-cases/<project>/labs/<lab>/<role>, or {SUPERUSER_GROUP}"
    )


def _parse_group_permissions(groups_claim, *, strict=False):
    groups = _normalize_groups_claim(groups_claim, strict=strict)
    permissions = _empty_group_permissions()

    for group in groups:
        try:
            parsed = _parse_keycloak_group(group)
        except GroupParsingError:
            if strict:
                raise
            continue

        if parsed["kind"] == "superuser":
            permissions["superuser"] = True
            continue

        project_data = permissions["projects"].setdefault(
            parsed["project"],
            {
                "explicit_project_role": None,
                "labs": {},
                "source_groups": [],
            },
        )
        project_data["source_groups"].append(group)

        if parsed["kind"] == "project":
            project_data["explicit_project_role"] = _merge_role(
                project_data["explicit_project_role"], parsed["role"]
            )
            continue

        current_lab_role = project_data["labs"].get(parsed["lab"])
        project_data["labs"][parsed["lab"]] = _merge_role(
            current_lab_role, parsed["role"]
        )

    return permissions


def _project_inferred_role(project_data):
    role = project_data["explicit_project_role"]
    if project_data["labs"]:
        role = _merge_role(role, ROLE_VIEW)
    return role


def _project_effective_role(project_data):
    role = project_data["explicit_project_role"]
    for lab_role in project_data["labs"].values():
        role = _merge_role(role, lab_role)
    return role


def _project_access_from_group_permissions(permissions):
    project_access = []
    for project_id in sorted(permissions["projects"]):
        project_data = permissions["projects"][project_id]
        explicit_project_role = project_data["explicit_project_role"]
        labs = sorted(project_data["labs"])
        lab_roles = [{"lab": lab, "role": project_data["labs"][lab]} for lab in labs]
        project_access.append(
            {
                "id": project_id,
                "labs": labs,
                "role": explicit_project_role,
                "effective_role": _project_effective_role(project_data),
                "project_role": explicit_project_role,
                "lab_roles": lab_roles,
                "source_groups": sorted(project_data["source_groups"]),
            }
        )
    return project_access


def build_keycloak_authorization(subject, username, groups_claim):
    permissions = _parse_group_permissions(groups_claim, strict=True)
    authorization = {
        "id": str(subject),
        "username": str(username),
        "superuser": bool(permissions["superuser"]),
        "projects": {},
    }
    for project_id in sorted(permissions["projects"]):
        project_data = permissions["projects"][project_id]
        authorization["projects"][project_id] = {
            "project_role": _project_inferred_role(project_data),
            "labs": dict(sorted(project_data["labs"].items())),
        }
    return {
        "authorization": authorization,
        "project_access": _project_access_from_group_permissions(permissions),
    }


def _normalize_lab_roles(lab_roles):
    normalized = []
    if not isinstance(lab_roles, list):
        return normalized
    for lab_role in lab_roles:
        if not isinstance(lab_role, dict):
            continue
        lab = _normalize_project_code(lab_role.get("lab"))
        role = _normalize_role(lab_role.get("role"))
        if not lab or not role:
            continue
        normalized.append({"lab": lab, "role": role})
    normalized.sort(key=lambda item: item["lab"])
    return normalized


def _summarize_role(project_role, lab_roles, labs):
    role = _normalize_role(project_role)
    for lab_role in lab_roles:
        role = _merge_role(role, lab_role["role"])
    if role is None and labs:
        role = ROLE_VIEW
    return role


def _normalize_project_claim(project):
    if not isinstance(project, dict):
        return None
    project_id = _normalize_project_code(project.get("id"))
    if not project_id:
        return None
    labs = project.get("labs")
    if not isinstance(labs, list):
        labs = []
    labs = sorted(
        {
            normalized_lab
            for normalized_lab in (
                _normalize_project_code(lab) for lab in labs
            )
            if normalized_lab
        }
    )
    raw_role = _normalize_role(project.get("role"))
    project_role = _normalize_role(project.get("project_role"))
    lab_roles = _normalize_lab_roles(project.get("lab_roles"))
    if project_role is None and raw_role is not None:
        project_role = raw_role
    for lab_role in lab_roles:
        if lab_role["lab"] not in labs:
            labs.append(lab_role["lab"])
    labs = sorted(set(labs))
    effective_role = _summarize_role(project_role, lab_roles, labs)
    source_groups = _normalize_groups(project.get("source_groups"))
    return {
        "id": project_id,
        "labs": labs,
        "role": project_role,
        "effective_role": effective_role,
        "project_role": project_role,
        "lab_roles": lab_roles,
        "source_groups": source_groups,
    }


def _build_project_access_from_claims(projects_claim):
    if not isinstance(projects_claim, list):
        return []
    normalized = []
    for project in projects_claim:
        normalized_project = _normalize_project_claim(project)
        if normalized_project:
            normalized.append(normalized_project)
    return normalized


def _build_project_access_from_groups(groups_claim):
    permissions = _parse_group_permissions(groups_claim, strict=True)
    return _project_access_from_group_permissions(permissions)


def build_project_access(projects_claim=None, groups_claim=None):
    project_access = _build_project_access_from_groups(groups_claim)
    if project_access:
        return project_access
    return _build_project_access_from_claims(projects_claim)


def is_admin_user(user):
    if user is None:
        return False
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


def is_keycloak_user(user):
    return bool(getattr(user, "auth_provider", None) == "keycloak")


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
    return get_project_role(user, project_id) == "admin"


def has_project_lab_access(user, project_id, lab_id):
    if is_admin_user(user):
        return True
    return get_project_lab_role(user, project_id, lab_id) is not None


def has_project_lab_write_access(user, project_id, lab_id):
    if is_admin_user(user):
        return True
    return get_project_lab_role(user, project_id, lab_id) == "admin"


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
    return build_project_access(
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
