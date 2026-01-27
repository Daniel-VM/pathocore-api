import json

import core.models


def list_schemas(filters=None):
    filters = filters or {}
    queryset = core.models.Schema.objects.all()

    schema_name = filters.get("schema_name")
    if schema_name:
        queryset = queryset.filter(schema_name__iexact=schema_name)

    schema_version = filters.get("schema_version")
    if schema_version:
        queryset = queryset.filter(schema_version__iexact=schema_version)

    if "schema_in_use" in filters:
        queryset = queryset.filter(schema_in_use=filters["schema_in_use"])
    if "schema_default" in filters:
        queryset = queryset.filter(schema_default=filters["schema_default"])

    schema_apps_name = filters.get("schema_apps_name")
    if schema_apps_name:
        queryset = queryset.filter(schema_apps_name__iexact=schema_apps_name)

    return queryset.order_by("-generated_at", "-id")


def get_schema_by_name_version(schema_name, schema_version):
    schema_obj = core.models.Schema.objects.filter(
        schema_name=schema_name, schema_version=schema_version
    ).last()
    if schema_obj is None:
        return None, None

    try:
        with schema_obj.file_name.open("r") as handle:
            schema_json = json.load(handle)
    except Exception:
        schema_json = None

    return schema_obj, schema_json
