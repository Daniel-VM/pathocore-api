from collections import defaultdict
from datetime import date
import json
import re
import unicodedata

from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, IntegrityError
from django.db.models import Count, Exists, F, OuterRef, Subquery
from django.db.models.functions import TruncDate

import core.config
from core import models
from core.api.utils import access_control

PRIORITY_PROPERTIES = core.config.DATABROWSER_PRIORITY_PROPERTIES
SECTION_META = core.config.DATABROWSER_SECTION_META
SECTION_ORDER = core.config.DATABROWSER_SECTION_ORDER
GLOBAL_CACHE_SCOPE = core.config.DATABROWSER_GLOBAL_CACHE_SCOPE
NO_FILTERS_HASH = core.config.DATABROWSER_NO_FILTERS_HASH
OVERVIEW_SUMMARY = core.config.DATABROWSER_OVERVIEW_SUMMARY
METADATA_SUMMARY = core.config.DATABROWSER_METADATA_SUMMARY
SCHEMA_SUMMARY = core.config.DATABROWSER_SCHEMA_SUMMARY
CACHEABLE_SUMMARIES = core.config.DATABROWSER_CACHEABLE_SUMMARIES
GEOLOCATION_PROPERTIES = set(core.config.DATABROWSER_GEOLOCATION_PROPERTIES)
GEOLOCATION_CENTROIDS = core.config.DATABROWSER_GEOLOCATION_CENTROIDS
PATHOGEN_PROPERTIES = core.config.DATABROWSER_PATHOGEN_PROPERTIES
YEAR_PROPERTIES = core.config.DATABROWSER_YEAR_PROPERTIES


def overview_summary(filters=None, request_user=None):
    return _cached_or_live_global_summary(
        OVERVIEW_SUMMARY, filters, _overview_summary_live
    )


def schema_summary(filters=None, request_user=None):
    return _cached_or_live_global_summary(SCHEMA_SUMMARY, filters, _schema_summary_live)


def metadata_summary(filters=None, request_user=None):
    return _cached_or_live_global_summary(
        METADATA_SUMMARY, filters, _metadata_summary_live
    )


def refresh_databrowser_summary_cache(summary_names=None):
    builders = _summary_builders()
    names = list(summary_names or CACHEABLE_SUMMARIES)
    unknown = sorted(set(names) - set(builders.keys()))
    if unknown:
        raise ValueError("Unknown databrowser summary: %s" % ", ".join(unknown))

    refreshed = {}
    for summary_name in names:
        refreshed[summary_name] = _refresh_global_summary(
            summary_name, builders[summary_name]
        )
    return refreshed


def _overview_summary_live(filters=None, request_user=None):
    filters = filters or {}
    samples = _visible_samples(filters, request_user)
    sample_ids = Subquery(samples.values("id"))
    schemas = _visible_schemas(filters, request_user)
    sample_count = samples.count()
    project_count = _project_count(samples)
    active_schema_count = schemas.filter(schema_in_use=True).count()
    visible_metadata_properties = (
        _metadata_queryset(sample_ids)
        .values("schema_property__property")
        .distinct()
        .count()
    )
    schema_mix = _schema_mix(samples)
    geography = _distribution_for_aliases(
        sample_ids,
        [
            "geo_loc_state",
            "collecting_institution_geo_loc_state",
            "submitting_geo_loc_state",
        ],
        "geography",
    )[:8]
    pathogens = _distribution_for_aliases(sample_ids, ["organism"], "categorical")[:6]
    sample_growth = _distribution_for_aliases(
        sample_ids, ["sample_collection_date"], "date"
    )
    if not sample_growth:
        sample_growth = _sample_created_at_distribution(samples)

    return {
        "kpis": [
            {
                "label": "Samples",
                "note": "Muestras incluidas en el snapshot global",
                "value": _format_integer(sample_count),
            },
            {
                "label": "Projects",
                "note": "Proyectos representados en los schemas activos",
                "value": _format_integer(project_count),
            },
            {
                "label": "Schemas",
                "note": "Schemas activos incluidos en el snapshot global",
                "value": _format_integer(active_schema_count),
            },
            {
                "label": "Metadata properties",
                "note": "Propiedades distintas con valores observados",
                "value": _format_integer(visible_metadata_properties),
            },
        ],
        "sample_growth": sample_growth,
        "pathogens": pathogens,
        "geography": geography,
        "schema_mix": schema_mix,
        "projects": _projects_distribution(samples),
        "notes": [
            "El crecimiento temporal prioriza sample_collection_date y cae a created_at cuando esa metadata no existe.",
            "La distribucion de patogenos depende de la parte de metadata plana expuesta por la API.",
        ],
        "coverage_notes": [
            "Los agregados se calculan en backend para evitar una llamada de metadata por muestra."
        ],
        "metrics": {
            "sample_count": sample_count,
            "project_count": project_count,
            "active_schema_count": active_schema_count,
            "visible_metadata_properties": visible_metadata_properties,
        },
    }


