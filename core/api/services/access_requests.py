from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers

import core.models
from core.api.services import keycloak_admin

ROLE_VIEW = "view"
ROLE_ADMIN = "admin"
SUPPORTED_ROLES = {ROLE_VIEW, ROLE_ADMIN}


class DuplicatePendingAccessRequest(serializers.ValidationError):
    pass


def access_request_catalog():
    catalog = []
    for use_case in getattr(settings, "PATHOCORE_ACCESS_REQUEST_USE_CASES", []):
        name = _normalize_identifier(use_case.get("name"))
        if not name:
            continue
        labs = [
            {
                "name": _normalize_identifier(lab),
                "label": str(lab).strip(),
            }
            for lab in use_case.get("labs", [])
            if _normalize_identifier(lab)
        ]
        catalog.append(
            {
                "name": name,
                "label": use_case.get("label") or name,
                "labs": labs,
                "roles": sorted(SUPPORTED_ROLES),
            }
        )
    return catalog


def normalize_request_fields(attrs):
    attrs["username"] = attrs["username"].strip()
    attrs["email"] = attrs["email"].strip().lower()
    attrs["first_name"] = attrs["first_name"].strip()
    attrs["last_name"] = attrs["last_name"].strip()
    attrs["requested_use_case"] = _normalize_identifier(attrs["requested_use_case"])
    requested_lab = attrs.get("requested_lab")
    attrs["requested_lab"] = (
        _normalize_identifier(requested_lab) if requested_lab else ""
    )
    attrs["requested_role"] = _normalize_role(attrs["requested_role"])
    message = attrs.get("message")
    attrs["message"] = message.strip() if isinstance(message, str) else ""
    return attrs


def validate_requested_scope(attrs):
    use_case = attrs.get("requested_use_case")
    lab = attrs.get("requested_lab") or ""
    role = attrs.get("requested_role")

    use_case_config = _get_use_case_config(use_case)
    if not use_case_config:
        raise serializers.ValidationError({"requested_use_case": "Unknown use-case"})
    if role not in SUPPORTED_ROLES:
        raise serializers.ValidationError({"requested_role": "Unknown role"})

    labs = {_normalize_identifier(item) for item in use_case_config.get("labs", [])}
    labs.discard(None)
    if labs and not lab:
        raise serializers.ValidationError(
            {"requested_lab": "Laboratory is required for this use-case"}
        )
    if lab and lab not in labs:
        raise serializers.ValidationError(
            {"requested_lab": "Unknown laboratory for this use-case"}
        )
    if not labs and lab:
        raise serializers.ValidationError(
            {"requested_lab": "This use-case does not define laboratories"}
        )
    return attrs


def create_access_request(validated_data):
    data = normalize_request_fields(dict(validated_data))
    validate_requested_scope(data)
    duplicate = core.models.AccessRequest.objects.filter(
        status=core.models.AccessRequest.STATUS_PENDING,
        requested_use_case=data["requested_use_case"],
        requested_lab=data["requested_lab"] or None,
        requested_role=data["requested_role"],
    ).filter(Q(username=data["username"]) | Q(email=data["email"]))
    if duplicate.exists():
        raise DuplicatePendingAccessRequest(
            {"error": "An equivalent pending access request already exists"}
        )

    access_request = core.models.AccessRequest.objects.create(
        username=data["username"],
        email=data["email"],
        first_name=data["first_name"],
        last_name=data["last_name"],
        requested_use_case=data["requested_use_case"],
        requested_lab=data["requested_lab"] or None,
        requested_role=data["requested_role"],
        message=data.get("message") or "",
    )
    notify_access_request_created(access_request)
    return access_request


def approve_access_request(access_request, reviewed_by, review_note=""):
    if access_request.status != core.models.AccessRequest.STATUS_PENDING:
        raise serializers.ValidationError(
            {"status": "Only pending requests can be approved"}
        )

    group_path = build_group_path(access_request)
    keycloak_result = keycloak_admin.provision_approved_user(access_request, group_path)

    with transaction.atomic():
        locked_request = core.models.AccessRequest.objects.select_for_update().get(
            pk=access_request.pk
        )
        if locked_request.status != core.models.AccessRequest.STATUS_PENDING:
            raise serializers.ValidationError(
                {"status": "Only pending requests can be approved"}
            )
        locked_request.status = core.models.AccessRequest.STATUS_APPROVED
        locked_request.reviewed_at = timezone.now()
        locked_request.reviewed_by = _local_reviewer_or_none(reviewed_by)
        locked_request.reviewed_by_identity = _reviewer_identity(reviewed_by)
        locked_request.review_note = review_note or ""
        locked_request.approved_group = group_path
        locked_request.keycloak_user_id = keycloak_result["user_id"]
        locked_request.save(
            update_fields=[
                "status",
                "reviewed_at",
                "reviewed_by",
                "reviewed_by_identity",
                "review_note",
                "approved_group",
                "keycloak_user_id",
            ]
        )
    notify_access_request_reviewed(locked_request)
    return locked_request


def reject_access_request(access_request, reviewed_by, review_note=""):
    if access_request.status != core.models.AccessRequest.STATUS_PENDING:
        raise serializers.ValidationError(
            {"status": "Only pending requests can be rejected"}
        )

    with transaction.atomic():
        locked_request = core.models.AccessRequest.objects.select_for_update().get(
            pk=access_request.pk
        )
        if locked_request.status != core.models.AccessRequest.STATUS_PENDING:
            raise serializers.ValidationError(
                {"status": "Only pending requests can be rejected"}
            )
        locked_request.status = core.models.AccessRequest.STATUS_REJECTED
        locked_request.reviewed_at = timezone.now()
        locked_request.reviewed_by = _local_reviewer_or_none(reviewed_by)
        locked_request.reviewed_by_identity = _reviewer_identity(reviewed_by)
        locked_request.review_note = review_note or ""
        locked_request.save(
            update_fields=[
                "status",
                "reviewed_at",
                "reviewed_by",
                "reviewed_by_identity",
                "review_note",
            ]
        )
    notify_access_request_reviewed(locked_request)
    return locked_request


def revoke_access_request(access_request, reviewed_by, review_note=""):
    if access_request.status != core.models.AccessRequest.STATUS_APPROVED:
        raise serializers.ValidationError(
            {"status": "Only approved requests can be revoked"}
        )
    if not access_request.approved_group:
        raise serializers.ValidationError(
            {"approved_group": "Approved group is missing for this request"}
        )

    keycloak_result = keycloak_admin.revoke_approved_user_access(
        access_request,
        access_request.approved_group,
    )

    with transaction.atomic():
        locked_request = core.models.AccessRequest.objects.select_for_update().get(
            pk=access_request.pk
        )
        if locked_request.status != core.models.AccessRequest.STATUS_APPROVED:
            raise serializers.ValidationError(
                {"status": "Only approved requests can be revoked"}
            )
        locked_request.status = core.models.AccessRequest.STATUS_REVOKED
        locked_request.reviewed_at = timezone.now()
        locked_request.reviewed_by = _local_reviewer_or_none(reviewed_by)
        locked_request.reviewed_by_identity = _reviewer_identity(reviewed_by)
        locked_request.review_note = review_note or ""
        locked_request.keycloak_user_id = (
            keycloak_result.get("user_id") or locked_request.keycloak_user_id
        )
        locked_request.save(
            update_fields=[
                "status",
                "reviewed_at",
                "reviewed_by",
                "reviewed_by_identity",
                "review_note",
                "keycloak_user_id",
            ]
        )
    notify_access_request_revoked(locked_request)
    return locked_request


def build_group_path(access_request):
    base_path = f"/use-cases/{access_request.requested_use_case}"
    if access_request.requested_lab:
        return (
            f"{base_path}/labs/"
            f"{access_request.requested_lab}/{access_request.requested_role}"
        )
    return f"{base_path}/{access_request.requested_role}"


def notify_access_request_created(access_request):
    send_mail(
        subject="PathoCore access request received",
        message=(
            f"Hello {access_request.first_name},\n\n"
            "We have received your PathoCore access request and it is pending "
            "administrator review.\n\n"
            f"Requested access: {build_group_path(access_request)}\n"
            "You will receive another notification once the request has been "
            "reviewed.\n"
        ),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[access_request.email],
        fail_silently=True,
    )

    recipients = _access_request_admin_recipients(access_request)
    if not recipients:
        return
    send_mail(
        subject=f"PathoCore access request pending: {access_request.username}",
        message=(
            f"User: {access_request.username} <{access_request.email}>\n"
            f"Requested: {build_group_path(access_request)}\n"
            f"Message: {access_request.message or '-'}"
        ),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=recipients,
        fail_silently=True,
    )


def _access_request_admin_recipients(access_request):
    recipients = []
    admin_group_path = f"/use-cases/{access_request.requested_use_case}/admin"
    try:
        recipients.extend(keycloak_admin.list_group_member_emails(admin_group_path))
    except keycloak_admin.KeycloakAdminError:
        pass

    recipients.extend(getattr(settings, "PATHOCORE_ACCESS_REQUEST_ADMIN_EMAILS", []))
    return _unique_emails(recipients)


def _unique_emails(emails):
    unique = []
    seen = set()
    for email in emails:
        normalized = str(email).strip().lower()
        if normalized and normalized not in seen:
            unique.append(normalized)
            seen.add(normalized)
    return unique


def notify_access_request_reviewed(access_request):
    if access_request.status == core.models.AccessRequest.STATUS_APPROVED:
        status_message = (
            "Your PathoCore access request has been approved. "
            "If this is your first access, you will receive a Keycloak email "
            "to verify your email and set your password."
        )
    elif access_request.status == core.models.AccessRequest.STATUS_REJECTED:
        status_message = "Your PathoCore access request has been rejected."
    else:
        status_message = (
            f"Your PathoCore access request status changed to "
            f"{access_request.status}."
        )

    send_mail(
        subject=f"PathoCore access request {access_request.status}",
        message=(
            f"{status_message}\n\n"
            f"Requested access: {build_group_path(access_request)}\n"
            f"Review note: {access_request.review_note or '-'}\n"
        ),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[access_request.email],
        fail_silently=True,
    )


def notify_access_request_revoked(access_request):
    send_mail(
        subject="PathoCore access revoked",
        message=(
            "Your PathoCore access has been revoked.\n\n"
            f"Revoked access: {access_request.approved_group or build_group_path(access_request)}\n"
            f"Review note: {access_request.review_note or '-'}\n"
        ),
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[access_request.email],
        fail_silently=True,
    )


def _get_use_case_config(use_case_name):
    normalized_name = _normalize_identifier(use_case_name)
    for use_case in getattr(settings, "PATHOCORE_ACCESS_REQUEST_USE_CASES", []):
        if _normalize_identifier(use_case.get("name")) == normalized_name:
            return use_case
    return None


def _local_reviewer_or_none(user):
    user_model = get_user_model()
    return user if isinstance(user, user_model) and user.pk else None


def _reviewer_identity(user):
    username = getattr(user, "username", None)
    user_id = getattr(user, "id", None)
    if username and user_id:
        return f"{username} ({user_id})"
    if username:
        return str(username)
    if user_id:
        return str(user_id)
    return ""


def _normalize_identifier(value):
    if not isinstance(value, str):
        return None
    cleaned = value.strip().lower()
    return cleaned or None


def _normalize_role(value):
    if not isinstance(value, str):
        return None
    role = value.strip().lower()
    return role if role in SUPPORTED_ROLES else None
