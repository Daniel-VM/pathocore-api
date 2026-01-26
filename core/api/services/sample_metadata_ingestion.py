from django.utils.dateparse import parse_date, parse_datetime

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
    raw_value = (
        payload.get("bioinformatics_analysis_date")
        or payload.get("analysis_date")
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


def ingest_sample_metadata(sample_obj, schema_obj, payload):
    sample_payload_fields = _get_sample_payload_fields()
    if models.MetadataValues.objects.filter(sample=sample_obj).exists():
        # Prevent repeat ingestion; future PUT/PATCH can handle updates.
        raise ValueError("Metadata already stored for this sample")
    analysis_date = _extract_analysis_date(payload)

    stored_count = 0
    for field, value in payload.items():
        if field in ("schema_name", "schema_version"):
            continue
        if field in sample_payload_fields:
            # Skip sample fields; they should be stored via sample ingest only.
            continue
        if value is None:
            continue
        if isinstance(value, (dict, list)):
            # TODO: support complex fields using MetadataGroup; for now skip them.
            # Example (pseudo):
            # - create MetadataGroup for each object in list
            # - store each sub-property in MetadataValues with group_id
            continue
        property_obj = models.SchemaProperties.objects.filter(
            schemaID=schema_obj, property__iexact=field
        ).last()
        if property_obj is None:
            raise ValueError(f"Field '{field}' is not defined in schema properties")
        models.MetadataValues.objects.create(
            value=str(value),
            analysis_date=analysis_date,
            sample=sample_obj,
            schema_property=property_obj,
        )
        stored_count += 1
    return stored_count
