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


def _schema_property_type(prop_data):
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
    return str(prop_type)[:20]


def _nested_schema_properties(prop_data):
    if not isinstance(prop_data, dict):
        return None
    properties = prop_data.get("properties")
    if isinstance(properties, dict):
        return properties
    items = prop_data.get("items")
    if isinstance(items, dict) and isinstance(items.get("properties"), dict):
        return items["properties"]
    return None


def _nested_required_fields(prop_data):
    required = prop_data.get("required")
    items = prop_data.get("items")
    if isinstance(items, dict) and isinstance(items.get("required"), list):
        required = items["required"]
    if not isinstance(required, list):
        return []
    return required


def _property_spec(
    property_path,
    prop_data,
    *,
    required=False,
    inherited_classification=None,
):
    if len(property_path) > 50:
        raise ValueError(
            f"schema property path '{property_path}' exceeds 50 characters"
        )

    classification_name = (
        _normalize_str(prop_data.get("classification")) or inherited_classification
    )
    has_enum = isinstance(prop_data.get("enum"), list) and len(prop_data["enum"]) > 0

    return {
        "property": property_path,
        "classification_name": classification_name,
        "examples": _stringify_examples(prop_data.get("examples")),
        "ontology": _normalize_str(prop_data.get("ontology")),
        "type": _schema_property_type(prop_data),
        "format": _normalize_str(prop_data.get("format")),
        "description": _normalize_str(prop_data.get("description")),
        "label": _normalize_str(prop_data.get("label")),
        "required": required,
        "options": has_enum,
        "fill_mode": _normalize_str(prop_data.get("fill_mode")),
        "enum_values": (
            [str(item) for item in prop_data.get("enum", [])] if has_enum else []
        ),
    }


def _iter_schema_property_specs(
    properties,
    required_fields,
    *,
    parent_path="",
    inherited_classification=None,
):
    for prop_name, prop_data in properties.items():
        if not isinstance(prop_data, dict):
            continue

        property_path = f"{parent_path}.{prop_name}" if parent_path else prop_name
        classification_name = (
            _normalize_str(prop_data.get("classification")) or inherited_classification
        )

        yield _property_spec(
            property_path,
            prop_data,
            required=prop_name in required_fields,
            inherited_classification=inherited_classification,
        )

        nested_properties = _nested_schema_properties(prop_data)
        if nested_properties:
            yield from _iter_schema_property_specs(
                nested_properties,
                _nested_required_fields(prop_data),
                parent_path=property_path,
                inherited_classification=classification_name,
            )


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
    access_control.ensure_project_write_access(request_user, schema_app_name)

    file_name = f"{schema_name}_{schema_version}.json".replace(" ", "_")
    file_payload = ContentFile(
        json.dumps(schema_data, ensure_ascii=False, indent=2), name=file_name
    )

    required_fields = schema_data.get("required") or []
    if not isinstance(required_fields, list):
        required_fields = []

    property_specs = []
    seen_properties = set()
    for property_spec in _iter_schema_property_specs(properties, required_fields):
        property_key = property_spec["property"].lower()
        if property_key in seen_properties:
            continue
        seen_properties.add(property_key)
        property_specs.append(property_spec)

    return {
        "schema_fields": {
            "file_name": file_payload,
            "user_name": access_control.get_persisted_user(request_user),
            "schema_name": schema_name,
            "schema_version": schema_version,
            "schema_default": False,
            "schema_in_use": schema_in_use,
            "schema_app_name": schema_app_name,
        },
        "deactivate_existing_filter": (
            {
                "schema_app_name": schema_app_name,
                "schema_name": schema_name,
                "schema_in_use": True,
            }
            if schema_in_use
            else None
        ),
        "property_specs": property_specs,
    }
