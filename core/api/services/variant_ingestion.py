from datetime import date, datetime

from django.db import transaction
from django.utils.dateparse import parse_date

from core import models
from core.api.utils import access_control

DEFAULT_CHUNK_SIZE = 1000
MAX_ALLELE_LENGTH = 255


def ingest_variants(payload, request_user=None, chunk_size=DEFAULT_CHUNK_SIZE):
    grouped_payloads = _normalize_payload(payload)
    if not grouped_payloads:
        raise ValueError("No variant payloads provided")

    # Merge repeated sample/date entries before replacing existing observations.
    groups = {}
    for item in grouped_payloads:
        sample_obj = _resolve_sample_from_candidates(
            item["sample_candidates"], request_user=request_user
        )
        analysis_date = _parse_required_date(item["analysis_date"])
        key = (sample_obj.pk, analysis_date)
        entry = groups.setdefault(
            key,
            {"sample": sample_obj, "analysis_date": analysis_date, "variants": []},
        )
        entry["variants"].extend(item["variants"])

    totals = {
        "samples_processed": 0,
        "variants_received": 0,
        "sample_variants_stored": 0,
        "sample_variants_replaced": 0,
        "distinct_variants_seen": 0,
        "annotations_seen": 0,
    }

    distinct_variant_keys = set()
    distinct_annotation_keys = set()

    for group in groups.values():
        sample_totals, variant_keys, annotation_keys = _ingest_sample_variant_group(
            group["sample"],
            group["analysis_date"],
            group["variants"],
            chunk_size=chunk_size,
        )
        totals["samples_processed"] += 1
        totals["variants_received"] += sample_totals["variants_received"]
        totals["sample_variants_stored"] += sample_totals["sample_variants_stored"]
        totals["sample_variants_replaced"] += sample_totals["sample_variants_replaced"]
        distinct_variant_keys.update(variant_keys)
        distinct_annotation_keys.update(annotation_keys)

    totals["distinct_variants_seen"] = len(distinct_variant_keys)
    totals["annotations_seen"] = len(distinct_annotation_keys)
    return totals


def _normalize_payload(payload):
    if isinstance(payload, list):
        return [_normalize_sample_payload(item) for item in payload]
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a JSON object or a list of JSON objects")
    if isinstance(payload.get("records"), list):
        return [_normalize_sample_payload(item) for item in payload["records"]]
    return [_normalize_sample_payload(payload)]


def _normalize_sample_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError("Each sample payload must be a JSON object")
    variants = payload.get("variants")
    if not isinstance(variants, list) or not variants:
        raise ValueError("variants must be a non-empty list")
    sample_id = (
        payload.get("sample_id")
        or payload.get("sample_unique_id")
        or payload.get("sample_name")
        or payload.get("sample")
    )
    if not sample_id or not isinstance(sample_id, str) or not sample_id.strip():
        raise ValueError("sample_id is required")
    analysis_date = (
        payload.get("analysis_date")
        or payload.get("bioinformatics_analysis_date")
        or payload.get("collection_date")
    )
    if analysis_date is None:
        raise ValueError("analysis_date is required")
    return {
        "sample_id": sample_id.strip(),
        "sample_candidates": _sample_candidates(sample_id, variants),
        "analysis_date": analysis_date,
        "variants": variants,
    }


def _sample_candidates(primary_sample_id, variants):
    candidates = []
    for candidate in [primary_sample_id] + [
        row.get("sample") for row in variants if isinstance(row, dict)
    ]:
        candidate = _clean_string(candidate)
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _resolve_sample_from_candidates(sample_candidates, request_user=None):
    for sample_identifier in sample_candidates:
        sample_obj = _resolve_sample(sample_identifier, request_user=request_user)
        if sample_obj is not None:
            return sample_obj
    raise ValueError(f"Sample not found: {sample_candidates[0]}")


def _resolve_sample(sample_identifier, request_user=None):
    queryset = models.Sample.objects.all()
    if request_user is not None:
        queryset = access_control.apply_sample_scope(queryset, request_user)

    for field_name in (
        "sample_unique_id",
        "sequencing_sample_id",
        "microbiology_lab_sample_id",
        "collecting_lab_sample_id",
        "submitting_lab_sample_id",
    ):
        sample_obj = queryset.filter(**{field_name: sample_identifier}).last()
        if sample_obj is not None:
            return sample_obj

    metadata_queryset = models.MetadataValues.objects.filter(
        value=sample_identifier,
        schema_property__property__in=[
            "unique_sample_id",
            "isolate_sample_id",
            "sample_id",
        ],
    ).select_related("sample")
    if request_user is not None:
        metadata_queryset = access_control.apply_metadata_values_scope(
            metadata_queryset, request_user
        )
    metadata_row = metadata_queryset.last()
    if metadata_row is not None:
        return metadata_row.sample
    return None


