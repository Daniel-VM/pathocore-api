from core import models


def list_samples(filters: dict):
    queryset = models.Sample.objects.all()

    sample_unique_id = filters.get("sample_unique_id")
    if sample_unique_id:
        queryset = queryset.filter(sample_unique_id=sample_unique_id)

    sequencing_sample_id = filters.get("sequencing_sample_id")
    if sequencing_sample_id:
        queryset = queryset.filter(sequencing_sample_id=sequencing_sample_id)

    collecting_institution = filters.get("collecting_institution")
    if collecting_institution:
        queryset = queryset.filter(collecting_institution__icontains=collecting_institution)

    collecting_lab_sample_id = filters.get("collecting_lab_sample_id")
    if collecting_lab_sample_id:
        queryset = queryset.filter(collecting_lab_sample_id=collecting_lab_sample_id)

    microbiology_lab_sample_id = filters.get("microbiology_lab_sample_id")
    if microbiology_lab_sample_id:
        queryset = queryset.filter(microbiology_lab_sample_id=microbiology_lab_sample_id)

    submitting_lab_sample_id = filters.get("submitting_lab_sample_id")
    if submitting_lab_sample_id:
        queryset = queryset.filter(submitting_lab_sample_id=submitting_lab_sample_id)

    schema_name = filters.get("schema_name")
    schema_version = filters.get("schema_version")
    if schema_name or schema_version:
        schema_filter = {}
        if schema_name:
            schema_filter["schema_name"] = schema_name
        if schema_version:
            schema_filter["schema_version"] = schema_version
        schema_obj = models.Schema.objects.filter(**schema_filter).last()
        if schema_obj is None:
            raise ValueError("Schema not found for provided filters")
        queryset = queryset.filter(schema_obj=schema_obj)

    created_at_from = filters.get("created_at_from")
    if created_at_from:
        queryset = queryset.filter(created_at__gte=created_at_from)

    created_at_to = filters.get("created_at_to")
    if created_at_to:
        queryset = queryset.filter(created_at__lte=created_at_to)

    sequencing_date_from = filters.get("sequencing_date_from")
    if sequencing_date_from:
        queryset = queryset.filter(sequencing_date__gte=sequencing_date_from)

    sequencing_date_to = filters.get("sequencing_date_to")
    if sequencing_date_to:
        queryset = queryset.filter(sequencing_date__lte=sequencing_date_to)

    return queryset
