from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone

from core import models


def _get_sample_payload_fields():
    from core.api.v1.serializers import SampleIngestSerializer

    sample_field_names = {field.name for field in models.Sample._meta.get_fields()}
    sample_payload_fields = set(sample_field_names)
    serializer = SampleIngestSerializer()
    for field_name, field in serializer.fields.items():
        source = field.source if field.source != "*" else field_name
        if source in sample_field_names:
            sample_payload_fields.add(field_name)
    return sample_payload_fields


# TODO: harcoded date due to backward compatibility with models.MetadataValues.analysis_date not allowing nulls
def _extract_analysis_date(payload):
    raw_value = payload.get("bioinformatics_analysis_date") or payload.get(
        "analysis_date"
    )
    if raw_value is None:
        raise ValueError(
            "analysis_date is required (use bioinformatics_analysis_date or analysis_date)"
        )
    if hasattr(raw_value, "date"):
        return raw_value.date()
    if isinstance(raw_value, str):
        parsed = parse_date(raw_value) or parse_datetime(raw_value)
        if parsed is None:
            raise ValueError("analysis_date must be an ISO date or datetime string")
        return parsed.date() if hasattr(parsed, "date") else parsed
    raise ValueError("analysis_date must be a string or date")


def resolve_sample_metadata_schema(sample_obj, schema_name=None, schema_version=None):
    if schema_name and schema_version:
        schema_obj = models.Schema.objects.filter(
            schema_name=schema_name, schema_version=schema_version
        ).last()
        if schema_obj is None:
            raise ValueError("Schema not found for provided name/version")
        if sample_obj.schema_obj_id and sample_obj.schema_obj_id != schema_obj.id:
            raise ValueError("Schema does not match sample schema")
        return schema_obj

    schema_obj = sample_obj.schema_obj
    if schema_obj is None:
        raise ValueError("Sample has no schema assigned")
    return schema_obj


def _get_schema_property(schema_obj, property_name):
    return models.SchemaProperties.objects.filter(
        schemaID=schema_obj, property__iexact=property_name
    ).last()


def _metadata_value(value):
    if value is None:
        return None
    return str(value)


def _normalize_complex_records(field, value):
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        raise ValueError(f"Field '{field}' must be an object or a list of objects")
    records = []
    for index, item in enumerate(value):
        if item is None:
            continue
        if not isinstance(item, dict):
            raise ValueError(
                f"Field '{field}' item {index} must be an object, got "
                f"{type(item).__name__}"
            )
        records.append(item)
    return records


def _prepare_scalar_metadata_value(sample_obj, schema_obj, analysis_date, field, value):
    property_obj = _get_schema_property(schema_obj, field)
    if property_obj is None:
        raise ValueError(f"Field '{field}' is not defined in schema properties")
    return {
        "value": _metadata_value(value),
        "analysis_date": analysis_date,
        "sample": sample_obj,
        "schema_property": property_obj,
    }


def _prepare_complex_metadata_values(
    sample_obj,
    schema_obj,
    analysis_date,
    field,
    value,
):
    group_property_obj = _get_schema_property(schema_obj, field)
    if group_property_obj is None:
        raise ValueError(f"Field '{field}' is not defined in schema properties")

    create_specs = []
    records = _normalize_complex_records(field, value)
    for group_index, record in enumerate(records):
        group_spec = {
            "sample": sample_obj,
            "group_property": group_property_obj,
            "group_index": group_index,
        }
        for child_field, child_value in record.items():
            if child_value is None:
                continue
            child_property_name = f"{field}.{child_field}"
            child_property_obj = _get_schema_property(schema_obj, child_property_name)
            if child_property_obj is None:
                raise ValueError(
                    f"Field '{child_property_name}' is not defined in schema properties"
                )
            create_specs.append(
                {
                    "value": _metadata_value(child_value),
                    "analysis_date": analysis_date,
                    "sample": sample_obj,
                    "schema_property": child_property_obj,
                    "group_spec": group_spec,
                }
            )
    return create_specs


def prepare_sample_metadata_create(sample_obj, schema_obj, payload):
    sample_payload_fields = _get_sample_payload_fields()
    if models.MetadataValues.objects.filter(sample=sample_obj).exists():
        # Prevent repeat ingestion; future PUT/PATCH can handle updates.
        raise ValueError("Metadata already stored for this sample")
    analysis_date = _extract_analysis_date(payload)

    create_specs = []
    for field, value in payload.items():
        if field in ("schema_name", "schema_version"):
            continue
        if field in sample_payload_fields:
            # Skip sample fields; they should be stored via sample ingest only.
            continue
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            create_specs.extend(
                _prepare_complex_metadata_values(
                    sample_obj, schema_obj, analysis_date, field, value
                )
            )
            continue
        create_specs.append(
            _prepare_scalar_metadata_value(
                sample_obj, schema_obj, analysis_date, field, value
            )
        )
    return create_specs


def create_sample_metadata_values(create_specs):
    group_cache = {}
    created_values = []
    for create_spec in create_specs:
        create_spec = dict(create_spec)
        group_spec = create_spec.pop("group_spec", None)
        if group_spec is not None:
            group_key = (
                group_spec["sample"].pk,
                group_spec["group_property"].pk,
                group_spec["group_index"],
            )
            group_obj = group_cache.get(group_key)
            if group_obj is None:
                group_obj = models.MetadataGroup.objects.create(
                    sample=group_spec["sample"],
                    group_property=group_spec["group_property"],
                    group_index=group_spec["group_index"],
                    created_at=timezone.now(),
                )
                group_cache[group_key] = group_obj
            create_spec["group"] = group_obj
        created_values.append(models.MetadataValues.objects.create(**create_spec))
    return created_values