def _schema_summary_live(filters=None, request_user=None):
    filters = filters or {}
    samples = _visible_samples(filters, request_user)
    schemas = _visible_schemas(filters, request_user)
    sample_count_by_schema = _sample_count_by_schema_id(samples)
    property_rows = list(
        models.SchemaProperties.objects.filter(
            schemaID__in=Subquery(schemas.values("id"))
        )
        .select_related("classificationID", "schemaID")
        .values(
            "id",
            "schemaID_id",
            "property",
            "label",
            "description",
            "type",
            "examples",
            "classificationID__classification_name",
        )
        .order_by("schemaID_id", "property")
    )
    options_by_property = _options_by_property([row["id"] for row in property_rows])
    properties_by_schema = defaultdict(list)
    classification_counts = defaultdict(int)
    for row in property_rows:
        classification = row["classificationID__classification_name"] or "Unclassified"
        classification_counts[classification] += 1
        properties_by_schema[row["schemaID_id"]].append(
            {
                "classification": classification,
                "description": row["description"]
                or "No description provided by schema.",
                "enum_values": options_by_property.get(row["id"], []),
                "examples": _split_examples(row["examples"]),
                "label": row["label"] or _humanize(row["property"]),
                "path": row["property"],
                "property_name": row["property"],
                "type": row["type"] or "unknown",
            }
        )

    schema_cards = []
    for schema_obj in schemas.order_by(
        "schema_app_name", "schema_name", "schema_version"
    ):
        schema_properties = properties_by_schema.get(schema_obj.id, [])
        by_classification = defaultdict(list)
        for prop in schema_properties:
            by_classification[prop["classification"]].append(prop)
        classifications = [
            {
                "name": name,
                "property_count": len(props),
                "properties": sorted(props, key=lambda item: item["label"]),
            }
            for name, props in by_classification.items()
        ]
        classifications.sort(key=lambda item: (-item["property_count"], item["name"]))
        schema_cards.append(
            {
                "classification_count": len(classifications),
                "classifications": classifications,
                "generated_at": schema_obj.generated_at,
                "name": schema_obj.schema_name,
                "project_name": schema_obj.schema_app_name or "Unknown project",
                "property_count": len(schema_properties),
                "sample_count": sample_count_by_schema.get(schema_obj.id, 0),
                "version": schema_obj.schema_version,
            }
        )

    classification_distribution = _chart_items(classification_counts)
    schema_distribution = [
        {"label": item["name"], "value": item["sample_count"]} for item in schema_cards
    ]
    project_count = _project_count(samples)
    active_schema_count = schemas.filter(schema_in_use=True).count()
    return {
        "stats": [
            {
                "label": "Active schemas",
                "note": "Schemas marcados en uso en el backend",
                "value": _format_integer(active_schema_count),
            },
            {
                "label": "Projects",
                "note": "Projects incluidos en /schema",
                "value": _format_integer(project_count),
            },
            {
                "label": "Samples",
                "note": "Muestras agregadas para la vista estructural",
                "value": _format_integer(samples.count()),
            },
            {
                "label": "Classification types",
                "note": "Clasificaciones distintas presentes en schemas activos",
                "value": _format_integer(len(classification_counts)),
            },
        ],
        "schema_distribution": schema_distribution,
        "classification_distribution": classification_distribution,
        "schema_cards": schema_cards,
        "schema_options": _schema_options(schemas, sample_count_by_schema),
        "notes": [
            "La distribucion por classification usa las definiciones registradas en core_metadata_schema_properties.",
            "La exploracion de bloques Schema ya no requiere descargar cada JSON schema completo en el navegador.",
        ],
    }


def _metadata_summary_live(filters=None, request_user=None):
    filters = filters or {}
    samples = _visible_samples(filters, request_user)
    schemas = _visible_schemas(filters, request_user)
    sample_ids = Subquery(samples.values("id"))
    definitions = _property_definitions(schemas)
    sections = _metadata_sections(sample_ids, definitions, samples.count())
    populated_priority_properties = sum(
        1
        for section in sections
        for item in section["properties"]
        if item["participant_count"] > 0
    )
    metadata_samples = (
        _metadata_queryset(sample_ids).values("sample_id").distinct().count()
    )
    visible_metadata_properties = (
        _metadata_queryset(sample_ids)
        .values("schema_property__property")
        .distinct()
        .count()
    )
    return {
        "schema_options": [
            {
                "key": "all",
                "label": "All schemas",
                "scope": "global",
            }
        ],
        "schema_scopes": [],
        "sections": sections,
        "notes": [
            "La vista agrega resultados desde endpoints backend agregados; ya no descarga metadata muestra a muestra.",
            "La metadata compleja agrupada dentro de arrays/objetos se resume por propiedad plana registrada.",
        ],
        "stats": [
            {
                "label": "Sections",
                "note": "Bloques principales del entregable",
                "value": "3",
            },
            {
                "label": "Priority properties with data",
                "note": "Propiedades priorizadas con al menos una muestra",
                "value": _format_integer(populated_priority_properties),
            },
            {
                "label": "Samples with metadata",
                "note": "Muestras del snapshot con al menos una entrada",
                "value": _format_integer(metadata_samples),
            },
            {
                "label": "Visible metadata properties",
                "note": "Propiedades distintas pobladas en el dataset actual",
                "value": _format_integer(visible_metadata_properties),
            },
        ],
    }


def property_distribution(filters=None, request_user=None):
    filters = filters or {}
    property_name = filters.get("property")
    if not property_name:
        raise ValueError("property is required")
    property_spec = _priority_spec_for_property(property_name)
    aliases = property_spec["aliases"] if property_spec else [property_name]
    strategy = property_spec["strategy"] if property_spec else "categorical"
    samples = _visible_samples(filters, None)
    sample_ids = Subquery(samples.values("id"))
    total_samples = samples.count()
    property_rows = _metadata_sample_value_rows(sample_ids, aliases)
    matched_samples = len({row["sample_id"] for row in property_rows})
    values = _build_distribution(_value_counts_from_rows(property_rows), strategy)
    breakdowns = _property_distribution_breakdowns(
        sample_ids=sample_ids,
        property_rows=property_rows,
        property_strategy=strategy,
    )
    return {
        "property": property_name,
        "aliases": aliases,
        "strategy": strategy,
        "data_contract_version": "2026-04-flexible-property-distribution",
        "coverage": _coverage_payload(total_samples, matched_samples),
        "metadata": _property_distribution_metadata(
            property_name, aliases, strategy, property_spec
        ),
        "total_samples": total_samples,
        "matched_samples": matched_samples,
        "values": values,
        "breakdowns": breakdowns,
        "cards": _property_distribution_cards(
            property_name=property_name,
            property_spec=property_spec,
            values=values,
            breakdowns=breakdowns,
            strategy=strategy,
        ),
        "ui_hints": _property_distribution_ui_hints(strategy),
    }


def _summary_builders():
    return {
        OVERVIEW_SUMMARY: _overview_summary_live,
        METADATA_SUMMARY: _metadata_summary_live,
        SCHEMA_SUMMARY: _schema_summary_live,
    }


def _cached_or_live_global_summary(summary_name, filters, live_builder):
    normalized_filters = _normalize_filters(filters)
    if normalized_filters:
        # Databrowser is a global database snapshot. Filtered views are still
        # computed globally, without user project scoping.
        return _generic_databrowser_payload(
            summary_name, live_builder(normalized_filters, request_user=None)
        )

    try:
        cached = models.DatabrowserSummaryCache.objects.filter(
            summary_name=summary_name,
            scope_key=GLOBAL_CACHE_SCOPE,
            filters_hash=NO_FILTERS_HASH,
        ).first()
    except DatabaseError:
        cached = None

    if cached is not None:
        return _generic_databrowser_payload(summary_name, cached.payload)

    try:
        return _generic_databrowser_payload(
            summary_name, _refresh_global_summary(summary_name, live_builder)["payload"]
        )
    except DatabaseError:
        return _generic_databrowser_payload(
            summary_name, live_builder({}, request_user=None)
        )


def _refresh_global_summary(summary_name, live_builder):
    filters = {}
    payload = _generic_databrowser_payload(
        summary_name, _json_safe(live_builder(filters, request_user=None))
    )
    try:
        cache_obj, _ = models.DatabrowserSummaryCache.objects.update_or_create(
            summary_name=summary_name,
            scope_key=GLOBAL_CACHE_SCOPE,
            filters_hash=NO_FILTERS_HASH,
            defaults={
                "filters": filters,
                "payload": payload,
            },
        )
    except IntegrityError:
        cache_obj = models.DatabrowserSummaryCache.objects.get(
            summary_name=summary_name,
            scope_key=GLOBAL_CACHE_SCOPE,
            filters_hash=NO_FILTERS_HASH,
        )
        cache_obj.filters = filters
        cache_obj.payload = payload
        cache_obj.save(update_fields=["filters", "payload", "generated_at"])
    return {
        "summary_name": cache_obj.summary_name,
        "scope_key": cache_obj.scope_key,
        "filters_hash": cache_obj.filters_hash,
        "generated_at": cache_obj.generated_at,
        "payload": payload,
    }


def _generic_databrowser_payload(summary_name, payload):
    """Remove project/use-case details from generic databrowser payloads."""

    generic_payload = _json_safe(payload)
    if summary_name == OVERVIEW_SUMMARY:
        generic_payload["geography"] = _enrich_geography_chart_items(
            generic_payload.get("geography", [])
        )
        generic_payload["projects"] = []
        generic_payload["kpis"] = [
            item
            for item in generic_payload.get("kpis", [])
            if item.get("label") != "Projects"
        ]
        generic_payload.get("metrics", {}).pop("project_count", None)
    elif summary_name == SCHEMA_SUMMARY:
        generic_payload["stats"] = [
            item
            for item in generic_payload.get("stats", [])
            if item.get("label") != "Projects"
        ]
        for schema_card in generic_payload.get("schema_cards", []):
            schema_card.pop("project_name", None)
        for schema_option in generic_payload.get("schema_options", []):
            schema_option.pop("project_name", None)
    elif summary_name == METADATA_SUMMARY:
        _enrich_metadata_geography(generic_payload)
        generic_payload["schema_options"] = [
            {
                "key": "all",
                "label": "All schemas",
                "scope": "global",
            }
        ]
        generic_payload["schema_scopes"] = []
    return generic_payload


def _enrich_metadata_geography(payload):
    for section in payload.get("sections", []):
        _enrich_section_geography(section)
    for schema_scope in payload.get("schema_scopes", []):
        for section in schema_scope.get("sections", []):
            _enrich_section_geography(section)


def _enrich_section_geography(section):
    for property_card in section.get("properties", []):
        if _is_geography_property_card(property_card):
            property_card["values"] = _enrich_geography_chart_items(
                property_card.get("values", [])
            )
    for chart in section.get("summary_charts", []):
        if _is_geography_summary_chart(chart):
            chart["values"] = _enrich_geography_chart_items(chart.get("values", []))


def _is_geography_property_card(property_card):
    property_name = str(property_card.get("property_name", "")).lower()
    actual_property_name = str(property_card.get("actual_property_name", "")).lower()
    return property_name in GEOLOCATION_PROPERTIES or any(
        property_name in actual_property_name for property_name in GEOLOCATION_PROPERTIES
    )


def _is_geography_summary_chart(chart):
    title = str(chart.get("title", "")).lower()
    return "geographic" in title or "region" in title


def _enrich_geography_chart_items(items):
    enriched = []
    for item in items or []:
        enriched_item = dict(item)
        geo = _geo_for_label(enriched_item.get("label", ""))
        if geo:
            enriched_item["label"] = geo["label"]
            enriched_item["geo"] = geo
        enriched.append(enriched_item)
    return enriched


def _normalize_filters(filters):
    normalized = {}
    for key, value in sorted((filters or {}).items()):
        if value in (None, ""):
            continue
        if hasattr(value, "isoformat"):
            value = value.isoformat()
        normalized[key] = value
    return normalized


def _json_safe(payload):
    return json.loads(json.dumps(payload, cls=DjangoJSONEncoder))


def _visible_schemas(filters, request_user):
    queryset = models.Schema.objects.all()
    if request_user is not None:
        queryset = access_control.apply_schema_scope(queryset, request_user)
    project_name = filters.get("project_name")
    if project_name:
        queryset = queryset.filter(schema_app_name__iexact=project_name)
    schema_name = filters.get("schema_name")
    if schema_name:
        queryset = queryset.filter(schema_name=schema_name)
    schema_version = filters.get("schema_version")
    if schema_version:
        queryset = queryset.filter(schema_version=schema_version)
    return queryset


def _visible_samples(filters, request_user):
    queryset = models.Sample.objects.select_related("schema_obj").all()
    if request_user is not None:
        queryset = access_control.apply_sample_scope(queryset, request_user)
    project_name = filters.get("project_name")
    if project_name:
        queryset = queryset.filter(schema_obj__schema_app_name__iexact=project_name)
    schema_name = filters.get("schema_name")
    if schema_name:
        queryset = queryset.filter(schema_obj__schema_name=schema_name)
    schema_version = filters.get("schema_version")
    if schema_version:
        queryset = queryset.filter(schema_obj__schema_version=schema_version)
    return _apply_metadata_filters(queryset, filters)


def _apply_metadata_filters(queryset, filters):
    if filters.get("date_from"):
        queryset = _filter_by_metadata(
            queryset,
            "sample_collection_date",
            value_lookup={"value__gte": filters["date_from"].isoformat()},
        )
    if filters.get("date_to"):
        queryset = _filter_by_metadata(
            queryset,
            "sample_collection_date",
            value_lookup={"value__lte": filters["date_to"].isoformat()},
        )
    if filters.get("sequencing_platform"):
        queryset = _filter_by_metadata(
            queryset,
            "sequencing_instrument_platform",
            value_lookup={"value__iexact": filters["sequencing_platform"]},
        )
    return queryset


def _filter_by_metadata(sample_queryset, property_name, value_lookup):
    metadata_queryset = models.MetadataValues.objects.filter(
        sample_id=OuterRef("pk"),
        schema_property__property__iexact=property_name,
        **value_lookup,
    )
    return sample_queryset.filter(Exists(metadata_queryset))


def _metadata_queryset(sample_ids):
    return models.MetadataValues.objects.filter(sample_id__in=sample_ids)


def _distribution_for_aliases(sample_ids, aliases, strategy):
    rows = (
        _metadata_queryset(sample_ids)
        .filter(schema_property__property__in=aliases)
        .exclude(value__isnull=True)
        .exclude(value="")
        .values("value")
        .annotate(count=Count("sample_id", distinct=True))
    )
    return _build_distribution([(row["value"], row["count"]) for row in rows], strategy)


def _metadata_sample_value_rows(sample_ids, aliases):
    return list(
        _metadata_queryset(sample_ids)
        .filter(schema_property__property__in=aliases)
        .exclude(value__isnull=True)
        .exclude(value="")
        .values("sample_id", "value")
        .distinct()
    )


def _value_counts_from_rows(rows):
    sample_ids_by_value = defaultdict(set)
    for row in rows:
        sample_ids_by_value[row["value"]].add(row["sample_id"])
    return [(value, len(sample_ids)) for value, sample_ids in sample_ids_by_value.items()]


def _property_distribution_breakdowns(sample_ids, property_rows, property_strategy):
    if not property_rows:
        return _empty_property_distribution_breakdowns()

    pathogen_index = _sample_context_index(
        sample_ids, PATHOGEN_PROPERTIES, _categorical_label
    )
    year_index = _sample_context_index(sample_ids, YEAR_PROPERTIES, _year_label)
    location_index = _sample_context_index(
        sample_ids, GEOLOCATION_PROPERTIES, _location_label
    )
    return {
        "pathogen": _grouped_property_distribution(
            property_rows=property_rows,
            context_index=pathogen_index,
            unknown_label="Unknown pathogen",
            group_label="pathogen",
            strategy=property_strategy,
            chart_kind="grouped-bar",
            max_groups=12,
        ),
        "year": _grouped_property_distribution(
            property_rows=property_rows,
            context_index=year_index,
            unknown_label="Unknown year",
            group_label="year",
            strategy=property_strategy,
            chart_kind="grouped-bar",
            max_groups=30,
            sort_mode="label",
        ),
        "location": _location_property_distribution(
            property_rows=property_rows,
            location_index=location_index,
            strategy=property_strategy,
        ),
    }


def _empty_property_distribution_breakdowns():
    return {
        "pathogen": {
            "id": "by-pathogen",
            "label": "By pathogen",
            "group_by": "pathogen",
            "source_properties": sorted(PATHOGEN_PROPERTIES),
            "chart_kind": "grouped-bar",
            "metric": "distinct_sample_count",
            "groups_total": 0,
            "groups_returned": 0,
            "truncated": False,
            "series": [],
        },
        "year": {
            "id": "by-year",
            "label": "By year",
            "group_by": "year",
            "source_properties": sorted(YEAR_PROPERTIES),
            "chart_kind": "grouped-bar",
            "metric": "distinct_sample_count",
            "groups_total": 0,
            "groups_returned": 0,
            "truncated": False,
            "series": [],
        },
        "location": {
            "id": "by-location",
            "label": "By location",
            "group_by": "location",
            "source_properties": sorted(GEOLOCATION_PROPERTIES),
            "chart_kind": "choropleth-map",
            "metric": "distinct_sample_count",
            "map_join": {
                "geo_field": "geo",
                "join_key": "code",
                "value_field": "value",
            },
            "matched_samples_with_property": 0,
            "locations_total": 0,
            "values": [],
            "truncated": False,
        },
    }