def _parse_required_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("analysis_date must use YYYY-MM-DD format")
    cleaned = value.strip()
    if len(cleaned) == 8 and cleaned.isdigit():
        cleaned = f"{cleaned[:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    parsed = parse_date(cleaned)
    if parsed is None:
        raise ValueError("analysis_date must use YYYY-MM-DD format")
    return parsed


def _ingest_sample_variant_group(sample_obj, analysis_date, raw_variants, chunk_size):
    seen_variant_ids = set()
    sample_totals = {
        "variants_received": 0,
        "sample_variants_stored": 0,
        "sample_variants_replaced": 0,
    }
    distinct_variant_keys = set()
    distinct_annotation_keys = set()

    with transaction.atomic():
        deleted_count, _ = models.SampleVariant.objects.filter(
            sample=sample_obj,
            analysis_date=analysis_date,
        ).delete()
        sample_totals["sample_variants_replaced"] = deleted_count

        for chunk in _chunks(raw_variants, chunk_size):
            normalized_rows = [_normalize_variant_row(row) for row in chunk]
            sample_totals["variants_received"] += len(normalized_rows)
            result = _store_variant_chunk(
                sample_obj,
                analysis_date,
                normalized_rows,
                seen_variant_ids=seen_variant_ids,
                chunk_size=chunk_size,
            )
            sample_totals["sample_variants_stored"] += result["sample_variants_stored"]
            distinct_variant_keys.update(result["variant_keys"])
            distinct_annotation_keys.update(result["annotation_keys"])

    return sample_totals, distinct_variant_keys, distinct_annotation_keys


def _chunks(items, chunk_size):
    for index in range(0, len(items), chunk_size):
        yield items[index : index + chunk_size]


def _normalize_variant_row(row):
    if not isinstance(row, dict):
        raise ValueError("Each variant must be a JSON object")
    chrom = _clean_string(
        row.get("chrom")
        or row.get("chromosome")
        or row.get("reference_genome_accession")
        or row.get("reference_genome")
    )
    position = _parse_positive_int(_first_present(row, "pos", "position"), "position")
    reference = _clean_string(
        row.get("ref") or row.get("reference") or row.get("reference_allele")
    ).upper()
    alternate = _clean_string(
        row.get("alt") or row.get("alternate") or row.get("alternate_allele")
    ).upper()
    if not chrom:
        raise ValueError("Variant chrom/chromosome is required")
    if not reference:
        raise ValueError("Variant reference/ref is required")
    if not alternate:
        raise ValueError("Variant alternate/alt is required")
    if len(reference) > MAX_ALLELE_LENGTH or len(alternate) > MAX_ALLELE_LENGTH:
        raise ValueError(
            f"Variant reference/alternate alleles cannot exceed {MAX_ALLELE_LENGTH} characters"
        )

    effect = _clean_string(row.get("effect"))
    gene = _clean_string(row.get("gene"))
    return {
        "chrom": chrom,
        "position": position,
        "reference": reference,
        "alternate": alternate,
        "variant_type": _infer_variant_type(reference, alternate),
        "depth": _parse_optional_int(_first_present(row, "depth", "dp")),
        "allele_frequency": _parse_optional_float(
            _first_present(row, "allele_frequency", "af")
        ),
        "gene_region": _clean_string(row.get("gene_region") or gene),
        "effect": effect,
        "functional_class": _clean_string(
            row.get("functional_class") or _infer_functional_class(effect)
        ),
        "locus_name": _clean_string(row.get("locus_name") or gene),
        "locus_id": _clean_string(row.get("locus_id") or row.get("gene_id")),
        "aminoacid_change": _clean_string(
            row.get("aminoacid_change")
            or row.get("hgvs_p")
            or row.get("hgvs_p_1_letter")
        ),
    }


def _store_variant_chunk(
    sample_obj,
    analysis_date,
    normalized_rows,
    seen_variant_ids,
    chunk_size,
):
    variant_keys = {_variant_key(row) for row in normalized_rows}
    variant_map = _get_or_create_variants(variant_keys, normalized_rows, chunk_size)

    sample_variant_by_variant_id = {}
    annotation_specs = {}
    for row in normalized_rows:
        variant_obj = variant_map[_variant_key(row)]
        if variant_obj.pk in seen_variant_ids:
            continue
        seen_variant_ids.add(variant_obj.pk)
        sample_variant_by_variant_id[variant_obj.pk] = models.SampleVariant(
            sample=sample_obj,
            variant=variant_obj,
            depth=row["depth"],
            allele_frequency=row["allele_frequency"],
            analysis_date=analysis_date,
        )
        if _has_annotation(row):
            annotation_key = (
                variant_obj.pk,
                row["gene_region"],
                row["effect"],
                row["aminoacid_change"],
            )
            annotation_specs[annotation_key] = {
                "variant": variant_obj,
                "gene_region": row["gene_region"],
                "effect": row["effect"],
                "functional_class": row["functional_class"],
                "locus_name": row["locus_name"],
                "locus_id": row["locus_id"],
                "aminoacid_change": row["aminoacid_change"],
            }

    if sample_variant_by_variant_id:
        models.SampleVariant.objects.bulk_create(
            list(sample_variant_by_variant_id.values()),
            batch_size=chunk_size,
            ignore_conflicts=True,
        )

    _bulk_create_missing_annotations(annotation_specs, chunk_size)
    return {
        "sample_variants_stored": len(sample_variant_by_variant_id),
        "variant_keys": set(variant_keys),
        "annotation_keys": set(annotation_specs.keys()),
    }


