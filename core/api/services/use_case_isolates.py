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


DATA_CONTRACT_VERSION = "1.2"

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
SEQUENCE_TYPE_1_SCHEME_ALIASES = (
    "sequence_type.sequence_type_1_scheme",
    "sequence_type_1_scheme",
)
SEQUENCE_TYPE_2_SCHEME_ALIASES = (
    "sequence_type.sequence_type_2_scheme",
    "sequence_type_2_scheme",
)
SEQUENCE_TYPE_ORIGIN_ALIASES = ("sequence_type.origin",)
AMR_GENE_NAME_ALIASES = ("amr_acquired_genes.gene_name",)
AMR_ALLELE_NAME_ALIASES = ("amr_acquired_genes.allele_name",)
AMR_CLASSIFICATION_ALIASES = ("amr_acquired_genes.classification",)
AMR_ORIGIN_ALIASES = ("amr_acquired_genes.origin",)
AMR_GENE_PROFILE_ALIASES = (
    *AMR_GENE_NAME_ALIASES,
    *AMR_ALLELE_NAME_ALIASES,
    *AMR_CLASSIFICATION_ALIASES,
    *AMR_ORIGIN_ALIASES,
)
BLA_CARB_ALIASES = ("bla_carb", "amr_acquired_genes.bla_carb")
BLA_ESBL_ALIASES = ("bla_esbl", "amr_acquired_genes.bla_esbl")
ORGANISM_SPECIES_ALIASES = ("organism.species",)
ORGANISM_SPECIES_GROUP_ALIASES = (
    "organism.species_group",
    "species_group",
)
ORGANISM_ORIGIN_ALIASES = ("organism.origin",)
ORGANISM_FIELD_ALIASES = (
    *ORGANISM_SPECIES_ALIASES,
    *ORGANISM_SPECIES_GROUP_ALIASES,
    *ORGANISM_ORIGIN_ALIASES,
)
COLLECTING_PROVINCE_ALIASES = (
    "collecting_institution_geo_loc_region",
    "geo_loc_region",
)
SUBMITTING_PROVINCE_ALIASES = ("submitting_geo_loc_region",)
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
    "province": {
        "label": "Preferred province",
        "kind": "geography",
        "source_properties": (
            *COLLECTING_PROVINCE_ALIASES,
            *SUBMITTING_PROVINCE_ALIASES,
        ),
    },
    "collecting_province": {
        "label": "Collecting province",
        "kind": "geography",
        "source_properties": COLLECTING_PROVINCE_ALIASES,
    },
    "submitting_province": {
        "label": "Submitting province",
        "kind": "geography",
        "source_properties": SUBMITTING_PROVINCE_ALIASES,
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
    "sequence_type": {
        "label": "Sequence type",
        "kind": "categorical",
        "source_properties": SEQUENCE_TYPE_ALIASES,
    },
    "sequence_type_1_scheme": {
        "label": "Sequence type 1 scheme",
        "kind": "categorical",
        "source_properties": SEQUENCE_TYPE_1_SCHEME_ALIASES,
        "include_column": False,
    },
    "sequence_type_2_scheme": {
        "label": "Sequence type 2 scheme",
        "kind": "categorical",
        "source_properties": SEQUENCE_TYPE_2_SCHEME_ALIASES,
        "include_column": False,
    },
    "sequence_type_origin": {
        "label": "Sequence type origin",
        "kind": "categorical",
        "source_properties": SEQUENCE_TYPE_ORIGIN_ALIASES,
        "include_column": False,
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
COMPUTED_FIELD_SPECS = {
    "species": {
        "label": "Species",
        "kind": "categorical",
        "source_properties": ORGANISM_FIELD_ALIASES,
    },
    "species_group": {
        "label": "Species group",
        "kind": "categorical",
        "source_properties": ORGANISM_FIELD_ALIASES,
    },
    "amr_gene": {
        "label": "Gene",
        "kind": "categorical",
        "source_properties": AMR_GENE_NAME_ALIASES,
    },
    "amr_allele": {
        "label": "Allele",
        "kind": "categorical",
        "source_properties": AMR_ALLELE_NAME_ALIASES,
    },
    "amr_classification": {
        "label": "Classification",
        "kind": "categorical",
        "source_properties": AMR_CLASSIFICATION_ALIASES,
    },
    "bla_carb": {
        "label": "bla_carb",
        "kind": "categorical",
        "source_properties": (*AMR_GENE_PROFILE_ALIASES, *BLA_CARB_ALIASES),
    },
    "bla_esbl": {
        "label": "bla_esbl",
        "kind": "categorical",
        "source_properties": (*AMR_GENE_PROFILE_ALIASES, *BLA_ESBL_ALIASES),
    },
    "data_origin": {
        "label": "Data origin",
        "kind": "categorical",
        "source_properties": (
            *ORGANISM_ORIGIN_ALIASES,
            *AMR_ORIGIN_ALIASES,
            *SEQUENCE_TYPE_ORIGIN_ALIASES,
        ),
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
    metadata["amr_summary"] = _amr_gene_summaries(sample_ids)
    metadata["organism_summary"] = _organism_summaries(sample_ids)
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
            (
                "Rows are generated from project-scoped samples and metadata "
                "values in bulk."
            ),
            (
                "Complex metadata is resolved through grouped dotted properties "
                "where available."
            ),
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


def _amr_gene_summaries(sample_ids):
    summaries = defaultdict(_empty_amr_summary)
    if not sample_ids:
        return summaries

    grouped_values = defaultdict(lambda: defaultdict(list))
    group_order = {}
    seen_values = defaultdict(lambda: defaultdict(set))
    rows = (
        models.MetadataValues.objects.filter(sample_id__in=sample_ids)
        .filter(group__isnull=False)
        .filter(_property_query(AMR_GENE_PROFILE_ALIASES))
        .exclude(value__isnull=True)
        .exclude(value="")
        .values(
            "sample_id",
            "group_id",
            "group__group_index",
            "schema_property__property",
            "value",
        )
        .order_by(
            "sample_id",
            "group__group_index",
            "schema_property__property",
            "value",
        )
    )

    for row in rows:
        field = _amr_gene_field(row["schema_property__property"])
        value = _display_value(row["value"])
        if not field or not value:
            continue
        group_key = (row["sample_id"], row["group_id"])
        group_order[group_key] = row["group__group_index"] or 0
        value_key = value.lower()
        if value_key in seen_values[group_key][field]:
            continue
        seen_values[group_key][field].add(value_key)
        grouped_values[group_key][field].append(value)

    for group_key, values_by_field in sorted(
        grouped_values.items(),
        key=lambda item: (item[0][0], group_order.get(item[0], 0), item[0][1] or 0),
    ):
        sample_id, _group_id = group_key
        record = _amr_record(values_by_field)
        if record is None:
            continue
        summaries[sample_id]["records"].append(record)

    future_buckets = _future_bla_bucket_values(sample_ids)
    for sample_id, values_by_bucket in future_buckets.items():
        summaries[sample_id]["future_bla_carb"].extend(
            values_by_bucket.get("bla_carb", [])
        )
        summaries[sample_id]["future_bla_esbl"].extend(
            values_by_bucket.get("bla_esbl", [])
        )

    for sample_id, summary in summaries.items():
        _finalize_amr_summary(summary)
    return summaries


def _organism_summaries(sample_ids):
    summaries = defaultdict(dict)
    if not sample_ids:
        return summaries

    grouped_values = defaultdict(lambda: defaultdict(list))
    group_order = {}
    seen_values = defaultdict(lambda: defaultdict(set))
    rows = (
        models.MetadataValues.objects.filter(sample_id__in=sample_ids)
        .filter(group__isnull=False)
        .filter(_property_query(ORGANISM_FIELD_ALIASES))
        .exclude(value__isnull=True)
        .exclude(value="")
        .values(
            "sample_id",
            "group_id",
            "group__group_index",
            "schema_property__property",
            "value",
        )
        .order_by(
            "sample_id",
            "group__group_index",
            "schema_property__property",
            "value",
        )
    )

    for row in rows:
        field = _organism_field(row["schema_property__property"])
        value = _display_value(row["value"])
        if not field or not value:
            continue
        group_key = (row["sample_id"], row["group_id"])
        group_order[group_key] = row["group__group_index"] or 0
        value_key = value.lower()
        if value_key in seen_values[group_key][field]:
            continue
        seen_values[group_key][field].add(value_key)
        grouped_values[group_key][field].append(value)

    records_by_sample = defaultdict(list)
    for group_key, values_by_field in sorted(
        grouped_values.items(),
        key=lambda item: (item[0][0], group_order.get(item[0], 0), item[0][1] or 0),
    ):
        sample_id, _group_id = group_key
        record = _organism_record(values_by_field)
        if record:
            records_by_sample[sample_id].append(record)

    for sample_id, records in records_by_sample.items():
        summaries[sample_id] = _organism_summary(records)
    return summaries


def _row_payload(sample_row, metadata):
    sample_id = sample_row["id"]
    collection_date = _first_date(metadata["collection_date"].get(sample_id))
    if collection_date is None:
        collection_date = _date_from_datetime(sample_row.get("sequencing_date"))
    if collection_date is None:
        collection_date = _date_from_datetime(sample_row.get("created_at"))

    collecting_region = _first_location(metadata["collecting_region"].get(sample_id))
    submitting_region = _first_location(metadata["submitting_region"].get(sample_id))
    collecting_province = _first_value(metadata["collecting_province"].get(sample_id))
    submitting_province = _first_value(metadata["submitting_province"].get(sample_id))
    submitting_institution = _first_value(
        metadata["submitting_institution"].get(sample_id)
    )
    if submitting_institution is None:
        submitting_institution = _display_value(
            sample_row.get("collecting_institution")
        )
    organism_summary = metadata["organism_summary"].get(sample_id) or {}
    amr_summary = metadata["amr_summary"].get(sample_id) or _empty_amr_summary()
    sequence_type = _first_sequence_type(metadata["sequence_type"].get(sample_id))
    sequence_type_origins = metadata["sequence_type_origin"].get(sample_id, [])
    origins = _unique_values(
        [
            *organism_summary.get("origins", []),
            *amr_summary.get("origins", []),
            *sequence_type_origins,
        ]
    )
    is_sequenced = _is_sequenced(origins, sequence_type)
    data_origin = _preferred_origin(origins, is_sequenced)
    fallback_pathogen = _first_value(metadata["pathogen"].get(sample_id))
    if organism_summary:
        species = organism_summary.get("species")
        species_group = organism_summary.get("species_group")
    else:
        species = fallback_pathogen if is_sequenced else None
        species_group = None if is_sequenced else fallback_pathogen
    pathogen = species or species_group or fallback_pathogen

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
        "collecting_province": collecting_province,
        "submitting_province": submitting_province,
        "province": collecting_province or submitting_province,
        "pathogen": pathogen,
        "species": species,
        "species_group": species_group,
        "pathogen_origin": organism_summary.get("origin"),
        "sequence_type": sequence_type,
        "sequence_type_1_scheme": _first_value(
            metadata["sequence_type_1_scheme"].get(sample_id)
        ),
        "sequence_type_2_scheme": _first_value(
            metadata["sequence_type_2_scheme"].get(sample_id)
        ),
        "sequence_type_schemes": _unique_values(
            [
                *metadata["sequence_type_1_scheme"].get(sample_id, []),
                *metadata["sequence_type_2_scheme"].get(sample_id, []),
            ]
        ),
        "amr_gene": _joined_values(amr_summary.get("genes")),
        "amr_allele": _joined_values(amr_summary.get("alleles")),
        "amr_classification": _joined_values(amr_summary.get("classifications")),
        "amr_gene_records": amr_summary.get("records", []),
        "bla_carb": _joined_values(amr_summary.get("bla_carb")),
        "bla_esbl": _joined_values(amr_summary.get("bla_esbl")),
        "data_origin": data_origin,
        "is_sequenced": is_sequenced,
        "sequencing_status": "Sequenced" if is_sequenced else "Not sequenced",
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
        ("province", "province"),
        ("center", "submitting_institution"),
        ("infection_type", "infection_type"),
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

    for filter_key, record_key in (
        ("gene", "gene"),
        ("allele", "allele"),
        ("classification", "classification"),
    ):
        values = _filter_values(filters, filter_key)
        if values:
            filtered = [
                row
                for row in filtered
                if _row_has_all_record_values(row, record_key, values)
            ]

    bla_groups = _filter_values(filters, "bla_group")
    if bla_groups:
        filtered = [
            row for row in filtered if _row_has_all_bla_groups(row, bla_groups)
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
        tokens = _search_tokens(search)
        filtered = [
            row
            for row in filtered
            if all(token in _row_search_text(row) for token in tokens)
        ]

    return filtered


def _paginate(rows, filters):
    page_size = _positive_int(filters.get("page_size"), default=5000, maximum=5000)
    page = _positive_int(filters.get("page"), default=1, maximum=None)
    start = (page - 1) * page_size
    return rows[start : start + page_size]


def _filter_options(rows):
    collection_dates = _sorted_unique(row.get("collection_date") for row in rows)
    amr_records = [
        record for row in rows for record in row.get("amr_gene_records", [])
    ]
    return {
        "autonomous_communities": _sorted_unique(row.get("region") for row in rows),
        "alleles": _sorted_unique(record.get("allele") for record in amr_records),
        "bla_groups": _sorted_unique(
            _classification_bucket(record.get("classification"))
            for record in amr_records
        ),
        "centers": _sorted_unique(row.get("submitting_institution") for row in rows),
        "classifications": _sorted_unique(
            record.get("classification") for record in amr_records
        ),
        "collection_date_min": collection_dates[0] if collection_dates else None,
        "collection_date_max": collection_dates[-1] if collection_dates else None,
        "genes": _sorted_unique(record.get("gene") for record in amr_records),
        "infection_types": _sorted_unique(row.get("infection_type") for row in rows),
        "pathogens": _sorted_unique(row.get("pathogen") for row in rows),
        "provinces": _sorted_unique(row.get("province") for row in rows),
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
        if spec.get("include_column", True)
    ]
    computed_columns = [
        _computed_column(field, spec)
        for field, spec in COMPUTED_FIELD_SPECS.items()
    ]
    return base_columns + metadata_columns + computed_columns


def _computed_column(field, spec):
    column = {
        "id": field,
        "label": spec["label"],
        "kind": spec["kind"],
        "source_properties": list(spec["source_properties"]),
    }
    if field.startswith("amr_") or field.startswith("bla_"):
        column["group_property"] = "amr_acquired_genes"
    elif field in {"species", "species_group"}:
        column["group_property"] = "organism"
    return column


def _data_quality(rows, total_samples):
    field_quality = {}
    missing_fields = []
    for field, spec in {**FIELD_SPECS, **COMPUTED_FIELD_SPECS}.items():
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
        "province",
        "sequence_type",
        "gene",
        "allele",
        "classification",
        "bla_group",
        "center",
        "infection_type",
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
    return set()


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


def _unique_values(values):
    unique = []
    seen = set()
    for value in values or []:
        value = _display_value(value)
        if not value:
            continue
        value_key = value.lower()
        if value_key in seen:
            continue
        seen.add(value_key)
        unique.append(value)
    return unique


def _empty_amr_summary():
    return {
        "records": [],
        "genes": [],
        "alleles": [],
        "classifications": [],
        "bla_carb": [],
        "bla_esbl": [],
        "future_bla_carb": [],
        "future_bla_esbl": [],
        "origins": [],
    }


def _amr_gene_field(property_name):
    normalized = str(property_name or "").lower()
    if normalized in {alias.lower() for alias in AMR_GENE_NAME_ALIASES}:
        return "gene"
    if normalized in {alias.lower() for alias in AMR_ALLELE_NAME_ALIASES}:
        return "allele"
    if normalized in {alias.lower() for alias in AMR_CLASSIFICATION_ALIASES}:
        return "classification"
    if normalized in {alias.lower() for alias in AMR_ORIGIN_ALIASES}:
        return "origin"
    return None


def _amr_record(values_by_field):
    gene = _first_value(values_by_field.get("gene"))
    allele = _first_value(values_by_field.get("allele"))
    classification = _first_value(values_by_field.get("classification"))
    origin = _first_value(values_by_field.get("origin"))
    if not any((gene, allele, classification)):
        return None
    return {
        "gene": gene,
        "allele": allele,
        "classification": classification,
        "origin": _normalize_origin(origin),
        "label": _amr_record_label(gene=gene, allele=allele),
    }


def _amr_record_label(*, gene, allele):
    if gene and allele:
        return f"{gene} > {allele}"
    return gene or allele


def _future_bla_bucket_values(sample_ids):
    values = defaultdict(lambda: defaultdict(list))
    aliases = (*BLA_CARB_ALIASES, *BLA_ESBL_ALIASES)
    rows = _metadata_rows(sample_ids, aliases)
    for row in rows:
        property_name = str(row["schema_property__property"] or "").lower()
        label = _display_value(row["value"])
        if not label:
            continue
        if property_name in {alias.lower() for alias in BLA_CARB_ALIASES}:
            values[row["sample_id"]]["bla_carb"].extend(_split_values(label))
        elif property_name in {alias.lower() for alias in BLA_ESBL_ALIASES}:
            values[row["sample_id"]]["bla_esbl"].extend(_split_values(label))
    return values


def _metadata_rows(sample_ids, aliases):
    if not sample_ids or not aliases:
        return []
    return (
        models.MetadataValues.objects.filter(sample_id__in=sample_ids)
        .filter(_property_query(aliases))
        .exclude(value__isnull=True)
        .exclude(value="")
        .values("sample_id", "schema_property__property", "value")
        .order_by("sample_id", "schema_property__property", "value")
        .distinct()
    )


def _finalize_amr_summary(summary):
    records = sorted(
        summary["records"],
        key=lambda record: (
            str(record.get("gene") or "").casefold(),
            str(record.get("allele") or "").casefold(),
            str(record.get("classification") or "").casefold(),
        ),
    )
    summary["records"] = records
    summary["genes"] = _sorted_unique(record.get("gene") for record in records)
    summary["alleles"] = _sorted_unique(record.get("allele") for record in records)
    summary["classifications"] = _sorted_unique(
        record.get("classification") for record in records
    )
    summary["origins"] = _sorted_unique(record.get("origin") for record in records)

    bla_carb = []
    bla_esbl = []
    for record in records:
        label = record.get("label")
        bucket = _classification_bucket(record.get("classification"))
        if bucket == "bla_carb" and label:
            bla_carb.append(label)
        elif bucket == "bla_esbl" and label:
            bla_esbl.append(label)
    bla_carb.extend(summary.get("future_bla_carb", []))
    bla_esbl.extend(summary.get("future_bla_esbl", []))
    summary["bla_carb"] = _sorted_unique(bla_carb)
    summary["bla_esbl"] = _sorted_unique(bla_esbl)


def _classification_bucket(classification):
    normalized = str(classification or "").casefold().replace("-", "_")
    if normalized == "bla_carb":
        return "bla_carb"
    if normalized.startswith("bla_esbl"):
        return "bla_esbl"
    return None


def _organism_field(property_name):
    normalized = str(property_name or "").lower()
    if normalized in {alias.lower() for alias in ORGANISM_SPECIES_ALIASES}:
        return "species"
    if normalized in {alias.lower() for alias in ORGANISM_SPECIES_GROUP_ALIASES}:
        return "species_group"
    if normalized in {alias.lower() for alias in ORGANISM_ORIGIN_ALIASES}:
        return "origin"
    return None


def _organism_record(values_by_field):
    species = _first_value(values_by_field.get("species"))
    species_group = _first_value(values_by_field.get("species_group"))
    origin = _normalize_origin(_first_value(values_by_field.get("origin")))
    if not any((species, species_group)):
        return None
    return {
        "species": species,
        "species_group": species_group,
        "origin": origin,
    }


def _organism_summary(records):
    isciii_records = [
        record for record in records if record.get("origin") == "isciii"
    ]
    submitting_records = [
        record for record in records if record.get("origin") == "submitting"
    ]
    preferred_species_record = (
        isciii_records[0] if isciii_records else records[0] if records else {}
    )
    preferred_group_record = (
        next((record for record in records if record.get("species_group")), None)
        or (submitting_records[0] if submitting_records else None)
        or preferred_species_record
    )
    species = preferred_species_record.get("species")
    if preferred_species_record.get("origin") == "submitting":
        species = None
    species_group = preferred_group_record.get("species_group")
    if not species_group and preferred_group_record.get("origin") == "submitting":
        species_group = preferred_group_record.get("species")
    return {
        "species": species,
        "species_group": species_group,
        "origin": preferred_species_record.get("origin"),
        "origins": _sorted_unique(record.get("origin") for record in records),
    }


def _normalize_origin(origin):
    normalized = str(origin or "").strip().casefold()
    if normalized in {"isciii", "submitting"}:
        return normalized
    return _display_value(origin)


def _is_sequenced(origins, sequence_type):
    return "isciii" in {str(origin).casefold() for origin in origins} or bool(
        sequence_type
    )


def _preferred_origin(origins, is_sequenced):
    normalized_origins = {str(origin).casefold() for origin in origins}
    if is_sequenced or "isciii" in normalized_origins:
        return "isciii"
    if "submitting" in normalized_origins:
        return "submitting"
    return None


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


def _filter_values(filters, key):
    value = filters.get(key)
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = re.split(r"[,;|]", str(value))
    return [
        cleaned
        for cleaned in (_display_value(raw_value) for raw_value in raw_values)
        if cleaned
    ]


def _row_has_all_record_values(row, record_key, values):
    available_values = {
        str(record.get(record_key) or "").casefold()
        for record in row.get("amr_gene_records", [])
    }
    return all(value.casefold() in available_values for value in values)


def _row_has_all_bla_groups(row, bla_groups):
    available_groups = {
        _classification_bucket(record.get("classification"))
        for record in row.get("amr_gene_records", [])
    }
    return all(group.casefold() in available_groups for group in bla_groups)


def _search_tokens(search):
    return [
        token.casefold()
        for token in re.split(r"[\s,;|]+", str(search or ""))
        if token
    ]


def _row_search_text(row):
    record_values = [
        str(record.get(key) or "")
        for record in row.get("amr_gene_records", [])
        for key in ("gene", "allele", "classification", "origin", "label")
    ]
    row_values = [
        str(row.get(key) or "")
        for key in (
            "sample_unique_id",
            "sequencing_sample_id",
            "submitting_lab_sample_id",
            "submitting_institution",
            "province",
            "species",
            "species_group",
            "sequence_type",
            "amr_gene",
            "amr_allele",
            "amr_classification",
            "bla_carb",
            "bla_esbl",
        )
    ]
    return " ".join([*row_values, *record_values]).casefold()


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