def _sample_context_index(sample_ids, aliases, normalizer):
    rows = _metadata_sample_value_rows(sample_ids, aliases)
    context = defaultdict(set)
    for row in rows:
        label = normalizer(row["value"])
        if label:
            context[row["sample_id"]].add(label)
    return {sample_id: sorted(labels) for sample_id, labels in context.items()}


def _grouped_property_distribution(
    property_rows,
    context_index,
    unknown_label,
    group_label,
    strategy,
    chart_kind,
    max_groups,
    sort_mode="count",
):
    group_sample_ids = defaultdict(set)
    group_value_sample_ids = defaultdict(lambda: defaultdict(set))
    for row in property_rows:
        sample_id = row["sample_id"]
        context_labels = context_index.get(sample_id) or [unknown_label]
        for context_label in context_labels:
            group_sample_ids[context_label].add(sample_id)
            group_value_sample_ids[context_label][row["value"]].add(sample_id)

    series = []
    for label, sample_ids in group_sample_ids.items():
        value_counts = [
            (value, len(value_sample_ids))
            for value, value_sample_ids in group_value_sample_ids[label].items()
        ]
        series.append(
            {
                "label": label,
                "sample_count": len(sample_ids),
                "values": _build_distribution(value_counts, strategy),
            }
        )

    if sort_mode == "label":
        series.sort(
            key=lambda item: (item["label"].startswith("Unknown"), item["label"])
        )
    else:
        series.sort(key=lambda item: (-item["sample_count"], item["label"]))

    return {
        "id": f"by-{group_label}",
        "label": f"By {group_label}",
        "group_by": group_label,
        "source_properties": (
            sorted(YEAR_PROPERTIES)
            if group_label == "year"
            else sorted(PATHOGEN_PROPERTIES)
        ),
        "chart_kind": chart_kind,
        "metric": "distinct_sample_count",
        "groups_total": len(series),
        "groups_returned": min(len(series), max_groups),
        "truncated": len(series) > max_groups,
        "series": series[:max_groups],
    }


def _location_property_distribution(property_rows, location_index, strategy):
    location_total_sample_ids = defaultdict(set)
    for sample_id, labels in location_index.items():
        for label in labels:
            location_total_sample_ids[label].add(sample_id)

    matched_sample_ids = {row["sample_id"] for row in property_rows}
    location_sample_ids = defaultdict(set)
    location_value_sample_ids = defaultdict(lambda: defaultdict(set))
    for row in property_rows:
        sample_id = row["sample_id"]
        location_labels = location_index.get(sample_id) or ["Unknown location"]
        for location_label in location_labels:
            location_sample_ids[location_label].add(sample_id)
            location_value_sample_ids[location_label][row["value"]].add(sample_id)

    values = []
    for label, sample_ids in location_sample_ids.items():
        total_for_location = len(location_total_sample_ids.get(label, sample_ids))
        matched_count = len(sample_ids)
        geo = _geo_for_label(label)
        value_counts = [
            (raw_value, len(value_sample_ids))
            for raw_value, value_sample_ids in location_value_sample_ids[label].items()
        ]
        item = {
            "label": geo["label"] if geo else label,
            "value": matched_count,
            "matched_samples": matched_count,
            "total_samples": total_for_location,
            "matched_share": (
                matched_count / total_for_location if total_for_location else 0
            ),
            "top_values": _build_distribution(value_counts, strategy)[:8],
            "tooltip": {
                "title": geo["label"] if geo else label,
                "matched_samples": matched_count,
                "total_samples": total_for_location,
                "matched_share": (
                    matched_count / total_for_location if total_for_location else 0
                ),
            },
        }
        if geo:
            item["geo"] = geo
        values.append(item)

    values.sort(
        key=lambda item: (
            item["label"] == "Unknown location",
            -item["matched_samples"],
            item["label"],
        )
    )
    return {
        "id": "by-location",
        "label": "By location",
        "group_by": "location",
        "source_properties": sorted(GEOLOCATION_PROPERTIES),
        "chart_kind": "choropleth-map",
        "metric": "distinct_sample_count",
        "map_join": {
            "geo_field": "geo",
            "join_key": "code",
            "value_field": "value",
        },
        "matched_samples_with_property": len(matched_sample_ids),
        "locations_total": len(values),
        "values": values[:50],
        "truncated": len(values) > 50,
    }


