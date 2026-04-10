import re

from django.db.models import Count, Exists, F, Max, Min, OuterRef, Q, Subquery
from django.utils.dateparse import parse_date

from core import models
from core.api.utils import access_control


HGVS_GENOMIC_RE = re.compile(r"^g\.(\d+)([A-Za-z]+)>([A-Za-z]+)$")
COLLECTION_DATE_PROPERTY = "sample_collection_date"
SEQUENCING_PLATFORM_PROPERTY = "sequencing_instrument_platform"


def parse_hgvs_genomic(value):
    if not isinstance(value, str):
        raise ValueError(
            "Invalid HGVS genomic variant. Expected format: g.<position><ref>><alt>"
        )
    normalized = "".join(value.strip().split())
    match = HGVS_GENOMIC_RE.match(normalized)
    if not match:
        raise ValueError(
            "Invalid HGVS genomic variant. Expected format: g.<position><ref>><alt>"
        )
    position = int(match.group(1))
    if position <= 0:
        raise ValueError(
            "Invalid HGVS genomic variant. Expected format: g.<position><ref>><alt>"
        )
    return {
        "variant": f"g.{position}{match.group(2).upper()}>{match.group(3).upper()}",
        "position": position,
        "reference_allele": match.group(2).upper(),
        "alternate_allele": match.group(3).upper(),
    }


def search_variants(filters, request_user=None):
    query = _resolve_variant_query(filters)
    sample_queryset = _visible_samples(filters, request_user=request_user)
    queryset = _visible_sample_variants(
        filters,
        sample_queryset=sample_queryset,
        variant_query=query,
    )

    visible_sample_count = sample_queryset.distinct().count()
    sample_count = queryset.values("sample_id").distinct().count()
    global_allele_frequency = (
        round(sample_count / visible_sample_count, 4) if visible_sample_count else 0
    )

    query_response = {
        "variant": query["variant"],
        "position": query["position"],
        "reference_allele": query["reference_allele"],
        "alternate_allele": query["alternate_allele"],
        "reference_genome": filters.get("reference_genome")
        or query.get("reference_genome"),
    }
    summary = {
        "sample_count": sample_count,
        "visible_sample_count": visible_sample_count,
        "global_allele_frequency": global_allele_frequency,
    }
    return {"query": query_response, "summary": summary, "queryset": queryset}


def serialize_search_results(sample_variant_rows):
    rows = list(sample_variant_rows)
    sample_ids = [row.sample_id for row in rows]
    metadata_by_sample = _sample_metadata_map(
        sample_ids,
        [COLLECTION_DATE_PROPERTY, SEQUENCING_PLATFORM_PROPERTY],
    )
    results = []
    for row in rows:
        annotation = _first_annotation(row.variant)
        metadata = metadata_by_sample.get(row.sample_id, {})
        results.append(
            {
                "sample_id": row.sample.sample_unique_id,
                "variant": _variant_hgvs(row.variant),
                "position": row.variant.position,
                "reference_allele": row.variant.reference,
                "alternate_allele": row.variant.alternate,
                "allele_frequency": row.allele_frequency,
                "effect": annotation.effect if annotation else "",
                "depth": row.depth,
                "type": row.variant.variant_type,
                "gene_region": annotation.gene_region if annotation else "",
                "functional_class": annotation.functional_class if annotation else "",
                "locus_name": annotation.locus_name if annotation else "",
                "locus_id": annotation.locus_id if annotation else "",
                "aminoacid_change": annotation.aminoacid_change if annotation else "",
                "collection_date": metadata.get(COLLECTION_DATE_PROPERTY),
                "sequencing_platform": metadata.get(SEQUENCING_PLATFORM_PROPERTY),
                "reference_genome": row.variant.chrom,
                "analysis_date": row.analysis_date,
                "project_name": (
                    row.sample.schema_obj.schema_app_name
                    if row.sample.schema_obj
                    else None
                ),
            }
        )
    return results


