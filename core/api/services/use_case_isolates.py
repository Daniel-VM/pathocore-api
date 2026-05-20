from collections import defaultdict
from datetime import date, datetime
import re
import unicodedata

from django.db.models import Q
from django.utils import timezone

import core.config
from core import models
from core.api.services import use_case_data
from core.api.utils import access_control


DATA_CONTRACT_VERSION = "1.0"

SEQUENCE_TYPE_ALIASES = (
    "sequence_type.sequence_type_1",
    "sequence_type.sequence_type_2",
    "sequence_type_1",
    "sequence_type_2",
    "sequence_type",
    "mlst_sequence_type",
    "mlst.ST",
    "ST",
)
HOST_ALIASES = (
    "host_common_name",
    "host_scientific_name",
)
ISOLATE_DELIVERY_TYPE_ALIASES = ("isolate_delivery_type",)

FIELD_SPECS = {
    "collection_date": {
        "label": "Collection date",
        "kind": "date",
        "source_properties": use_case_data.COLLECTION_DATE_ALIASES,
    },
    "pathogen": {
        "label": "Pathogen",
        "kind": "categorical",
        "source_properties": use_case_data.PATHOGEN_ALIASES,
    },
    "region": {
        "label": "Preferred region",
        "kind": "geography",
        "source_properties": (
            *use_case_data.COLLECTING_REGION_ALIASES,
            *use_case_data.SUBMITTING_REGION_ALIASES,
        ),
    },
    "collecting_region": {
        "label": "Collecting region",
        "kind": "geography",
        "source_properties": use_case_data.COLLECTING_REGION_ALIASES,
    },
    "submitting_region": {
        "label": "Submitting region",
        "kind": "geography",
        "source_properties": use_case_data.SUBMITTING_REGION_ALIASES,
    },
    "submitting_institution": {
        "label": "Submitting institution",
        "kind": "categorical",
        "source_properties": use_case_data.CENTER_ALIASES,
    },
    "infection_type": {
        "label": "Infection type",
        "kind": "categorical",
        "source_properties": use_case_data.INFECTION_TYPE_ALIASES,
    },
    "sequencing_platform": {
        "label": "Sequencing platform",
        "kind": "categorical",
        "source_properties": use_case_data.SEQUENCING_PLATFORM_ALIASES,
    },
    "resistance_profile": {
        "label": "Resistance profile",
        "kind": "categorical",
        "source_properties": use_case_data.RESISTANCE_PROFILE_ALIASES,
    },
    "carbapenemase": {
        "label": "Carbapenemase",
        "kind": "categorical",
        "source_properties": use_case_data.RESISTANCE_SIGNAL_ALIASES,
    },
    "sequence_type": {
        "label": "Sequence type",
        "kind": "categorical",
        "source_properties": SEQUENCE_TYPE_ALIASES,
    },
    "host": {
        "label": "Host",
        "kind": "categorical",
        "source_properties": HOST_ALIASES,
    },
    "isolate_delivery_type": {
        "label": "Isolate delivery type",
        "kind": "categorical",
        "source_properties": ISOLATE_DELIVERY_TYPE_ALIASES,
    },
}


def isolate_explorer(project_name, *, filters=None, request_user=None):
    project_name = _normalize_project_name(project_name)
    if not project_name:
        raise ValueError("project_name is required")

    filters = filters or {}
    samples = models.Sample.objects.select_related("schema_obj").filter(
        schema_obj__schema_app_name__iexact=project_name
    )
    if request_user is not None:
        samples = access_control.apply_sample_scope(samples, request_user)

    sample_rows = list(
        samples.order_by("sample_unique_id").values(
            "id",
            "sample_unique_id",
            "sequencing_sample_id",
            "submitting_lab_sample_id",
            "collecting_lab_sample_id",
            "collecting_lab_isolate_id",
            "sequencing_isolate_id",
            "submitting_lab_isolate_id",
            "collecting_institution",
            "sequencing_date",
            "created_at",
        )
    )
    total_samples = len(sample_rows)
    sample_ids = [row["id"] for row in sample_rows]
    metadata = _metadata_indexes(sample_ids)
    rows = [_row_payload(row, metadata) for row in sample_rows]
    filter_options = _filter_options(rows)
    filtered_rows = _apply_filters(rows, filters)
    paginated_rows = _paginate(filtered_rows, filters)

    return {
        "data_contract_version": DATA_CONTRACT_VERSION,
        "project_name": project_name,
        "project_label": _project_label(project_name),
        "generated_at": timezone.now(),
        "project": {
            "id": project_name,
            "label": _project_label(project_name),
        },
        "query": _query_payload(filters),
        "columns": _columns(),
        "rows": paginated_rows,
        "filter_options": filter_options,
        "total_samples": total_samples,
        "matched_samples": len(filtered_rows),
        "total_loaded": len(paginated_rows),
        "data_quality": _data_quality(rows, total_samples),
        "notes": [
            "Rows are generated from project-scoped samples and metadata values in bulk.",
            "Complex metadata is resolved through grouped dotted properties where available.",
        ],
    }


