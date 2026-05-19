from collections import defaultdict

from django.db.models import Q, Exists, OuterRef, Subquery

from core import models
from core.api.utils import access_control


def _normalize_list(values):
    if values is None:
        return None
    if isinstance(values, str):
        values = [values]
    cleaned = [item.strip() for item in values if item and item.strip()]
    return cleaned or None


def _complex_parent_property(property_name):
    if "." not in property_name:
        return None
    parent_name, _, child_name = property_name.partition(".")
    if not parent_name.strip() or not child_name.strip():
        return None
    return parent_name.strip()


def list_sample_metadata(
    sample_obj, classifications=None, properties=None, request_user=None
):
    queryset = models.MetadataValues.objects.filter(sample=sample_obj).select_related(
        "schema_property",
        "schema_property__classificationID",
        "group",
        "group__group_property",
    )
    if request_user is not None:
        queryset = access_control.apply_metadata_values_scope(queryset, request_user)
    classifications = _normalize_list(classifications)
    properties = _normalize_list(properties)
    if classifications:
        queryset = queryset.filter(
            schema_property__classificationID__classification_name__in=classifications
        )
    if properties:
        queryset = queryset.filter(schema_property__property__in=properties)

    results = []
    for item in queryset.order_by(
        "group__group_property__property",
        "group__group_index",
        "schema_property__property",
        "id",
    ):
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
                "group_property": (
                    item.group.group_property.property if item.group_id else None
                ),
            }
        )
    return results


def list_samples_by_property(property_name, value=None, request_user=None):
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
    if request_user is not None:
        queryset = access_control.apply_metadata_values_scope(queryset, request_user)
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


def list_samples_by_metadata_query(
    property_name=None,
    values=None,
    match="any",
    classification=None,
    request_user=None,
):
    if match not in {"all", "any"}:
        raise ValueError("match must be 'all' or 'any'")

    normalized_property = None
    if property_name is not None:
        if not isinstance(property_name, str):
            raise ValueError("property must be a string")
        normalized_property = property_name.strip()
        if not normalized_property:
            raise ValueError("property cannot be empty")
        property_queryset = models.SchemaProperties.objects.all()
        if request_user is not None:
            property_queryset = property_queryset.filter(
                schemaID__in=access_control.apply_schema_scope(
                    models.Schema.objects.all(), request_user
                )
            )
        property_exists = property_queryset.filter(
            property__iexact=normalized_property
        ).exists()
        if not property_exists:
            raise ValueError(f"Unknown property: {normalized_property}")

    normalized_values = []
    if values is not None:
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            raise ValueError("value must be a string or repeated query parameter")
        for value in values:
            if not isinstance(value, str):
                raise ValueError("value must be a string")
            current = value.strip()
            if not current:
                raise ValueError("value cannot be empty")
            normalized_values.append(current)
        normalized_values = list(dict.fromkeys(normalized_values))

    normalized_classification = None
    if classification is not None:
        if not isinstance(classification, str):
            raise ValueError("classification must be a string")
        normalized_classification = classification.strip()
        if not normalized_classification:
            raise ValueError("classification cannot be empty")

    # Build sample scope first and use EXISTS subqueries to avoid large Python-side
    # set operations on metadata tables.
    samples_queryset = models.Sample.objects.all()
    if request_user is not None:
        samples_queryset = access_control.apply_sample_scope(
            samples_queryset, request_user
        )

    metadata_base_filter = Q()
    if normalized_property:
        metadata_base_filter &= Q(schema_property__property__iexact=normalized_property)
    if normalized_classification:
        metadata_base_filter &= Q(
            schema_property__classificationID__classification_name__iexact=normalized_classification
        )

    values_q = Q()
    if normalized_values:
        for value in normalized_values:
            values_q |= Q(value__iexact=value)

    if normalized_values:
        if match == "any":
            exists_queryset = (
                models.MetadataValues.objects.filter(sample_id=OuterRef("pk"))
                .filter(metadata_base_filter)
                .filter(values_q)
            )
            matched_samples = samples_queryset.filter(Exists(exists_queryset))
        else:
            matched_samples = samples_queryset
            for value in normalized_values:
                exists_queryset = (
                    models.MetadataValues.objects.filter(sample_id=OuterRef("pk"))
                    .filter(metadata_base_filter)
                    .filter(value__iexact=value)
                )
                matched_samples = matched_samples.filter(Exists(exists_queryset))
    else:
        exists_queryset = models.MetadataValues.objects.filter(
            sample_id=OuterRef("pk")
        ).filter(metadata_base_filter)
        matched_samples = samples_queryset.filter(Exists(exists_queryset))

    if not matched_samples.exists():
        return []

    metadata_queryset = models.MetadataValues.objects.filter(
        sample_id__in=Subquery(matched_samples.values("id"))
    ).filter(metadata_base_filter)
    if normalized_values:
        metadata_queryset = metadata_queryset.filter(values_q)

    metadata_rows = metadata_queryset.values(
        "sample_id",
        "sample__sample_unique_id",
        "schema_property__property",
        "value",
    ).order_by("sample__sample_unique_id", "sample_id")

    sample_to_values = {}
    for row in metadata_rows:
        item_property = row["schema_property__property"]
        if item_property is None:
            continue
        sample_id = row["sample_id"]
        entry = sample_to_values.setdefault(
            sample_id,
            {"sample_unique_id": row["sample__sample_unique_id"], "values": {}},
        )
        values_map = entry["values"]
        value = row["value"]
        if item_property in values_map:
            existing = values_map[item_property]
            if isinstance(existing, list):
                existing.append(value)
            else:
                values_map[item_property] = [existing, value]
        else:
            values_map[item_property] = value

    return list(sample_to_values.values())


def search_samples_metadata(filters, match="all", request_user=None):
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
        normalized_filters.append(
            {
                "property": prop,
                "property_lower": prop.lower(),
                "parent_property": _complex_parent_property(prop),
                "value": value,
            }
        )

    # Validate properties exist in user-visible schemas and resolve each filter
    # property to concrete schema_property ids (possibly several across schemas).
    properties_queryset = models.SchemaProperties.objects.all()
    if request_user is not None:
        properties_queryset = properties_queryset.filter(
            schemaID__in=access_control.apply_schema_scope(
                models.Schema.objects.all(), request_user
            )
        )

    property_ids_by_lower_name = {}
    missing_props = []
    for item in normalized_filters:
        prop_lower = item["property"].lower()
        if prop_lower in property_ids_by_lower_name:
            continue
        prop_ids = list(
            properties_queryset.filter(property__iexact=item["property"]).values_list(
                "id", flat=True
            )
        )
        if not prop_ids:
            missing_props.append(prop_lower)
            continue
        property_ids_by_lower_name[prop_lower] = prop_ids

    if missing_props:
        missing_props = sorted(set(missing_props))
        raise ValueError("Unknown property(ies): " + ", ".join(missing_props))

    filter_conditions = []
    for item in normalized_filters:
        prop_ids = property_ids_by_lower_name[item["property_lower"]]
        condition = Q(schema_property_id__in=prop_ids)
        if item["value"] is not None:
            condition &= Q(value__iexact=item["value"])
        filter_conditions.append(condition)

    samples_queryset = models.Sample.objects.all()
    if request_user is not None:
        samples_queryset = access_control.apply_sample_scope(
            samples_queryset, request_user
        )

    if match == "any":
        any_condition = Q()
        for condition in filter_conditions:
            any_condition |= condition
        exists_queryset = models.MetadataValues.objects.filter(
            sample_id=OuterRef("pk")
        ).filter(any_condition)
        matched_samples = samples_queryset.filter(Exists(exists_queryset))
    else:
        parent_grouped_filters = defaultdict(list)
        simple_filter_conditions = []
        for item, condition in zip(normalized_filters, filter_conditions):
            parent_property = item["parent_property"]
            if parent_property:
                parent_grouped_filters[parent_property.lower()].append(
                    {
                        "parent_property": parent_property,
                        "property": item["property"],
                        "condition": condition,
                    }
                )
            else:
                simple_filter_conditions.append(condition)

        same_group_filters = []
        for grouped_items in parent_grouped_filters.values():
            distinct_child_properties = {
                item["property"].lower() for item in grouped_items
            }
            if len(grouped_items) > 1 and len(distinct_child_properties) > 1:
                parent_property = grouped_items[0]["parent_property"]
                parent_ids = list(
                    properties_queryset.filter(
                        property__iexact=parent_property
                    ).values_list("id", flat=True)
                )
                if not parent_ids:
                    raise ValueError(f"Unknown property: {parent_property}")
                same_group_filters.append(
                    {
                        "parent_ids": parent_ids,
                        "conditions": [item["condition"] for item in grouped_items],
                    }
                )
            else:
                simple_filter_conditions.extend(
                    item["condition"] for item in grouped_items
                )

        matched_samples = samples_queryset
        for condition in simple_filter_conditions:
            exists_queryset = models.MetadataValues.objects.filter(
                sample_id=OuterRef("pk")
            ).filter(condition)
            matched_samples = matched_samples.filter(Exists(exists_queryset))
        for same_group_filter in same_group_filters:
            group_queryset = models.MetadataGroup.objects.filter(
                sample_id=OuterRef("pk"),
                group_property_id__in=same_group_filter["parent_ids"],
            )
            for condition in same_group_filter["conditions"]:
                value_queryset = models.MetadataValues.objects.filter(
                    group_id=OuterRef("pk")
                ).filter(condition)
                group_queryset = group_queryset.filter(Exists(value_queryset))
            matched_samples = matched_samples.filter(Exists(group_queryset))

    if not matched_samples.exists():
        return []

    output_filter = Q()
    for condition in filter_conditions:
        output_filter |= condition

    metadata_rows = (
        models.MetadataValues.objects.filter(
            sample_id__in=Subquery(matched_samples.values("id"))
        )
        .filter(output_filter)
        .values(
            "sample_id",
            "sample__sample_unique_id",
            "schema_property__property",
            "value",
        )
        .order_by("sample__sample_unique_id", "sample_id")
    )

    results = {}
    for row in metadata_rows:
        item_property = row["schema_property__property"]
        if item_property is None:
            continue
        sample_id = row["sample_id"]
        entry = results.setdefault(
            sample_id,
            {"sample_unique_id": row["sample__sample_unique_id"], "values": {}},
        )
        values_map = entry["values"]
        value = row["value"]
        if item_property in values_map:
            existing = values_map[item_property]
            if isinstance(existing, list):
                existing.append(value)
            else:
                values_map[item_property] = [existing, value]
        else:
            values_map[item_property] = value

    return list(results.values())


def list_properties_by_classification(classification_name, request_user=None):
    if not classification_name or not isinstance(classification_name, str):
        raise ValueError("classification is required")
    normalized = classification_name.strip()
    if not normalized:
        raise ValueError("classification is required")
    queryset = models.SchemaProperties.objects.all()
    if request_user is not None:
        queryset = queryset.filter(
            schemaID__in=access_control.apply_schema_scope(
                models.Schema.objects.all(), request_user
            )
        )
    properties = (
        queryset.filter(classificationID__classification_name__iexact=normalized)
        .values_list("property", flat=True)
        .distinct()
        .order_by("property")
    )
    return [{"property": name} for name in properties]
