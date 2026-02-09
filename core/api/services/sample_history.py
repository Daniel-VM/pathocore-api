from core import models


def list_sample_history(filters: dict):
    queryset = models.SampleStateHistory.objects.select_related(
        "sample", "state", "error_name"
    )

    sample_id = filters.get("sample_id")
    if sample_id:
        queryset = queryset.filter(sample_id=sample_id)

    sample_unique_id = filters.get("sample_unique_id")
    if sample_unique_id:
        normalized = sample_unique_id.strip()
        if normalized:
            queryset = queryset.filter(sample__sample_unique_id=normalized)

    sequencing_sample_id = filters.get("sequencing_sample_id")
    if sequencing_sample_id:
        normalized = sequencing_sample_id.strip()
        if normalized:
            queryset = queryset.filter(sample__sequencing_sample_id=normalized)

    submitting_lab_sample_id = filters.get("submitting_lab_sample_id")
    if submitting_lab_sample_id:
        normalized = submitting_lab_sample_id.strip()
        if normalized:
            queryset = queryset.filter(sample__submitting_lab_sample_id=normalized)

    collecting_lab_isolate_id = filters.get("collecting_lab_isolate_id")
    if collecting_lab_isolate_id:
        normalized = collecting_lab_isolate_id.strip()
        if normalized:
            queryset = queryset.filter(sample__collecting_lab_isolate_id=normalized)

    collecting_lab_sample_id = filters.get("collecting_lab_sample_id")
    if collecting_lab_sample_id:
        normalized = collecting_lab_sample_id.strip()
        if normalized:
            queryset = queryset.filter(sample__collecting_lab_sample_id=normalized)

    state_id = filters.get("state_id")
    if state_id:
        queryset = queryset.filter(state_id=state_id)

    state = filters.get("state")
    if state:
        normalized = state.strip()
        if normalized:
            queryset = queryset.filter(state__state__iexact=normalized)

    error_name_id = filters.get("error_name_id")
    if error_name_id:
        queryset = queryset.filter(error_name_id=error_name_id)

    error_name = filters.get("error_name")
    if error_name:
        normalized = error_name.strip()
        if normalized:
            queryset = queryset.filter(error_name__error_name__iexact=normalized)

    is_current = filters.get("is_current")
    if is_current is not None:
        queryset = queryset.filter(is_current=is_current)

    changed_at_from = filters.get("changed_at_from")
    if changed_at_from:
        queryset = queryset.filter(changed_at__gte=changed_at_from)

    changed_at_to = filters.get("changed_at_to")
    if changed_at_to:
        queryset = queryset.filter(changed_at__lte=changed_at_to)

    return queryset.order_by("-is_current", "-changed_at", "-id")