def _metadata_indexes(sample_ids):
    aliases_by_field = {
        field: tuple(spec["source_properties"])
        for field, spec in FIELD_SPECS.items()
    }
    all_aliases = []
    for aliases in aliases_by_field.values():
        all_aliases.extend(aliases)

    values = {field: defaultdict(list) for field in aliases_by_field}
    alias_to_fields = defaultdict(list)
    for field, aliases in aliases_by_field.items():
        for index, alias in enumerate(aliases):
            alias_to_fields[alias.lower()].append((field, index))

    if not sample_ids or not all_aliases:
        return values

    rows = (
        models.MetadataValues.objects.filter(sample_id__in=sample_ids)
        .filter(_property_query(all_aliases))
        .exclude(value__isnull=True)
        .exclude(value="")
        .values(
            "sample_id",
            "schema_property__property",
            "value",
            "group__group_index",
        )
        .order_by(
            "sample_id",
            "schema_property__property",
            "group__group_index",
            "value",
        )
        .distinct()
    )

    weighted_values = {field: defaultdict(list) for field in aliases_by_field}
    seen = {field: defaultdict(set) for field in aliases_by_field}
    for row in rows:
        row_property = row["schema_property__property"]
        row_value = _display_value(row["value"])
        if not row_property or not row_value:
            continue
        for field, alias_index in alias_to_fields.get(row_property.lower(), []):
            if field in _multi_value_fields():
                split_values = _split_values(row_value)
            else:
                split_values = [row_value]
            for value in split_values:
                key = value.lower()
                if key in seen[field][row["sample_id"]]:
                    continue
                seen[field][row["sample_id"]].add(key)
                weighted_values[field][row["sample_id"]].append((alias_index, value))

    for field, by_sample in weighted_values.items():
        for sample_id, field_values in by_sample.items():
            values[field][sample_id] = [
                value
                for _, value in sorted(
                    field_values, key=lambda item: (item[0], item[1])
                )
            ]
    return values


def _row_payload(sample_row, metadata):
    sample_id = sample_row["id"]
    collection_date = _first_date(metadata["collection_date"].get(sample_id))
    if collection_date is None:
        collection_date = _date_from_datetime(sample_row.get("sequencing_date"))
    if collection_date is None:
        collection_date = _date_from_datetime(sample_row.get("created_at"))

    collecting_region = _first_location(metadata["collecting_region"].get(sample_id))
    submitting_region = _first_location(metadata["submitting_region"].get(sample_id))
    submitting_institution = _first_value(
        metadata["submitting_institution"].get(sample_id)
    )
    if submitting_institution is None:
        submitting_institution = _display_value(sample_row.get("collecting_institution"))

    return {
        "sample_unique_id": sample_row["sample_unique_id"],
        "sequencing_sample_id": sample_row.get("sequencing_sample_id"),
        "submitting_lab_sample_id": sample_row.get("submitting_lab_sample_id"),
        "collecting_lab_sample_id": sample_row.get("collecting_lab_sample_id"),
        "collecting_lab_isolate_id": sample_row.get("collecting_lab_isolate_id"),
        "sequencing_isolate_id": sample_row.get("sequencing_isolate_id"),
        "submitting_lab_isolate_id": sample_row.get("submitting_lab_isolate_id"),
        "collection_date": collection_date.isoformat() if collection_date else None,
        "collecting_region": collecting_region,
        "submitting_region": submitting_region,
        "region": collecting_region or submitting_region,
        "pathogen": _first_value(metadata["pathogen"].get(sample_id)),
        "sequence_type": _first_sequence_type(metadata["sequence_type"].get(sample_id)),
        "carbapenemase": _joined_values(metadata["carbapenemase"].get(sample_id)),
        "resistance_profile": _joined_values(
            metadata["resistance_profile"].get(sample_id)
        ),
        "sequencing_platform": _first_value(
            metadata["sequencing_platform"].get(sample_id)
        ),
        "submitting_institution": submitting_institution,
        "infection_type": _first_value(metadata["infection_type"].get(sample_id)),
        "isolate_delivery_type": _first_value(
            metadata["isolate_delivery_type"].get(sample_id)
        ),
        "host": _first_value(metadata["host"].get(sample_id)),
    }


def _apply_filters(rows, filters):
    filtered = rows
    for key, row_key in (
        ("pathogen", "pathogen"),
        ("region", "region"),
        ("center", "submitting_institution"),
        ("infection_type", "infection_type"),
        ("sequencing_platform", "sequencing_platform"),
        ("resistance_profile", "resistance_profile"),
    ):
        value = _clean_filter(filters.get(key))
        if value:
            filtered = [
                row for row in filtered if _equals(row.get(row_key), value)
            ]

    sequence_type = _clean_filter(filters.get("sequence_type"))
    if sequence_type:
        filtered = [
            row
            for row in filtered
            if _contains(
                _normalize_sequence_type(row.get("sequence_type")),
                _normalize_sequence_type(sequence_type),
            )
        ]

    carbapenemase = _clean_filter(filters.get("carbapenemase"))
    if carbapenemase:
        filtered = [
            row
            for row in filtered
            if _contains(row.get("carbapenemase"), carbapenemase)
        ]

    date_from = _parse_date(filters.get("collection_date_from"))
    if date_from:
        filtered = [
            row
            for row in filtered
            if row.get("collection_date")
            and row["collection_date"] >= date_from.isoformat()
        ]

    date_to = _parse_date(filters.get("collection_date_to"))
    if date_to:
        filtered = [
            row
            for row in filtered
            if row.get("collection_date")
            and row["collection_date"] <= date_to.isoformat()
        ]

    search = _clean_filter(filters.get("search"))
    if search:
        normalized = search.lower()
        filtered = [
            row
            for row in filtered
            if normalized
            in " ".join(
                str(row.get(key) or "")
                for key in (
                    "sample_unique_id",
                    "sequencing_sample_id",
                    "submitting_lab_sample_id",
                    "submitting_institution",
                    "sequence_type",
                    "carbapenemase",
                )
            ).lower()
        ]

    return filtered


def _paginate(rows, filters):
    page_size = _positive_int(filters.get("page_size"), default=5000, maximum=5000)
    page = _positive_int(filters.get("page"), default=1, maximum=None)
    start = (page - 1) * page_size
    return rows[start : start + page_size]


def _filter_options(rows):
    collection_dates = _sorted_unique(row.get("collection_date") for row in rows)
    return {
        "autonomous_communities": _sorted_unique(row.get("region") for row in rows),
        "centers": _sorted_unique(row.get("submitting_institution") for row in rows),
        "collection_date_min": collection_dates[0] if collection_dates else None,
        "collection_date_max": collection_dates[-1] if collection_dates else None,
        "infection_types": _sorted_unique(row.get("infection_type") for row in rows),
        "pathogens": _sorted_unique(row.get("pathogen") for row in rows),
        "resistance_profiles": _sorted_unique(
            row.get("resistance_profile") for row in rows
        ),
        "sequencing_platforms": _sorted_unique(
            row.get("sequencing_platform") for row in rows
        ),
        "sequence_types": _sorted_unique(row.get("sequence_type") for row in rows),
    }


