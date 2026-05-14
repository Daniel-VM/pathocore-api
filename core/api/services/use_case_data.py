from collections import defaultdict
from datetime import date, datetime
import json
import re
import unicodedata

from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, IntegrityError
from django.db.models import Count, Q, Subquery
from django.utils import timezone

import core.config
from core import models
from core.api.utils import access_control


USE_CASE_DATA_SUMMARY = "use-case-data-summary"
NO_FILTERS_HASH = core.config.DATABROWSER_NO_FILTERS_HASH

PATHOGEN_ALIASES = (
    "organism",
    "species",
    "pathogen",
    "taxon_name",
)
COLLECTION_DATE_ALIASES = (
    "sample_collection_date",
    "collection_date",
)
CENTER_ALIASES = (
    "submitting_institution",
    "collecting_institution",
)
COLLECTING_REGION_ALIASES = (
    "collecting_institution_geo_loc_state",
    "geo_loc_state",
)
SUBMITTING_REGION_ALIASES = (
    "submitting_geo_loc_state",
)
INFECTION_TYPE_ALIASES = (
    "infection_type",
)
SEQUENCING_PLATFORM_ALIASES = (
    "sequencing_instrument_platform",
)
RESISTANCE_PROFILE_ALIASES = (
    "ECDC Resistance profile",
    "IDSA Resistance profile",
    "antimicrobial_resistance_profile",
)
RESISTANCE_SIGNAL_ALIASES = (
    "carbapenemase_genes",
    "carbapenemase_class_a_test",
    "ESBL_test",
    "mbl_test",
)
BIOINFO_ANALYSIS_ALIASES = (
    "bioinformatics_protocol_software_name",
    "preprocessing_software_name",
    "assembly_method",
    "annotation_software_name",
)
SERIES_COLORS = (
    "#0f766e",
    "#2563eb",
    "#7c3aed",
    "#ea580c",
    "#0891b2",
    "#be123c",
    "#4d7c0f",
    "#9333ea",
)


def data_summary(project_name, *, use_cache=True):
    project_name = _normalize_project_name(project_name)
    if not project_name:
        raise ValueError("project_name is required")

    if use_cache:
        cached = _get_cached_project_summary(project_name)
        if cached is not None and cached.payload.get("data_contract_version") == "1.1":
            return cached.payload

    try:
        return refresh_use_case_data_summary_cache([project_name])[project_name][
            "payload"
        ]
    except DatabaseError:
        return _json_safe(_build_project_summary(project_name))


def refresh_use_case_data_summary_cache(project_names=None):
    names = _normalize_project_names(project_names or _known_project_names())
    refreshed = {}
    for project_name in names:
        refreshed[project_name] = _refresh_project_summary(project_name)
    return refreshed


def _known_project_names():
    return (
        models.Schema.objects.exclude(schema_app_name__isnull=True)
        .exclude(schema_app_name="")
        .values_list("schema_app_name", flat=True)
        .distinct()
        .order_by("schema_app_name")
    )