def _property_distribution_cards(property_name, property_spec, values, breakdowns, strategy):
    display_name = (
        property_spec.get("display_name", _humanize(property_name))
        if property_spec
        else _humanize(property_name)
    )
    chart_title = (
        property_spec.get("chart_title", f"Samples by {display_name}")
        if property_spec
        else f"Samples by {display_name}"
    )
    cards = [
        {
            "id": "overall-distribution",
            "title": chart_title,
            "description": "Distribution of distinct samples by selected metadata value.",
            "default_renderer": _chart_kind_for_strategy(strategy),
            "supported_renderers": _supported_renderers_for_strategy(strategy),
            "metric": "distinct_sample_count",
            "data_path": "values",
            "has_data": bool(values),
        }
    ]
    if breakdowns["pathogen"]["series"]:
        cards.append(
            {
                "id": "by-pathogen",
                "title": f"{display_name} by pathogen",
                "description": (
                    "Same property distribution grouped by pathogen or organism "
                    "metadata."
                ),
                "default_renderer": "grouped-bar",
                "supported_renderers": ["grouped-bar", "stacked-bar", "cards"],
                "metric": "distinct_sample_count",
                "data_path": "breakdowns.pathogen.series",
                "has_data": True,
            }
        )
    if breakdowns["year"]["series"]:
        cards.append(
            {
                "id": "by-year",
                "title": f"{display_name} by year",
                "description": "Same property distribution grouped by sample collection year.",
                "default_renderer": "grouped-bar",
                "supported_renderers": ["grouped-bar", "stacked-bar", "timeline"],
                "metric": "distinct_sample_count",
                "data_path": "breakdowns.year.series",
                "has_data": True,
            }
        )
    if breakdowns["location"]["values"]:
        cards.append(
            {
                "id": "by-location",
                "title": f"{display_name} by location",
                "description": (
                    "Samples with the selected property grouped by autonomous "
                    "community."
                ),
                "default_renderer": "choropleth-map",
                "supported_renderers": ["choropleth-map", "bar", "cards"],
                "metric": "distinct_sample_count",
                "data_path": "breakdowns.location.values",
                "has_data": True,
            }
        )
    return cards


def _property_distribution_metadata(property_name, aliases, strategy, property_spec):
    display_name = (
        property_spec.get("display_name", _humanize(property_name))
        if property_spec
        else _humanize(property_name)
    )
    return {
        "property": property_name,
        "display_name": display_name,
        "aliases": aliases,
        "strategy": strategy,
        "group": property_spec.get("group") if property_spec else None,
        "chart_title": (
            property_spec.get("chart_title", f"Samples by {display_name}")
            if property_spec
            else f"Samples by {display_name}"
        ),
    }


def _coverage_payload(total_samples, matched_samples):
    return {
        "matched_samples": matched_samples,
        "total_samples": total_samples,
        "matched_share": matched_samples / total_samples if total_samples else 0,
    }


def _property_distribution_ui_hints(strategy):
    return {
        "metric": "distinct_sample_count",
        "label_field": "label",
        "value_field": "value",
        "default_card": "overall-distribution",
        "card_order": [
            "overall-distribution",
            "by-pathogen",
            "by-year",
            "by-location",
        ],
        "overall_default_renderer": _chart_kind_for_strategy(strategy),
        "location_map": {
            "renderer": "choropleth-map",
            "geo_path": "breakdowns.location.values[].geo",
            "join_key": "geo.code",
            "tooltip_path": "breakdowns.location.values[].tooltip",
        },
    }


def _chart_kind_for_strategy(strategy):
    if strategy == "date":
        return "line"
    if strategy == "geography":
        return "choropleth-map"
    return "bar"


def _supported_renderers_for_strategy(strategy):
    if strategy == "date":
        return ["line", "bar", "cards"]
    if strategy == "geography":
        return ["choropleth-map", "bar", "cards"]
    return ["bar", "pie", "cards"]


def _categorical_label(value):
    return _truncate(_strip_ontology(str(value)))


def _year_label(value):
    parsed = _parse_date_label(value)
    return parsed[:4] if parsed else None


def _location_label(value):
    raw_label = _strip_ontology(str(value))
    if not raw_label:
        return None
    geo = _geo_for_label(raw_label)
    return geo["label"] if geo else _truncate(raw_label)


def _priority_spec_for_property(property_name):
    normalized_property = str(property_name).lower()
    for spec in PRIORITY_PROPERTIES:
        expected_property = spec["expected_property"].lower()
        aliases = [alias.lower() for alias in spec["aliases"]]
        if normalized_property == expected_property or normalized_property in aliases:
            return spec
    if normalized_property in GEOLOCATION_PROPERTIES:
        return {
            "aliases": list(GEOLOCATION_PROPERTIES),
            "strategy": "geography",
        }
    return None


def _metadata_sections(sample_ids, definitions, total_samples, include_empty=True):
    priority_index = _priority_metadata_index(sample_ids)
    sections = []
    for section_id in SECTION_ORDER:
        properties = []
        empty_properties = []
        for spec in [
            item for item in PRIORITY_PROPERTIES if item["group"] == section_id
        ]:
            card = _property_card(spec, definitions, total_samples, priority_index)
            if card["participant_count"] > 0:
                properties.append(card)
            elif include_empty:
                empty_properties.append(_empty_property_card(card))
        section = {
            "description": SECTION_META[section_id]["description"],
            "empty_properties": empty_properties,
            "empty_properties_count": len(empty_properties),
            "empty_properties_label": "Properties with 0 registered samples",
            "id": section_id,
            "notes": SECTION_META[section_id]["notes"],
            "properties": properties,
            "summary_charts": _summary_charts(section_id, priority_index),
            "title": SECTION_META[section_id]["title"],
        }
        sections.append(section)
    return sections


def _property_card(spec, definitions, total_samples, priority_index):
    aliases = spec["aliases"]
    alias_definitions = [definitions.get(alias.lower()) for alias in aliases]
    definition = next((item for item in alias_definitions if item), None)
    participant_sample_ids = set()
    for alias in aliases:
        participant_sample_ids.update(priority_index["participants"].get(alias, set()))
    participant_count = len(participant_sample_ids)
    raw_counts = []
    for alias in aliases:
        raw_counts.extend(priority_index["values"].get(alias, []))
    values = _build_distribution(raw_counts, spec["strategy"])
    aliases_used = sorted(
        alias for alias in aliases if alias in priority_index["aliases_used"]
    )
    card = {
        "chart_kind": "line" if spec["strategy"] == "date" else "bar",
        "chart_title": spec["chart_title"],
        "description": (
            definition["description"]
            if definition
            else "La API no expone todavía una descripción formal para esta propiedad."
        ),
        "display_name": spec["display_name"],
        "is_fallback": (
            bool(aliases_used)
            and (len(aliases_used) > 1 or aliases_used[0] != spec["expected_property"])
        ),
        "participant_count": participant_count,
        "participant_share": (
            participant_count / total_samples if total_samples > 0 else 0
        ),
        "has_data": participant_count > 0,
        "has_chart": bool(values),
        "property_name": spec["expected_property"],
        "values": values,
    }
    if aliases_used:
        card["actual_property_name"] = (
            aliases_used[0]
            if len(aliases_used) == 1
            else f"{aliases_used[0]} (+{len(aliases_used) - 1})"
        )
    return card