def variant_summary(filters, request_user=None):
    sample_queryset = _visible_samples(filters, request_user=request_user)
    queryset = _visible_sample_variants(filters, sample_queryset=sample_queryset)

    totals = {
        "visible_sample_count": sample_queryset.distinct().count(),
        "samples_with_variants": queryset.values("sample_id").distinct().count(),
        "variant_observations": queryset.count(),
        "distinct_variants": queryset.values("variant_id").distinct().count(),
    }
    reference_genomes = _label_value_rows(
        queryset.values(label=F("variant__chrom"))
        .annotate(value=Count("id"))
        .order_by("-value", "label")[:50]
    )
    variant_counts = _label_value_rows(
        queryset.values(label=F("variant__position"))
        .annotate(value=Count("id"))
        .order_by("-value", "label")[:50]
    )
    impact_classes = _label_value_rows(
        queryset.exclude(variant__annotations__functional_class="")
        .values(label=F("variant__annotations__functional_class"))
        .annotate(value=Count("id", distinct=True))
        .order_by("-value", "label")[:50]
    )
    projects = _label_value_rows(
        queryset.values(label=F("sample__schema_obj__schema_app_name"))
        .annotate(value=Count("id"))
        .order_by("-value", "label")
    )
    return {
        "totals": totals,
        "reference_genomes": reference_genomes,
        "variant_counts": variant_counts,
        "impact_classes": impact_classes,
        "projects": projects,
    }


def reference_genomes(filters, request_user=None):
    sample_queryset = _visible_samples(filters, request_user=request_user)
    queryset = _visible_sample_variants(filters, sample_queryset=sample_queryset)
    rows = (
        queryset.values("variant__chrom")
        .annotate(
            sample_count=Count("sample_id", distinct=True),
            variant_observation_count=Count("id"),
            distinct_variant_count=Count("variant_id", distinct=True),
        )
        .order_by("variant__chrom")
    )
    return [
        {
            "reference_genome": row["variant__chrom"],
            "sample_count": row["sample_count"],
            "variant_observation_count": row["variant_observation_count"],
            "distinct_variant_count": row["distinct_variant_count"],
        }
        for row in rows
    ]


def filter_options(filters, request_user=None):
    sample_queryset = _visible_samples(filters, request_user=request_user).filter(
        variant_observations__isnull=False
    )
    sample_ids = Subquery(sample_queryset.values("id").distinct())
    date_queryset = (
        models.MetadataValues.objects.filter(
            sample_id__in=sample_ids,
            schema_property__property__iexact=COLLECTION_DATE_PROPERTY,
        )
        .exclude(value__isnull=True)
        .exclude(value="")
    )
    platform_rows = (
        models.MetadataValues.objects.filter(
            sample_id__in=sample_ids,
            schema_property__property__iexact=SEQUENCING_PLATFORM_PROPERTY,
        )
        .exclude(value__isnull=True)
        .exclude(value="")
        .values_list("value", flat=True)
        .distinct()
        .order_by("value")
    )
    date_range = date_queryset.aggregate(min=Min("value"), max=Max("value"))
    return {
        "collection_date": {
            "min": date_range["min"],
            "max": date_range["max"],
        },
        "sequencing_platforms": [
            {"label": value, "value": value} for value in platform_rows
        ],
    }


def _resolve_variant_query(filters):
    variant = filters.get("variant")
    if variant:
        query = parse_hgvs_genomic(variant)
    else:
        position = filters.get("position")
        reference = filters.get("ref")
        alternate = filters.get("alt")
        if position is None or not reference or not alternate:
            raise ValueError("Provide variant or position/ref/alt")
        query = {
            "variant": f"g.{position}{reference.upper()}>{alternate.upper()}",
            "position": position,
            "reference_allele": reference.upper(),
            "alternate_allele": alternate.upper(),
        }
    reference_genome = filters.get("reference_genome")
    if reference_genome:
        query["reference_genome"] = reference_genome
    return query


def _visible_samples(filters, request_user=None):
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

    sample_id = filters.get("sample_id")
    if sample_id:
        queryset = queryset.filter(sample_unique_id=sample_id)

    collection_date_from = filters.get("collection_date_from")
    if collection_date_from:
        queryset = _filter_sample_metadata(
            queryset,
            COLLECTION_DATE_PROPERTY,
            Q(value__gte=collection_date_from.isoformat()),
        )

    collection_date_to = filters.get("collection_date_to")
    if collection_date_to:
        queryset = _filter_sample_metadata(
            queryset,
            COLLECTION_DATE_PROPERTY,
            Q(value__lte=collection_date_to.isoformat()),
        )

    sequencing_platform = filters.get("sequencing_platform")
    if sequencing_platform:
        queryset = _filter_sample_metadata(
            queryset,
            SEQUENCING_PLATFORM_PROPERTY,
            Q(value__iexact=sequencing_platform),
        )

    return queryset


def _visible_sample_variants(filters, sample_queryset, variant_query=None):
    queryset = (
        models.SampleVariant.objects.filter(
            sample_id__in=Subquery(sample_queryset.values("id"))
        )
        .select_related("sample", "sample__schema_obj", "variant")
        .prefetch_related("variant__annotations")
        .order_by("variant__position", "sample__sample_unique_id", "id")
    )

    if variant_query:
        queryset = queryset.filter(
            variant__position=variant_query["position"],
            variant__reference=variant_query["reference_allele"],
            variant__alternate=variant_query["alternate_allele"],
        )
        reference_genome = variant_query.get("reference_genome")
        if reference_genome:
            queryset = queryset.filter(variant__chrom__iexact=reference_genome)
    else:
        reference_genome = filters.get("reference_genome")
        if reference_genome:
            queryset = queryset.filter(variant__chrom__iexact=reference_genome)

    effect = filters.get("effect")
    if effect:
        queryset = queryset.filter(variant__annotations__effect__iexact=effect)

    locus_name = filters.get("locus_name")
    if locus_name:
        queryset = queryset.filter(variant__annotations__locus_name__iexact=locus_name)

    locus_id = filters.get("locus_id")
    if locus_id:
        queryset = queryset.filter(variant__annotations__locus_id__iexact=locus_id)

    aminoacid_change = filters.get("aminoacid_change")
    if aminoacid_change:
        queryset = queryset.filter(
            variant__annotations__aminoacid_change__iexact=aminoacid_change
        )

    created_at_from = filters.get("created_at_from")
    if created_at_from:
        queryset = queryset.filter(generated_at__gte=created_at_from)

    created_at_to = filters.get("created_at_to")
    if created_at_to:
        queryset = queryset.filter(generated_at__lte=created_at_to)

    return queryset.distinct()


def _filter_sample_metadata(sample_queryset, property_name, value_query):
    metadata_queryset = models.MetadataValues.objects.filter(
        sample_id=OuterRef("pk"),
        schema_property__property__iexact=property_name,
    ).filter(value_query)
    return sample_queryset.filter(Exists(metadata_queryset))


def _sample_metadata_map(sample_ids, property_names):
    if not sample_ids:
        return {}
    rows = models.MetadataValues.objects.filter(
        sample_id__in=sample_ids,
        schema_property__property__in=property_names,
    ).values("sample_id", "schema_property__property", "value")
    result = {}
    for row in rows:
        sample_data = result.setdefault(row["sample_id"], {})
        sample_data.setdefault(row["schema_property__property"], row["value"])
    return result


def _first_annotation(variant_obj):
    annotations = list(getattr(variant_obj, "annotations").all())
    if not annotations:
        return None
    return annotations[0]


def _variant_hgvs(variant_obj):
    return f"g.{variant_obj.position}{variant_obj.reference}>{variant_obj.alternate}"


def _label_value_rows(rows):
    result = []
    for row in rows:
        label = row["label"]
        if label is None or label == "":
            continue
        result.append({"label": str(label), "value": row["value"]})
    return result
