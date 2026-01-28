from typing import Tuple

from core import models


def ingest_sample(
    sample_payload: dict, request_user=None
) -> Tuple[models.Sample, bool]:
    raw_unique_id = sample_payload.get("sample_unique_id")
    if raw_unique_id is None:
        raise ValueError("sample_unique_id is required to ingest a sample")
    if not isinstance(raw_unique_id, str):
        raise ValueError("sample_unique_id must be a string")
    normalized_id = raw_unique_id.strip()
    if not normalized_id:
        raise ValueError("sample_unique_id cannot be empty")
    unique_max_length = models.Sample._meta.get_field("sample_unique_id").max_length
    if len(normalized_id) > unique_max_length:
        raise ValueError(
            f"sample_unique_id is too long (max {unique_max_length} characters)"
        )
    if models.Sample.objects.filter(sample_unique_id=normalized_id).exists():
        raise ValueError("Sample already exists")

    schema_name = sample_payload.get("schema_name")
    schema_version = sample_payload.get("schema_version")
    if isinstance(schema_name, str):
        schema_name = schema_name.strip()
    if isinstance(schema_version, str):
        schema_version = schema_version.strip()
    if not schema_name or not schema_version:
        raise ValueError("schema_name and schema_version are required")
    schema_obj = models.Schema.objects.filter(
        schema_name=schema_name, schema_version=schema_version
    ).last()
    if schema_obj is None:
        raise ValueError(
            f"Schema not found for name={schema_name} version={schema_version}"
        )

    defaults = {}
    sample_field_names = {
        f.name
        for f in models.Sample._meta.get_fields()
        if getattr(f, "is_relation", False) is False
    }
    excluded_defaults = {"id", "sample_unique_id", "created_at"}
    for key, value in sample_payload.items():
        if key in excluded_defaults or key not in sample_field_names:
            continue
        if value is None:
            continue
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                continue
            defaults[key] = trimmed
        else:
            defaults[key] = value

    sample_obj = models.Sample.objects.create(
        sample_unique_id=normalized_id,
        schema_obj=schema_obj,
        **defaults,
    )

    if request_user and getattr(sample_obj, "user_id", None) is None:
        sample_obj.user = request_user
        sample_obj.save(update_fields=["user"])

    return sample_obj, True