def _empty_property_card(card):
    return {
        "chart_title": card["chart_title"],
        "description": card["description"],
        "display_name": card["display_name"],
        "has_chart": False,
        "has_data": False,
        "participant_count": 0,
        "participant_share": 0,
        "property_name": card["property_name"],
    }


def _summary_charts(section_id, priority_index):
    if section_id == "sample-metadata":
        return [
            {
                "title": "Geographic coverage",
                "description": "Muestras por region visible",
                "kind": "bar",
                "values": _distribution_from_index(
                    priority_index,
                    [
                        "geo_loc_state",
                        "collecting_institution_geo_loc_state",
                        "submitting_geo_loc_state",
                    ],
                    "geography",
                )[:8],
            },
            {
                "title": "Collection timeline",
                "description": "Muestras por periodo de recogida",
                "kind": "line",
                "values": _distribution_from_index(
                    priority_index, ["sample_collection_date"], "date"
                ),
            },
        ]
    if section_id == "sample-bioinfo":
        return [
            {
                "title": "Sequencing technology",
                "description": "Muestras por plataforma de secuenciacion",
                "kind": "pie",
                "values": _distribution_from_index(
                    priority_index, ["sequencing_instrument_platform"], "categorical"
                ),
            },
            {
                "title": "Analysis software",
                "description": "Muestras por software principal de analisis",
                "kind": "bar",
                "values": _distribution_from_index(
                    priority_index,
                    ["bioinformatics_protocol_software_name"],
                    "categorical",
                ),
            },
        ]
    return [
        {
            "title": "Host distribution",
            "description": "Muestras por host common name",
            "kind": "pie",
            "values": _distribution_from_index(
                priority_index, ["host_common_name"], "categorical"
            ),
        },
        {
            "title": "Infection profile",
            "description": "Muestras por tipo de infeccion",
            "kind": "bar",
            "values": _distribution_from_index(
                priority_index, ["infection_type"], "categorical"
            ),
        },
    ]


def _priority_metadata_index(sample_ids):
    aliases = sorted(
        {alias for spec in PRIORITY_PROPERTIES for alias in spec["aliases"]}
        | {"sequencing_instrument_platform"}
    )
    value_rows = (
        _metadata_queryset(sample_ids)
        .filter(schema_property__property__in=aliases)
        .exclude(value__isnull=True)
        .exclude(value="")
        .values("schema_property__property", "value")
        .annotate(count=Count("sample_id", distinct=True))
    )
    participant_rows = (
        _metadata_queryset(sample_ids)
        .filter(schema_property__property__in=aliases)
        .values("schema_property__property", "sample_id")
        .distinct()
    )
    values = defaultdict(list)
    aliases_used = set()
    for row in value_rows:
        property_name = row["schema_property__property"]
        aliases_used.add(property_name)
        values[property_name].append((row["value"], row["count"]))
    participants = defaultdict(set)
    for row in participant_rows:
        participants[row["schema_property__property"]].add(row["sample_id"])
    return {
        "aliases_used": aliases_used,
        "participants": participants,
        "values": values,
    }


def _distribution_from_index(priority_index, aliases, strategy):
    raw_counts = []
    for alias in aliases:
        raw_counts.extend(priority_index["values"].get(alias, []))
    return _build_distribution(raw_counts, strategy)


def _property_definitions(schemas):
    rows = (
        models.SchemaProperties.objects.filter(
            schemaID__in=Subquery(schemas.values("id"))
        )
        .select_related("classificationID")
        .values(
            "property",
            "description",
            "label",
            "classificationID__classification_name",
        )
    )
    definitions = {}
    for row in rows:
        key = row["property"].lower()
        if key not in definitions:
            definitions[key] = {
                "classification": row["classificationID__classification_name"]
                or "Unclassified",
                "description": row["description"]
                or "La API no expone todavía una descripción formal para esta propiedad.",
                "label": row["label"] or _humanize(row["property"]),
            }
    return definitions


def _schema_options(schemas, sample_count_by_schema):
    options = []
    for schema_obj in schemas.order_by(
        "schema_app_name", "schema_name", "schema_version"
    ):
        options.append(
            {
                "key": _schema_key(schema_obj.schema_name, schema_obj.schema_version),
                "label": f"{schema_obj.schema_name} v{schema_obj.schema_version}",
                "project_name": schema_obj.schema_app_name or "Unknown project",
                "sample_count": sample_count_by_schema.get(schema_obj.id, 0),
                "schema_id": schema_obj.id,
                "schema_name": schema_obj.schema_name,
                "schema_version": schema_obj.schema_version,
            }
        )
    return options


def _sample_count_by_schema_id(samples):
    return {
        row["schema_obj_id"]: row["count"]
        for row in samples.values("schema_obj_id").annotate(count=Count("id"))
    }


def _schema_mix(samples):
    rows = (
        samples.values(label=F("schema_obj__schema_name"))
        .annotate(value=Count("id"))
        .order_by("-value", "label")
    )
    return _label_value_list(rows)