def _refresh_project_summary(project_name):
    payload = _json_safe(_build_project_summary(project_name))
    filters = {"project_name": project_name}
    scope_key = _project_scope_key(project_name)
    try:
        cache_obj, _ = models.DatabrowserSummaryCache.objects.update_or_create(
            summary_name=USE_CASE_DATA_SUMMARY,
            scope_key=scope_key,
            filters_hash=NO_FILTERS_HASH,
            defaults={
                "filters": filters,
                "payload": payload,
            },
        )
    except IntegrityError:
        cache_obj = models.DatabrowserSummaryCache.objects.get(
            summary_name=USE_CASE_DATA_SUMMARY,
            scope_key=scope_key,
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


def _get_cached_project_summary(project_name):
    try:
        return models.DatabrowserSummaryCache.objects.filter(
            summary_name=USE_CASE_DATA_SUMMARY,
            scope_key=_project_scope_key(project_name),
            filters_hash=NO_FILTERS_HASH,
        ).first()
    except DatabaseError:
        return None


def _build_project_summary(project_name):
    samples = models.Sample.objects.select_related("schema_obj").filter(
        schema_obj__schema_app_name__iexact=project_name
    )
    schemas = models.Schema.objects.filter(schema_app_name__iexact=project_name)
    sample_rows = list(
        samples.values("id", "created_at", "sequencing_date", "collecting_institution")
    )
    sample_ids = Subquery(samples.values("id"))
    sample_count = len(sample_rows)

    collection_dates = _sample_date_index(sample_ids, COLLECTION_DATE_ALIASES)
    pathogen_by_sample = _sample_first_value_index(sample_ids, PATHOGEN_ALIASES)
    center_by_sample = _center_index(sample_ids, sample_rows)
    collecting_region_by_sample = _sample_first_value_index(
        sample_ids, COLLECTING_REGION_ALIASES, normalizer=_location_label
    )
    submitting_region_by_sample = _sample_first_value_index(
        sample_ids, SUBMITTING_REGION_ALIASES, normalizer=_location_label
    )
    resistance_signals_by_sample = _sample_values_index(
        sample_ids, RESISTANCE_SIGNAL_ALIASES
    )
    sample_years = _sample_period_index(
        sample_rows, collection_dates, period="year"
    )
    sample_months = _sample_period_index(
        sample_rows, collection_dates, period="month"
    )

    analyzed_sample_count = _analyzed_sample_count(sample_ids)
    collecting_regions = _distribution_from_index(collecting_region_by_sample)
    submitting_regions = _distribution_from_index(submitting_region_by_sample)
    region_by_sample = _preferred_region_index(
        collecting_region_by_sample, submitting_region_by_sample
    )
    region_count = len(set(region_by_sample.values()))
    center_count = len(set(center_by_sample.values()))
    active_schema_count = schemas.filter(schema_in_use=True).count()
    schema_count = schemas.count()

    pathogen_distribution = _distribution_from_index(pathogen_by_sample)
    center_distribution = _distribution_from_index(center_by_sample)
    region_distribution = _distribution_from_index(region_by_sample)
    infection_type_distribution = _distribution_for_aliases(
        sample_ids, INFECTION_TYPE_ALIASES
    )
    sequencing_platform_distribution = _distribution_for_aliases(
        sample_ids, SEQUENCING_PLATFORM_ALIASES
    )
    resistance_profile_distribution = _distribution_for_aliases(
        sample_ids, RESISTANCE_PROFILE_ALIASES, split_values=True
    )
    resistance_signal_distribution = _distribution_from_index(
        resistance_signals_by_sample
    )
    annual_pathogen_series = _multi_series_chart(
        sample_years,
        pathogen_by_sample,
        simulated=False,
    )
    resistance_signals_series = _multi_series_chart(
        sample_years,
        resistance_signals_by_sample,
        simulated=False,
    )
    collection_timeline = _timeline_from_period_index(sample_months)
    territorial_coverage = _territorial_coverage(
        region_by_sample=region_by_sample,
        center_by_sample=center_by_sample,
        pathogen_by_sample=pathogen_by_sample,
        resistance_signals_by_sample=resistance_signals_by_sample,
    )

    metrics = {
        "total_samples": sample_count,
        "analyzed_samples": analyzed_sample_count,
        "participating_regions": region_count,
        "participating_centers": center_count,
        "active_schema_count": active_schema_count,
        "schema_count": schema_count,
        "samples_with_collection_date": len(collection_dates),
        "samples_with_pathogen": len(pathogen_by_sample),
        "samples_with_region": len(region_by_sample),
        "samples_with_resistance_signals": len(resistance_signals_by_sample),
    }

    dimensions = {
        "pathogen": _dimension(
            key="pathogen",
            label="Pathogen",
            kind="categorical",
            source_properties=PATHOGEN_ALIASES,
            values=pathogen_distribution,
            total_samples=sample_count,
            matched_samples=len(pathogen_by_sample),
        ),
        "center": _dimension(
            key="center",
            label="Center",
            kind="categorical",
            source_properties=CENTER_ALIASES,
            values=center_distribution,
            total_samples=sample_count,
            matched_samples=len(center_by_sample),
        ),
        "region": _dimension(
            key="region",
            label="Preferred region",
            kind="geography",
            source_properties=COLLECTING_REGION_ALIASES + SUBMITTING_REGION_ALIASES,
            values=region_distribution,
            total_samples=sample_count,
            matched_samples=len(region_by_sample),
        ),
        "collecting_region": _dimension(
            key="collecting_region",
            label="Collecting region",
            kind="geography",
            source_properties=COLLECTING_REGION_ALIASES,
            values=collecting_regions,
            total_samples=sample_count,
            matched_samples=len(collecting_region_by_sample),
        ),
        "submitting_region": _dimension(
            key="submitting_region",
            label="Submitting region",
            kind="geography",
            source_properties=SUBMITTING_REGION_ALIASES,
            values=submitting_regions,
            total_samples=sample_count,
            matched_samples=len(submitting_region_by_sample),
        ),
        "infection_type": _dimension(
            key="infection_type",
            label="Infection type",
            kind="categorical",
            source_properties=INFECTION_TYPE_ALIASES,
            values=infection_type_distribution,
            total_samples=sample_count,
            matched_samples=_matched_sample_count_for_aliases(
                sample_ids, INFECTION_TYPE_ALIASES
            ),
        ),
        "sequencing_platform": _dimension(
            key="sequencing_platform",
            label="Sequencing platform",
            kind="categorical",
            source_properties=SEQUENCING_PLATFORM_ALIASES,
            values=sequencing_platform_distribution,
            total_samples=sample_count,
            matched_samples=_matched_sample_count_for_aliases(
                sample_ids, SEQUENCING_PLATFORM_ALIASES
            ),
        ),
        "resistance_profile": _dimension(
            key="resistance_profile",
            label="Resistance profile",
            kind="categorical",
            source_properties=RESISTANCE_PROFILE_ALIASES,
            values=resistance_profile_distribution,
            total_samples=sample_count,
            matched_samples=_matched_sample_count_for_aliases(
                sample_ids, RESISTANCE_PROFILE_ALIASES
            ),
        ),
        "resistance_signal": _dimension(
            key="resistance_signal",
            label="Resistance signal",
            kind="categorical",
            source_properties=RESISTANCE_SIGNAL_ALIASES,
            values=resistance_signal_distribution,
            total_samples=sample_count,
            matched_samples=len(resistance_signals_by_sample),
        ),
    }

    time_series = {
        "samples_by_month": _single_time_series(
            key="samples_by_month",
            label="Samples by month",
            x_axis="month",
            source_properties=COLLECTION_DATE_ALIASES,
            values=collection_timeline,
        ),
        "pathogens_by_year": _grouped_time_series(
            key="pathogens_by_year",
            label="Pathogens by year",
            x_axis="year",
            group_by="pathogen",
            source_properties=PATHOGEN_ALIASES,
            chart=annual_pathogen_series,
        ),
        "resistance_signals_by_year": _grouped_time_series(
            key="resistance_signals_by_year",
            label="Resistance signals by year",
            x_axis="year",
            group_by="resistance_signal",
            source_properties=RESISTANCE_SIGNAL_ALIASES,
            chart=resistance_signals_series,
        ),
    }

    overview = {
        "total_samples": sample_count,
        "analyzed_samples": analyzed_sample_count,
        "participating_regions": region_count,
        "participating_centers": center_count,
        "kpis": _kpis(
            total_samples=sample_count,
            analyzed_samples=analyzed_sample_count,
            region_count=region_count,
            center_count=center_count,
        ),
        "project_pathogen_distribution": pathogen_distribution,
        "pathogen_distribution_simulated": False,
        "annual_pathogen_series": annual_pathogen_series,
        "resistance_signals_series": resistance_signals_series,
        "collection_timeline": collection_timeline,
        "territorial_coverage": territorial_coverage,
        "territorial_coverage_simulated": False,
        "centers": center_distribution,
        "collecting_regions": collecting_regions,
        "submitting_regions": submitting_regions,
        "infection_types": infection_type_distribution,
        "sequencing_platforms": sequencing_platform_distribution,
        "resistance_profiles": resistance_profile_distribution,
        "resistance_profiles_simulated": False,
        "notes": _summary_notes(sample_count),
    }
    generated_at = timezone.now()

    return {
        "data_contract_version": "1.1",
        "project_name": project_name,
        "project_label": _project_label(project_name),
        "generated_at": generated_at,
        "project": {
            "id": project_name,
            "label": _project_label(project_name),
        },
        "cache": {
            "generated_at": generated_at,
            "scope_key": _project_scope_key(project_name),
            "summary_name": USE_CASE_DATA_SUMMARY,
        },
        "metrics": metrics,
        "dimensions": dimensions,
        "time_series": time_series,
        "geography": {
            "regions": territorial_coverage,
            "map_join": {
                "geo_field": "geo",
                "join_key": "code",
                "value_field": "samples",
            },
        },
        "visualization_hints": _visualization_hints(),
        "overview": overview,
        "data_quality": {
            "simulated": False,
            "active_schema_count": active_schema_count,
            "schema_count": schema_count,
            "source_properties": {
                "pathogen": list(PATHOGEN_ALIASES),
                "collection_date": list(COLLECTION_DATE_ALIASES),
                "centers": list(CENTER_ALIASES),
                "collecting_regions": list(COLLECTING_REGION_ALIASES),
                "submitting_regions": list(SUBMITTING_REGION_ALIASES),
                "infection_types": list(INFECTION_TYPE_ALIASES),
                "sequencing_platforms": list(SEQUENCING_PLATFORM_ALIASES),
                "resistance_profiles": list(RESISTANCE_PROFILE_ALIASES),
                "resistance_signals": list(RESISTANCE_SIGNAL_ALIASES),
                "bioinformatics_analysis": list(BIOINFO_ANALYSIS_ALIASES),
            },
            "dimension_coverage": {
                key: value["coverage"] for key, value in dimensions.items()
            },
            "missing_operational_fields": _missing_operational_fields(overview),
        },
    }


def _sample_date_index(sample_ids, aliases):
    rows = _metadata_rows(sample_ids, aliases)
    dates = {}
    for row in rows:
        parsed = _parse_date(row["value"])
        if parsed and row["sample_id"] not in dates:
            dates[row["sample_id"]] = parsed
    return dates


def _sample_first_value_index(sample_ids, aliases, *, normalizer=None):
    values = {}
    normalize = normalizer or _display_label
    for row in _metadata_rows(sample_ids, aliases):
        label = normalize(row["value"])
        if label and row["sample_id"] not in values:
            values[row["sample_id"]] = label
    return values


def _sample_values_index(sample_ids, aliases):
    values = defaultdict(set)
    for row in _metadata_rows(sample_ids, aliases):
        for label in _split_labels(row["value"]):
            values[row["sample_id"]].add(label)
    return {sample_id: sorted(labels) for sample_id, labels in values.items()}


def _center_index(sample_ids, sample_rows):
    centers = _sample_first_value_index(sample_ids, CENTER_ALIASES)
    for sample_row in sample_rows:
        center = _display_label(sample_row.get("collecting_institution"))
        if center and sample_row["id"] not in centers:
            centers[sample_row["id"]] = center
    return centers


def _metadata_rows(sample_ids, aliases):
    if not aliases:
        return []
    return list(
        models.MetadataValues.objects.filter(sample_id__in=sample_ids)
        .filter(_property_query(aliases))
        .exclude(value__isnull=True)
        .exclude(value="")
        .values("sample_id", "value", "schema_property__property")
        .order_by("sample_id", "schema_property__property", "value")
        .distinct()
    )


def _distribution_for_aliases(sample_ids, aliases, *, split_values=False):
    if split_values:
        sample_ids_by_label = defaultdict(set)
        for row in _metadata_rows(sample_ids, aliases):
            for label in _split_labels(row["value"]):
                sample_ids_by_label[label].add(row["sample_id"])
        return _chart_items(
            {
                label: len(label_sample_ids)
                for label, label_sample_ids in sample_ids_by_label.items()
            }
        )

    rows = (
        models.MetadataValues.objects.filter(sample_id__in=sample_ids)
        .filter(_property_query(aliases))
        .exclude(value__isnull=True)
        .exclude(value="")
        .values("value")
        .annotate(count=Count("sample_id", distinct=True))
    )
    counts = defaultdict(int)
    for row in rows:
        label = _display_label(row["value"])
        if label:
            counts[label] += row["count"]
    return _chart_items(counts)


def _matched_sample_count_for_aliases(sample_ids, aliases):
    return (
        models.MetadataValues.objects.filter(sample_id__in=sample_ids)
        .filter(_property_query(aliases))
        .exclude(value__isnull=True)
        .exclude(value="")
        .values("sample_id")
        .distinct()
        .count()
    )


def _distribution_from_index(values_by_sample):
    counts = defaultdict(int)
    for label in values_by_sample.values():
        if isinstance(label, (list, tuple, set)):
            for item in label:
                counts[item] += 1
        elif label:
            counts[label] += 1
    return _chart_items(counts)


def _dimension(
    *,
    key,
    label,
    kind,
    source_properties,
    values,
    total_samples,
    matched_samples,
):
    matched_share = matched_samples / total_samples if total_samples else 0
    return {
        "id": key,
        "label": label,
        "kind": kind,
        "metric": "distinct_sample_count",
        "source_properties": list(source_properties),
        "coverage": {
            "matched_samples": matched_samples,
            "total_samples": total_samples,
            "matched_share": matched_share,
        },
        "values": values,
        "truncated": len(values) >= 50,
    }


def _single_time_series(*, key, label, x_axis, source_properties, values):
    return {
        "id": key,
        "label": label,
        "kind": "time_series",
        "x_axis": x_axis,
        "metric": "distinct_sample_count",
        "source_properties": list(source_properties),
        "values": values,
        "truncated": False,
    }


def _grouped_time_series(
    *,
    key,
    label,
    x_axis,
    group_by,
    source_properties,
    chart,
):
    return {
        "id": key,
        "label": label,
        "kind": "grouped_time_series",
        "x_axis": x_axis,
        "group_by": group_by,
        "metric": "distinct_sample_count",
        "source_properties": list(source_properties),
        "series": chart["series"],
        "values": chart["data"],
        "simulated": chart["simulated"],
        "truncated": False,
    }


def _preferred_region_index(collecting_region_by_sample, submitting_region_by_sample):
    region_by_sample = {}
    sample_ids = set(collecting_region_by_sample) | set(submitting_region_by_sample)
    for sample_id in sample_ids:
        label = (
            collecting_region_by_sample.get(sample_id)
            or submitting_region_by_sample.get(sample_id)
        )
        if label:
            region_by_sample[sample_id] = label
    return region_by_sample


def _sample_period_index(sample_rows, collection_dates, *, period):
    periods = {}
    for sample_row in sample_rows:
        value = collection_dates.get(sample_row["id"])
        if value is None:
            value = _date_from_datetime(sample_row.get("sequencing_date"))
        if value is None:
            value = _date_from_datetime(sample_row.get("created_at"))
        if value is None:
            continue
        if period == "year":
            periods[sample_row["id"]] = str(value.year)
        else:
            periods[sample_row["id"]] = f"{value.year:04d}-{value.month:02d}"
    return periods


def _timeline_from_period_index(period_by_sample):
    counts = defaultdict(int)
    for label in period_by_sample.values():
        counts[label] += 1
    return [
        {"label": label, "value": counts[label]}
        for label in sorted(counts.keys())
    ]


def _multi_series_chart(period_by_sample, values_by_sample, *, simulated):
    group_sample_ids = defaultdict(lambda: defaultdict(set))
    for sample_id, period in period_by_sample.items():
        values = values_by_sample.get(sample_id)
        if not values:
            continue
        elif isinstance(values, str):
            values = [values]
        for value in values:
            group_sample_ids[value][period].add(sample_id)

    top_labels = sorted(
        group_sample_ids.keys(),
        key=lambda label: (
            -sum(len(samples) for samples in group_sample_ids[label].values()),
            label,
        ),
    )[: len(SERIES_COLORS)]
    series = [
        {
            "key": _series_key(label, index),
            "label": label,
            "color": SERIES_COLORS[index % len(SERIES_COLORS)],
        }
        for index, label in enumerate(top_labels)
    ]
    periods = sorted(set(period_by_sample.values()))
    data = []
    for period in periods:
        item = {"label": period}
        for index, label in enumerate(top_labels):
            key = series[index]["key"]
            item[key] = len(group_sample_ids[label].get(period, set()))
        data.append(item)
    return {
        "data": data,
        "series": series,
        "simulated": simulated,
    }


def _territorial_coverage(
    *,
    region_by_sample,
    center_by_sample,
    pathogen_by_sample,
    resistance_signals_by_sample,
):
    sample_ids_by_region = defaultdict(set)
    for sample_id, label in region_by_sample.items():
        if label:
            sample_ids_by_region[label].add(sample_id)

    regions = []
    for label, region_sample_ids in sample_ids_by_region.items():
        centers = {
            center_by_sample[sample_id]
            for sample_id in region_sample_ids
            if sample_id in center_by_sample
        }
        dominant_pathogen = _top_label_for_samples(region_sample_ids, pathogen_by_sample)
        top_resistance_signal = _top_label_for_samples(
            region_sample_ids, resistance_signals_by_sample
        )
        geo = _geo_for_label(label)
        item = {
            "label": geo["label"] if geo else label,
            "region_code": _normalize_geo_key(label),
            "samples": len(region_sample_ids),
            "centers": len(centers),
            "hospitals": len(centers),
            "dominant_pathogen": dominant_pathogen or "Unknown pathogen",
            "top_resistance_signal": (
                top_resistance_signal or "Unknown resistance signal"
            ),
            "simulated": False,
            "notes": [],
            "x": geo.get("x", 0) if geo else 0,
            "y": geo.get("y", 0) if geo else 0,
        }
        if geo:
            item["geo"] = geo
        regions.append(item)

    return sorted(regions, key=lambda item: (-item["samples"], item["label"]))[:50]


def _top_label_for_samples(sample_ids, values_by_sample):
    counts = defaultdict(int)
    for sample_id in sample_ids:
        values = values_by_sample.get(sample_id)
        if isinstance(values, str):
            values = [values]
        for value in values or []:
            counts[value] += 1
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def _analyzed_sample_count(sample_ids):
    metadata_sample_ids = set(
        models.MetadataValues.objects.filter(sample_id__in=sample_ids)
        .filter(_property_query(BIOINFO_ANALYSIS_ALIASES))
        .exclude(value__isnull=True)
        .exclude(value="")
        .values_list("sample_id", flat=True)
        .distinct()
    )
    variant_sample_ids = set(
        models.SampleVariant.objects.filter(sample_id__in=sample_ids)
        .values_list("sample_id", flat=True)
        .distinct()
    )
    return len(metadata_sample_ids | variant_sample_ids)


def _kpis(*, total_samples, analyzed_samples, region_count, center_count):
    return [
        {
            "label": "Muestras disponibles",
            "note": "Muestras visibles del caso de uso",
            "value": _format_integer(total_samples),
        },
        {
            "label": "Muestras analizadas",
            "note": "Muestras con evidencia de procesamiento bioinformatico",
            "value": _format_integer(analyzed_samples),
        },
        {
            "label": "CCAA participantes",
            "note": "Comunidades autonomas detectadas en la capa visible",
            "value": _format_integer(region_count),
        },
        {
            "label": "Centros implicados",
            "note": "Hospitales o centros con al menos una muestra",
            "value": _format_integer(center_count),
        },
    ]


def _missing_operational_fields(overview):
    missing = []
    if not overview["project_pathogen_distribution"]:
        missing.append("pathogen")
    if not overview["resistance_profiles"]:
        missing.append("resistance_profiles")
    if not overview["resistance_signals_series"]["series"]:
        missing.append("resistance_signals")
    if not overview["territorial_coverage"]:
        missing.append("territorial_coverage")
    return missing


def _summary_notes(sample_count):
    notes = [
        "Los agregados se calculan en backend para evitar una llamada de metadata por muestra.",
        (
            "Las fechas priorizan sample_collection_date y caen a "
            "sequencing_date/created_at si no existe metadata de coleccion."
        ),
    ]
    if sample_count == 0:
        notes.append("No hay muestras registradas para este caso de uso.")
    return notes


def _visualization_hints():
    return {
        "recommended_cards": [
            {
                "id": "total_samples",
                "renderer": "kpi",
                "data_path": "metrics.total_samples",
            },
            {
                "id": "pathogen_distribution",
                "renderer": "donut",
                "data_path": "dimensions.pathogen.values",
            },
            {
                "id": "samples_by_month",
                "renderer": "line",
                "data_path": "time_series.samples_by_month.values",
            },
            {
                "id": "regions",
                "renderer": "map_or_bar",
                "data_path": "geography.regions",
            },
        ],
        "supported_renderers": {
            "categorical_dimension": ["bar", "donut", "table"],
            "geography_dimension": ["map", "bar", "table"],
            "time_series": ["line", "bar", "table"],
            "grouped_time_series": ["stacked_bar", "grouped_bar", "line", "table"],
        },
    }


def _property_query(aliases):
    query = Q()
    for alias in aliases:
        query |= Q(schema_property__property__iexact=alias)
    return query


def _chart_items(counts):
    return [
        {"label": label, "value": value}
        for label, value in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if label
    ][:50]


def _split_labels(value):
    text = _strip_ontology(str(value or ""))
    if not text:
        return []
    labels = []
    for item in re.split(r"[;,|]", text):
        label = _display_label(item)
        if label:
            labels.append(label)
    return labels


def _display_label(value):
    return _truncate(_strip_ontology(str(value or "").strip()))


def _location_label(value):
    label = _display_label(value)
    geo = _geo_for_label(label)
    return geo["label"] if geo else label


def _strip_ontology(value):
    while "[" in value and "]" in value:
        start = value.find("[")
        end = value.find("]", start)
        if end == -1:
            break
        value = value[:start] + value[end + 1 :]
    return value.strip()


def _parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _date_from_datetime(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _project_scope_key(project_name):
    return f"project:{project_name}"


def _normalize_project_names(project_names):
    normalized = []
    for project_name in project_names:
        normalized_name = _normalize_project_name(project_name)
        if normalized_name and normalized_name not in normalized:
            normalized.append(normalized_name)
    return normalized


def _normalize_project_name(project_name):
    return access_control._normalize_project_code(project_name)


def _project_label(project_name):
    return project_name.replace("_", " ").replace("-", " ").title()


def _series_key(label, index):
    normalized = unicodedata.normalize("NFKD", str(label))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", normalized).strip("_").lower()
    return normalized or f"series_{index + 1}"


def _geo_for_label(label):
    geo = core.config.DATABROWSER_GEOLOCATION_CENTROIDS.get(_normalize_geo_key(label))
    return dict(geo) if geo else None


def _normalize_geo_key(value):
    normalized = unicodedata.normalize("NFKD", str(value))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", normalized)
    return " ".join(normalized.lower().split())


def _truncate(value, max_length=40):
    return value if len(value) <= max_length else f"{value[: max_length - 1]}..."


def _format_integer(value):
    return f"{value:,}".replace(",", ".")


def _json_safe(payload):
    return json.loads(json.dumps(payload, cls=DjangoJSONEncoder))
