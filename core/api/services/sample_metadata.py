from django.db.models.functions import Lower

from core import models


def _normalize_list(values):
    if values is None:
        return None
    if isinstance(values, str):
        values = [values]
    cleaned = [item.strip() for item in values if item and item.strip()]
    return cleaned or None


def list_sample_metadata(sample_obj, classifications=None, properties=None):
    queryset = models.MetadataValues.objects.filter(sample=sample_obj).select_related(
        "schema_property", "schema_property__classificationID", "group"
    )
    classifications = _normalize_list(classifications)
    properties = _normalize_list(properties)
    if classifications:
        queryset = queryset.filter(
            schema_property__classificationID__classification_name__in=classifications
        )
    if properties:
        queryset = queryset.filter(schema_property__property__in=properties)

    results = []
    for item in queryset:
        classification_obj = item.schema_property.classificationID
        classification_name = (
            classification_obj.classification_name if classification_obj else None
        )
        results.append(
            {
                "property": item.schema_property.property,
                "value": item.value,
                "classification": classification_name,
                "group_id": item.group_id,
                "group_index": item.group.group_index if item.group_id else None,
            }
        )
    return results


def list_samples_by_property(property_name, value=None):
    if not property_name or not isinstance(property_name, str):
        raise ValueError("property is required")
    normalized = property_name.strip()
    if not normalized:
        raise ValueError("property is required")
    value_filter = None
    if value is not None:
        if not isinstance(value, str):
            raise ValueError("value must be a string")
        value_filter = value.strip()
        if not value_filter:
            raise ValueError("value cannot be empty")
    queryset = (
        models.MetadataValues.objects.filter(
            schema_property__property__iexact=normalized
        )
        .select_related("sample")
        .order_by("sample__sample_unique_id")
    )
    if value_filter is not None:
        queryset = queryset.filter(value__iexact=value_filter)
    results = []
    for item in queryset:
        results.append(
            {
                "sample_unique_id": item.sample.sample_unique_id,
                "value": item.value,
            }
        )
    return results


def search_samples_metadata(filters, match="all"):
    if not filters:
        raise ValueError("At least one filter is required")
    if match not in {"all", "any"}:
        raise ValueError("match must be 'all' or 'any'")

    normalized_filters = []
    for item in filters:
        prop = item.get("property")
        if not prop or not isinstance(prop, str):
            raise ValueError("property is required")
        prop = prop.strip()
        if not prop:
            raise ValueError("property is required")
        value = item.get("value")
        if value is not None:
            if not isinstance(value, str):
                raise ValueError("value must be a string")
            value = value.strip()
            if not value:
                raise ValueError("value cannot be empty")
        normalized_filters.append({"property": prop, "value": value})

    sample_sets = []
    # Validate properties exist in any schema (not restricted to schema_in_use).
    requested_props = {item["property"].lower() for item in normalized_filters}
    existing_props = set(
        models.SchemaProperties.objects.annotate(prop=Lower("property"))
        .values_list("prop", flat=True)
        .distinct()
    )
    missing_props = sorted(requested_props - existing_props)
    if missing_props:
        raise ValueError(
            "Unknown property(ies): " + ", ".join(missing_props)
        )

    for item in normalized_filters:
        queryset = models.MetadataValues.objects.filter(
            schema_property__property__iexact=item["property"]
        )
        if item["value"] is not None:
            queryset = queryset.filter(value__iexact=item["value"])
        sample_sets.append(set(queryset.values_list("sample_id", flat=True)))

    if match == "all":
        matched_ids = set.intersection(*sample_sets) if sample_sets else set()
    else:
        matched_ids = set.union(*sample_sets) if sample_sets else set()

    if not matched_ids:
        return []

    properties = {item["property"].lower() for item in normalized_filters}
    results = {}
    queryset = (
        models.MetadataValues.objects.filter(sample_id__in=matched_ids)
        .select_related("sample", "schema_property")
        .order_by("sample__sample_unique_id")
    )
    for item in queryset:
        if item.schema_property is None:
            continue
        item_property = item.schema_property.property
        matches_filter = False
        for current_filter in normalized_filters:
            if item_property.lower() != current_filter["property"].lower():
                continue
            if current_filter["value"] is None:
                matches_filter = True
            elif (
                item.value is not None
                and item.value.lower() == current_filter["value"].lower()
            ):
                matches_filter = True
            if matches_filter:
                break
        if not matches_filter:
            continue
        if item_property.lower() not in properties:
            continue
        entry = results.setdefault(
            item.sample_id,
            {"sample_unique_id": item.sample.sample_unique_id, "values": {}},
        )
        values_map = entry["values"]
        if item_property in values_map:
            existing = values_map[item_property]
            if isinstance(existing, list):
                existing.append(item.value)
            else:
                values_map[item_property] = [existing, item.value]
        else:
            values_map[item_property] = item.value

    return list(results.values())


def list_properties_by_classification(classification_name):
    if not classification_name or not isinstance(classification_name, str):
        raise ValueError("classification is required")
    normalized = classification_name.strip()
    if not normalized:
        raise ValueError("classification is required")
    properties = (
        models.SchemaProperties.objects.filter(
            classificationID__classification_name__iexact=normalized
        )
        .values_list("property", flat=True)
        .distinct()
        .order_by("property")
    )
    return [{"property": name} for name in properties]