def _get_or_create_variants(variant_keys, normalized_rows, chunk_size):
    variant_map = _fetch_variants_by_keys(variant_keys)
    missing_keys = variant_keys - set(variant_map.keys())
    if missing_keys:
        rows_by_key = {_variant_key(row): row for row in normalized_rows}
        models.Variant.objects.bulk_create(
            [
                models.Variant(
                    chrom=rows_by_key[key]["chrom"],
                    position=rows_by_key[key]["position"],
                    reference=rows_by_key[key]["reference"],
                    alternate=rows_by_key[key]["alternate"],
                    variant_type=rows_by_key[key]["variant_type"],
                )
                for key in missing_keys
            ],
            batch_size=chunk_size,
            ignore_conflicts=True,
        )
        variant_map = _fetch_variants_by_keys(variant_keys)
    return variant_map


def _fetch_variants_by_keys(variant_keys):
    if not variant_keys:
        return {}
    chroms = {key[0] for key in variant_keys}
    positions = {key[1] for key in variant_keys}
    references = {key[2] for key in variant_keys}
    alternates = {key[3] for key in variant_keys}
    candidates = models.Variant.objects.filter(
        chrom__in=chroms,
        position__in=positions,
        reference__in=references,
        alternate__in=alternates,
    )
    return {
        (item.chrom, item.position, item.reference, item.alternate): item
        for item in candidates
        if (item.chrom, item.position, item.reference, item.alternate) in variant_keys
    }


def _bulk_create_missing_annotations(annotation_specs, chunk_size):
    if not annotation_specs:
        return
    variant_ids = {key[0] for key in annotation_specs}
    existing_keys = set(
        models.VariantAnnotation.objects.filter(variant_id__in=variant_ids).values_list(
            "variant_id",
            "gene_region",
            "effect",
            "aminoacid_change",
        )
    )
    missing_specs = [
        spec for key, spec in annotation_specs.items() if key not in existing_keys
    ]
    if not missing_specs:
        return
    models.VariantAnnotation.objects.bulk_create(
        [models.VariantAnnotation(**spec) for spec in missing_specs],
        batch_size=chunk_size,
        ignore_conflicts=True,
    )


def _variant_key(row):
    return (row["chrom"], row["position"], row["reference"], row["alternate"])


def _has_annotation(row):
    return any(
        row[field_name]
        for field_name in (
            "gene_region",
            "effect",
            "functional_class",
            "locus_name",
            "locus_id",
            "aminoacid_change",
        )
    )


def _clean_string(value):
    if value is None:
        return ""
    return str(value).strip()


def _first_present(mapping, *keys):
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _parse_positive_int(value, field_name):
    if value is None or str(value).strip() == "":
        raise ValueError(f"{field_name} is required")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return parsed


def _parse_optional_int(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    if cleaned == "" or cleaned.upper() in {"NA", "N/A", "NONE", "NULL"}:
        return None
    try:
        parsed = int(float(cleaned))
    except (TypeError, ValueError) as exc:
        raise ValueError("depth must be an integer") from exc
    if parsed < 0:
        raise ValueError("depth cannot be negative")
    return parsed


def _parse_optional_float(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    if cleaned == "" or cleaned.upper() in {"NA", "N/A", "NONE", "NULL"}:
        return None
    try:
        return float(cleaned)
    except (TypeError, ValueError) as exc:
        raise ValueError("allele_frequency must be a number") from exc


def _infer_variant_type(reference, alternate):
    if len(reference) == 1 and len(alternate) == 1:
        return "SNV"
    if len(reference) == len(alternate):
        return "MNV"
    if len(alternate) > len(reference):
        return "insertion_or_complex"
    return "deletion_or_complex"


def _infer_functional_class(effect):
    if not effect:
        return ""
    normalized = effect.replace("&", ",").split(",", 1)[0].strip()
    for suffix in ("_variant", "_mutation"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized
