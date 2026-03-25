import json

from django.core.files.base import ContentFile

import core.models
from core.api.utils import access_control


def _normalize_str(value):
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned if cleaned else None
    return value


def _stringify_examples(examples):
    if examples is None:
        return None
    if isinstance(examples, list):
        return "; ".join([str(item) for item in examples if item is not None])[:250]
    return str(examples)[:250]


def prepare_schema_create(payload, request_user):
    if request_user is None:
        raise ValueError("User is required to upload a schema")

    schema_data = payload.get("schema")
    if not isinstance(schema_data, dict):
        raise ValueError("schema must be a JSON object")

    schema_name = _normalize_str(payload.get("schema_name")) or _normalize_str(
        schema_data.get("title") or schema_data.get("schema_name")
    )
    schema_version = _normalize_str(payload.get("schema_version")) or _normalize_str(
        schema_data.get("version") or schema_data.get("schema_version")
    )
    if not schema_name or not schema_version:
        raise ValueError("schema_name and schema_version are required")

    if core.models.Schema.objects.filter(
        schema_name=schema_name, schema_version=schema_version
    ).exists():
        raise ValueError("Schema already exists")

    properties = schema_data.get("properties")
    if not isinstance(properties, dict) or not properties:
        raise ValueError("schema properties are required")

    schema_in_use = payload.get("schema_in_use")
    if schema_in_use is None:
        schema_in_use = True

    schema_app_name = _normalize_str(payload.get("schema_app_name"))
    schema_app_name = access_control.validate_allowed_project_name(schema_app_name)

    file_name = f"{schema_name}_{schema_version}.json".replace(" ", "_")
    file_payload = ContentFile(
        json.dumps(schema_data, ensure_ascii=False, indent=2), name=file_name
    )

    required_fields = schema_data.get("required") or []
    if not isinstance(required_fields, list):
        required_fields = []

    property_specs = []
    for prop_name, prop_data in properties.items():
        if not isinstance(prop_data, dict):
            continue

        prop_type = prop_data.get("type")
        if isinstance(prop_type, list):
            prop_type = prop_type[0] if prop_type else None
        if prop_type is None and isinstance(prop_data.get("anyOf"), list):
            for entry in prop_data["anyOf"]:
                if isinstance(entry, dict) and entry.get("type"):
                    prop_type = entry["type"]
                    break
        if prop_type is None:
            prop_type = "string"

        has_enum = (
            isinstance(prop_data.get("enum"), list) and len(prop_data["enum"]) > 0
        )

        property_specs.append(
            {
                "property": prop_name,
                "classification_name": _normalize_str(prop_data.get("classification")),
                "examples": _stringify_examples(prop_data.get("examples")),
                "ontology": _normalize_str(prop_data.get("ontology")),
                "type": str(prop_type)[:20],
                "format": _normalize_str(prop_data.get("format")),
                "description": _normalize_str(prop_data.get("description")),
                "label": _normalize_str(prop_data.get("label")),
                "required": prop_name in required_fields,
                "options": has_enum,
                "fill_mode": _normalize_str(prop_data.get("fill_mode")),
                "enum_values": [str(item) for item in prop_data.get("enum", [])]
                if has_enum
                else [],
            }
        )

    return {
        "schema_fields": {
            "file_name": file_payload,
            "user_name": request_user,
            "schema_name": schema_name,
            "schema_version": schema_version,
            "schema_default": False,
            "schema_in_use": schema_in_use,
            "schema_app_name": schema_app_name,
        },
        "deactivate_existing_filter": {
            "schema_app_name": schema_app_name,
            "schema_name": schema_name,
            "schema_in_use": True,
        }
        if schema_in_use
        else None,
        "property_specs": property_specs,
    }