def _projects_distribution(samples):
    rows = (
        samples.values(label=F("schema_obj__schema_app_name"))
        .annotate(value=Count("id"))
        .order_by("-value", "label")
    )
    return _label_value_list(rows)


def _project_count(samples):
    return (
        samples.exclude(schema_obj__schema_app_name__isnull=True)
        .exclude(schema_obj__schema_app_name="")
        .values("schema_obj__schema_app_name")
        .distinct()
        .count()
    )


def _options_by_property(property_ids):
    options = defaultdict(list)
    if not property_ids:
        return options
    rows = (
        models.PropertyOptions.objects.filter(propertyID_id__in=property_ids)
        .exclude(enum__isnull=True)
        .exclude(enum="")
        .values("propertyID_id", "enum")
        .order_by("propertyID_id", "enum")
    )
    for row in rows:
        options[row["propertyID_id"]].append(row["enum"])
    return options


def _sample_created_at_distribution(samples):
    rows = (
        samples.annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )
    return [
        {"label": row["day"].isoformat(), "value": row["count"]}
        for row in rows
        if row["day"] is not None
    ]


def _build_distribution(value_counts, strategy):
    if strategy in {"age", "coverage", "read-count", "read-length"}:
        return _bucket_distribution(value_counts, strategy)
    if strategy == "date":
        return _date_distribution(value_counts)
    if strategy == "geography":
        return _geography_distribution(value_counts)
    counts = defaultdict(int)
    for value, count in value_counts:
        label = _truncate(_strip_ontology(str(value)))
        if label:
            counts[label] += count
    return _chart_items(counts)[:50]


def _geography_distribution(value_counts):
    counts = defaultdict(int)
    labels = {}
    geos = {}
    for raw_value, count in value_counts:
        raw_label = _strip_ontology(str(raw_value))
        if not raw_label:
            continue
        geo = _geo_for_label(raw_label)
        label = geo["label"] if geo else _truncate(raw_label)
        key = _normalize_geo_key(label if geo else raw_label)
        counts[key] += count
        labels[key] = label
        if geo:
            geos[key] = geo

    items = []
    for key, value in sorted(counts.items(), key=lambda item: (-item[1], labels[item[0]])):
        item = {"label": labels[key], "value": value}
        if key in geos:
            item["geo"] = geos[key]
        items.append(item)
    return items[:50]


def _bucket_distribution(value_counts, strategy):
    bucket_specs = {
        "age": [
            ("0-17", lambda value: value < 18),
            ("18-39", lambda value: 18 <= value < 40),
            ("40-64", lambda value: 40 <= value < 65),
            ("65-79", lambda value: 65 <= value < 80),
            ("80+", lambda value: value >= 80),
        ],
        "coverage": [
            ("<30x", lambda value: value < 30),
            ("30-60x", lambda value: 30 <= value < 60),
            ("60-100x", lambda value: 60 <= value < 100),
            (">100x", lambda value: value >= 100),
        ],
        "read-count": [
            ("<1M", lambda value: value < 1_000_000),
            ("1M-3M", lambda value: 1_000_000 <= value < 3_000_000),
            ("3M-5M", lambda value: 3_000_000 <= value < 5_000_000),
            (">5M", lambda value: value >= 5_000_000),
        ],
        "read-length": [
            ("<=150", lambda value: value <= 150),
            ("151-300", lambda value: 150 < value <= 300),
            ("301-1000", lambda value: 300 < value <= 1000),
            (">1000", lambda value: value > 1000),
        ],
    }[strategy]
    counts = defaultdict(int)
    for raw_value, count in value_counts:
        numeric = _numeric_value(raw_value)
        if numeric is None:
            continue
        for label, predicate in bucket_specs:
            if predicate(numeric):
                counts[label] += count
                break
    return [
        {"label": label, "value": counts[label]}
        for label, _ in bucket_specs
        if counts[label]
    ]


def _date_distribution(value_counts):
    counts = defaultdict(int)
    for raw_value, count in value_counts:
        parsed = _parse_date_label(raw_value)
        if parsed:
            counts[parsed] += count
    return [{"label": label, "value": counts[label]} for label in sorted(counts.keys())]


def _parse_date_label(value):
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if len(text) >= 10 and text[4:5] == "-" and text[7:8] == "-":
        return text[:10]
    return None


def _chart_items(counts):
    return [
        {"label": label, "value": value}
        for label, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _label_value_list(rows):
    return [{"label": row["label"] or "Unknown", "value": row["value"]} for row in rows]


def _split_examples(raw_examples):
    if not raw_examples:
        return []
    return [item.strip() for item in str(raw_examples).split(",") if item.strip()]


def _numeric_value(raw_value):
    try:
        return float("".join(char for char in str(raw_value) if char in "0123456789.-"))
    except ValueError:
        return None


def _strip_ontology(value):
    while "[" in value and "]" in value:
        start = value.find("[")
        end = value.find("]", start)
        if end == -1:
            break
        value = value[:start] + value[end + 1 :]
    return value.strip()


def _geo_for_label(label):
    geo = GEOLOCATION_CENTROIDS.get(_normalize_geo_key(label))
    return dict(geo) if geo else None


def _normalize_geo_key(value):
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", normalized)
    return " ".join(normalized.lower().split())


def _truncate(value, max_length=28):
    return value if len(value) <= max_length else f"{value[: max_length - 1]}…"


def _format_integer(value):
    return f"{value:,}".replace(",", ".")


def _humanize(value):
    return str(value).replace("_", " ").title()


def _schema_key(schema_name, schema_version):
    return f"{schema_name}::{schema_version}"