def _columns():
    base_columns = [
        {
            "id": "sample_unique_id",
            "label": "Sample ID",
            "kind": "identifier",
            "source": "sample.sample_unique_id",
        },
        {
            "id": "sequencing_sample_id",
            "label": "Sequencing sample ID",
            "kind": "identifier",
            "source": "sample.sequencing_sample_id",
        },
    ]
    metadata_columns = [
        {
            "id": field,
            "label": spec["label"],
            "kind": spec["kind"],
            "source_properties": list(spec["source_properties"]),
        }
        for field, spec in FIELD_SPECS.items()
    ]
    return base_columns + metadata_columns


def _data_quality(rows, total_samples):
    field_quality = {}
    missing_fields = []
    for field, spec in FIELD_SPECS.items():
        matched_samples = len([row for row in rows if row.get(field)])
        field_quality[field] = {
            "matched_samples": matched_samples,
            "total_samples": total_samples,
            "matched_share": matched_samples / total_samples if total_samples else 0,
            "source_properties": list(spec["source_properties"]),
        }
        if matched_samples == 0:
            missing_fields.append(field)

    return {
        "fields": field_quality,
        "missing_operational_fields": missing_fields,
    }


def _query_payload(filters):
    filter_keys = (
        "search",
        "pathogen",
        "region",
        "sequence_type",
        "carbapenemase",
        "center",
        "infection_type",
        "sequencing_platform",
        "resistance_profile",
        "collection_date_from",
        "collection_date_to",
    )
    return {
        "filters": {
            key: filters.get(key)
            for key in filter_keys
            if _clean_filter(filters.get(key))
        },
        "page": _positive_int(filters.get("page"), default=1, maximum=None),
        "page_size": _positive_int(
            filters.get("page_size"), default=5000, maximum=5000
        ),
    }


def _property_query(aliases):
    query = Q()
    for alias in aliases:
        query |= Q(schema_property__property__iexact=alias)
    return query


def _multi_value_fields():
    return {"carbapenemase", "resistance_profile"}


def _first_value(values):
    return values[0] if values else None


def _first_location(values):
    value = _first_value(values)
    if value is None:
        return None
    return _location_label(value)


def _first_date(values):
    for value in values or []:
        parsed = _parse_date(value)
        if parsed:
            return parsed
    return None


def _first_sequence_type(values):
    value = _first_value(values)
    if not value:
        return None
    text = str(value).strip()
    if text.upper().startswith("ST"):
        return text
    if text.isdigit():
        return f"ST{text}"
    return text


def _joined_values(values):
    values = values or []
    return ", ".join(values) if values else None


def _split_values(value):
    labels = []
    for item in re.split(r"[;,|]", str(value or "")):
        label = _display_value(item)
        if label:
            labels.append(label)
    return labels


def _display_value(value):
    if value is None:
        return None
    value = _strip_ontology(str(value)).strip()
    value = re.sub(r"\s{2,}", " ", value)
    value = re.sub(r"(^,\s*|\s*,\s*$)", "", value)
    return value or None


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


def _location_label(value):
    label = _display_value(value)
    geo = _geo_for_label(label)
    return geo["label"] if geo else label


def _geo_for_label(label):
    geo = getattr(core.config, "DATABROWSER_GEOLOCATION_CENTROIDS", {}).get(
        _normalize_geo_key(label)
    )
    return dict(geo) if geo else None


def _normalize_geo_key(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", normalized)
    return " ".join(normalized.lower().split())


def _normalize_sequence_type(value):
    return (
        str(value or "")
        .upper()
        .replace(" ", "")
        .replace("-", "")
        .removeprefix("ST")
    )


def _clean_filter(value):
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _equals(left, right):
    return str(left or "").casefold() == str(right or "").casefold()


def _contains(left, right):
    return str(right or "").casefold() in str(left or "").casefold()


def _positive_int(value, *, default, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(parsed, 1)
    return min(parsed, maximum) if maximum else parsed


def _sorted_unique(values):
    return sorted(
        {value for value in values if value},
        key=lambda value: str(value).casefold(),
    )


def _normalize_project_name(project_name):
    return access_control._normalize_project_code(project_name)


def _project_label(project_name):
    return project_name.replace("_", " ").replace("-", " ").title()
