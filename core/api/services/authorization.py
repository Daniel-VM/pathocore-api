from dataclasses import dataclass, field

ROLE_VIEW = "view"
ROLE_ADMIN = "admin"
ROLE_PRECEDENCE = {ROLE_VIEW: 1, ROLE_ADMIN: 2}
ROLE_ALIASES = {"viewer": ROLE_VIEW, ROLE_VIEW: ROLE_VIEW, ROLE_ADMIN: ROLE_ADMIN}
GROUP_ROOT_USE_CASES = "use-cases"
GROUP_SEGMENT_LABS = "labs"
SUPERUSER_GROUP = "/superusers"


class GroupParsingError(ValueError):
    """Raised when a Keycloak groups claim does not follow PathoCore grammar."""


@dataclass(frozen=True)
class ProjectAuthorization:
    id: str
    explicit_project_role: str | None = None
    labs: dict[str, str] = field(default_factory=dict)
    source_groups: tuple[str, ...] = ()

    @property
    def project_role(self):
        if self.explicit_project_role:
            return self.explicit_project_role
        if self.labs:
            return ROLE_VIEW
        return None

    @property
    def effective_role(self):
        role = self.explicit_project_role
        for lab_role in self.labs.values():
            role = merge_role(role, lab_role)
        return role

    def lab_role(self, lab_id):
        normalized_lab_id = normalize_identifier(lab_id)
        if not normalized_lab_id:
            return None
        return merge_role(
            self.explicit_project_role,
            self.labs.get(normalized_lab_id),
        )

    def can(self, lab=None, role=ROLE_VIEW):
        required_role = normalize_role_or_raise(role)
        if lab is None:
            return role_allows(self.project_role, required_role)
        return role_allows(self.lab_role(lab), required_role)

    def to_authorization_dict(self):
        return {
            "project_role": self.explicit_project_role,
            "labs": {lab: {"role": self.labs[lab]} for lab in sorted(self.labs)},
        }

    def to_project_access_dict(self):
        labs = sorted(self.labs)
        return {
            "id": self.id,
            "labs": labs,
            "role": self.explicit_project_role,
            "effective_role": self.effective_role,
            "project_role": self.explicit_project_role,
            "lab_roles": [{"lab": lab, "role": self.labs[lab]} for lab in labs],
            "source_groups": sorted(self.source_groups),
        }


@dataclass(frozen=True)
class AuthorizationUser:
    id: str
    username: str
    superuser: bool = False
    projects: dict[str, ProjectAuthorization] = field(default_factory=dict)
    groups: tuple[str, ...] = ()

    def can(self, project, lab=None, role=ROLE_VIEW):
        if self.superuser:
            return True
        project_id = normalize_identifier(project)
        if not project_id:
            return False
        project_authorization = self.projects.get(project_id)
        if project_authorization is None:
            return False
        return project_authorization.can(lab=lab, role=role)

    def to_authorization_dict(self):
        return {
            "id": self.id,
            "username": self.username,
            "superuser": bool(self.superuser),
            "projects": self.to_project_permissions(),
        }

    def to_project_access(self):
        return [
            self.projects[project_id].to_project_access_dict()
            for project_id in sorted(self.projects)
        ]

    def to_project_permissions(self):
        return {
            project_id: self.projects[project_id].to_authorization_dict()
            for project_id in sorted(self.projects)
        }


def build_user_from_token(payload, *, strict=True):
    subject = str(payload.get("sub") or "").strip()
    if not subject:
        raise ValueError("Token is missing required claim: sub")
    username = str(payload.get("preferred_username") or subject)
    return build_user_from_groups(
        subject=subject,
        username=username,
        groups_claim=payload.get("groups"),
        strict=strict,
    )


def build_user_from_groups(subject, username, groups_claim, *, strict=True):
    groups = normalize_groups_claim(groups_claim, strict=strict)
    parsed_permissions = _parse_group_permissions(groups, strict=strict)
    projects = {
        project_id: ProjectAuthorization(
            id=project_id,
            explicit_project_role=project_data["explicit_project_role"],
            labs=dict(sorted(project_data["labs"].items())),
            source_groups=tuple(sorted(project_data["source_groups"])),
        )
        for project_id, project_data in parsed_permissions["projects"].items()
    }
    return AuthorizationUser(
        id=str(subject),
        username=str(username),
        superuser=bool(parsed_permissions["superuser"]),
        projects=projects,
        groups=tuple(groups),
    )


def build_keycloak_authorization(subject, username, groups_claim):
    authorization_user = build_user_from_groups(
        subject=subject,
        username=username,
        groups_claim=groups_claim,
        strict=True,
    )
    return {
        "authorization": authorization_user.to_authorization_dict(),
        "project_access": authorization_user.to_project_access(),
        "authorization_user": authorization_user,
    }


def build_project_access(projects_claim=None, groups_claim=None):
    group_project_access = _build_project_access_from_groups(groups_claim)
    if group_project_access:
        return group_project_access
    return _build_project_access_from_claims(projects_claim)


def build_project_permissions(projects_claim=None, groups_claim=None):
    group_project_access = _build_project_access_from_groups(groups_claim)
    if group_project_access:
        return project_permissions_from_project_access(group_project_access)
    return project_permissions_from_project_access(
        _build_project_access_from_claims(projects_claim)
    )


def normalize_identifier(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def normalize_role(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return ROLE_ALIASES.get(cleaned)


def normalize_role_or_raise(role):
    normalized = normalize_role(role)
    if normalized is None:
        raise GroupParsingError(
            f"Unknown role '{role}'. Supported roles are: {ROLE_VIEW}, {ROLE_ADMIN}"
        )
    return normalized


def normalize_groups(groups):
    if not isinstance(groups, list):
        return []
    return [str(group).strip() for group in groups if str(group).strip()]


def normalize_groups_claim(groups_claim, *, strict=False):
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


def merge_role(current, candidate):
    if candidate is None:
        return current
    if current is None:
        return candidate
    if ROLE_PRECEDENCE[candidate] > ROLE_PRECEDENCE[current]:
        return candidate
    return current


def role_allows(actual_role, required_role):
    actual = normalize_role(actual_role)
    required = normalize_role(required_role)
    if actual is None or required is None:
        return False
    return ROLE_PRECEDENCE[actual] >= ROLE_PRECEDENCE[required]


def project_permissions_from_project_access(project_access):
    permissions = {}
    if not isinstance(project_access, list):
        return permissions

    for project in project_access:
        if not isinstance(project, dict):
            continue
        project_id = normalize_identifier(project.get("id"))
        if not project_id:
            continue

        lab_roles = {
            lab_role["lab"]: lab_role["role"]
            for lab_role in _normalize_lab_roles(project.get("lab_roles"))
        }
        raw_labs = project.get("labs")
        if not isinstance(raw_labs, list):
            raw_labs = []
        labs = {
            lab: {"role": lab_roles.get(lab)}
            for lab in sorted(
                {
                    normalized_lab
                    for normalized_lab in (
                        normalize_identifier(lab) for lab in raw_labs
                    )
                    if normalized_lab
                }
            )
        }
        for lab, role in sorted(lab_roles.items()):
            labs[lab] = {"role": role}

        permissions[project_id] = {
            "project_role": normalize_role(project.get("project_role")),
            "labs": labs,
        }

    return permissions


def _normalize_role_from_group(role, group):
    normalized = normalize_role(role)
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

    project_id = normalize_identifier(path_parts[1])
    if not project_id:
        raise GroupParsingError(f"Malformed group path '{group}': project is required")

    if len(path_parts) == 3:
        return {
            "kind": "project",
            "project": project_id,
            "role": _normalize_role_from_group(path_parts[2], group),
        }

    if len(path_parts) == 5 and path_parts[2].lower() == GROUP_SEGMENT_LABS:
        lab_id = normalize_identifier(path_parts[3])
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


def _parse_group_permissions(groups, *, strict=False):
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
            project_data["explicit_project_role"] = merge_role(
                project_data["explicit_project_role"], parsed["role"]
            )
            continue

        current_lab_role = project_data["labs"].get(parsed["lab"])
        project_data["labs"][parsed["lab"]] = merge_role(
            current_lab_role, parsed["role"]
        )

    return permissions


def _normalize_lab_roles(lab_roles):
    normalized = []
    if not isinstance(lab_roles, list):
        return normalized
    for lab_role in lab_roles:
        if not isinstance(lab_role, dict):
            continue
        lab = normalize_identifier(lab_role.get("lab"))
        role = normalize_role(lab_role.get("role"))
        if not lab or not role:
            continue
        normalized.append({"lab": lab, "role": role})
    normalized.sort(key=lambda item: item["lab"])
    return normalized


def _summarize_role(project_role, lab_roles, labs):
    role = normalize_role(project_role)
    for lab_role in lab_roles:
        role = merge_role(role, lab_role["role"])
    if role is None and labs:
        role = ROLE_VIEW
    return role


def _normalize_project_claim(project):
    if not isinstance(project, dict):
        return None
    project_id = normalize_identifier(project.get("id"))
    if not project_id:
        return None
    labs = project.get("labs")
    if not isinstance(labs, list):
        labs = []
    labs = sorted(
        {
            normalized_lab
            for normalized_lab in (normalize_identifier(lab) for lab in labs)
            if normalized_lab
        }
    )
    raw_role = normalize_role(project.get("role"))
    project_role = normalize_role(project.get("project_role"))
    lab_roles = _normalize_lab_roles(project.get("lab_roles"))
    if project_role is None and raw_role is not None:
        project_role = raw_role
    for lab_role in lab_roles:
        if lab_role["lab"] not in labs:
            labs.append(lab_role["lab"])
    labs = sorted(set(labs))
    effective_role = _summarize_role(project_role, lab_roles, labs)
    source_groups = normalize_groups(project.get("source_groups"))
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
    groups = normalize_groups_claim(groups_claim, strict=True)
    authorization_user = build_user_from_groups(
        subject="",
        username="",
        groups_claim=groups,
        strict=True,
    )
    return authorization_user.to_project_access()
