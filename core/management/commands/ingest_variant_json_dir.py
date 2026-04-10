import json
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core import models
from core.api.services import variant_ingestion


class Command(BaseCommand):
    help = "Ingest variant JSON files from a directory or file list."

    def add_arguments(self, parser):
        parser.add_argument(
            "paths",
            nargs="+",
            help="Variant JSON file(s) or directories containing JSON files.",
        )
        parser.add_argument(
            "--pattern",
            default="*.json",
            help="Glob pattern used when a path is a directory. Default: *.json",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=variant_ingestion.DEFAULT_CHUNK_SIZE,
            help="Bulk DB chunk size passed to the variant ingestion service.",
        )
        parser.add_argument(
            "--limit-files",
            type=int,
            help="Process only the first N files. Useful for smoke tests.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and resolve samples, but do not write variants.",
        )
        parser.add_argument(
            "--fail-fast",
            action="store_true",
            help="Stop at the first validation or ingestion error.",
        )
        parser.add_argument(
            "--error-log",
            help="Optional TSV file where skipped records/errors are appended.",
        )

    def handle(self, *args, **options):
        chunk_size = options["chunk_size"]
        if chunk_size < 1 or chunk_size > 5000:
            raise CommandError("chunk-size must be between 1 and 5000")

        files = _resolve_files(options["paths"], options["pattern"])
        if options["limit_files"]:
            files = files[: options["limit_files"]]
        if not files:
            raise CommandError("No JSON files found")

        sample_lookup, samples_by_pk = _build_sample_lookup()
        self.stdout.write(
            "Loaded %s sample identifiers for %s samples"
            % (len(sample_lookup), len(samples_by_pk))
        )

        error_log = None
        if options.get("error_log"):
            error_log = open(options["error_log"], "a", encoding="utf-8")
            error_log.write("file\tsample_id\tcandidates\terror\n")

        totals = defaultdict(int)
        try:
            for path in files:
                file_totals = self._process_file(
                    path, options, error_log, sample_lookup, samples_by_pk
                )
                for key, value in file_totals.items():
                    totals[key] += value
        finally:
            if error_log is not None:
                error_log.close()

        self.stdout.write(
            self.style.SUCCESS(
                "Variant JSON ingest finished: files=%s records=%s valid_records=%s "
                "skipped_records=%s groups=%s variants_received=%s "
                "sample_variants_stored=%s sample_variants_replaced=%s"
                % (
                    totals["files"],
                    totals["records"],
                    totals["valid_records"],
                    totals["skipped_records"],
                    totals["groups"],
                    totals["variants_received"],
                    totals["sample_variants_stored"],
                    totals["sample_variants_replaced"],
                )
            )
        )

    def _process_file(self, path, options, error_log, sample_lookup, samples_by_pk):
        self.stdout.write("Processing %s" % path)
        records = _load_records(path)
        grouped_records = defaultdict(list)
        file_totals = defaultdict(int)
        file_totals["files"] = 1

        for record in records:
            file_totals["records"] += 1
            try:
                normalized = variant_ingestion._normalize_sample_payload(record)
                sample_pk = _resolve_sample_pk_with_lookup(
                    normalized["sample_candidates"], sample_lookup
                )
                analysis_date = variant_ingestion._parse_required_date(
                    normalized["analysis_date"]
                )
            except ValueError as exc:
                file_totals["skipped_records"] += 1
                _write_error(error_log, path, record, str(exc))
                if options["fail_fast"]:
                    raise CommandError("%s: %s" % (path, exc)) from exc
                continue

            file_totals["valid_records"] += 1
            grouped_records[(sample_pk, analysis_date)].append(record)

        file_totals["groups"] = len(grouped_records)
        if options["dry_run"]:
            file_totals["variants_received"] = sum(
                len(record.get("variants") or [])
                for group in grouped_records.values()
                for record in group
            )
            self.stdout.write(
                "Dry run %s: records=%s valid=%s skipped=%s groups=%s variants=%s"
                % (
                    path.name,
                    file_totals["records"],
                    file_totals["valid_records"],
                    file_totals["skipped_records"],
                    file_totals["groups"],
                    file_totals["variants_received"],
                )
            )
            return file_totals

        for (sample_pk, analysis_date), group_records in grouped_records.items():
            sample_obj = samples_by_pk[sample_pk]
            raw_variants = [
                variant
                for record in group_records
                for variant in (record.get("variants") or [])
            ]
            try:
                result, variant_keys, annotation_keys = (
                    variant_ingestion._ingest_sample_variant_group(
                        sample_obj,
                        analysis_date,
                        raw_variants,
                        chunk_size=options["chunk_size"],
                    )
                )
            except ValueError as exc:
                file_totals["skipped_records"] += len(group_records)
                for record in group_records:
                    _write_error(error_log, path, record, str(exc))
                if options["fail_fast"]:
                    raise CommandError("%s: %s" % (path, exc)) from exc
                continue

            file_totals["distinct_variants_seen"] += len(variant_keys)
            file_totals["annotations_seen"] += len(annotation_keys)
            for key in (
                "variants_received",
                "sample_variants_stored",
                "sample_variants_replaced",
            ):
                file_totals[key] += result.get(key, 0)

        self.stdout.write(
            "Stored %s: records=%s valid=%s skipped=%s groups=%s variants=%s stored=%s"
            % (
                path.name,
                file_totals["records"],
                file_totals["valid_records"],
                file_totals["skipped_records"],
                file_totals["groups"],
                file_totals["variants_received"],
                file_totals["sample_variants_stored"],
            )
        )
        return file_totals


def _resolve_files(paths, pattern):
    files = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if path.is_dir():
            files.extend(sorted(path.glob(pattern)))
        elif path.is_file():
            files.append(path)
        else:
            raise CommandError("Path not found: %s" % raw_path)
    return sorted(set(files), key=lambda item: item.name)


def _build_sample_lookup():
    sample_lookup = {}
    samples_by_pk = {}
    sample_rows = models.Sample.objects.all()
    for sample_obj in sample_rows:
        samples_by_pk[sample_obj.pk] = sample_obj
        for value in (
            sample_obj.sample_unique_id,
            sample_obj.sequencing_sample_id,
            sample_obj.microbiology_lab_sample_id,
            sample_obj.collecting_lab_sample_id,
            sample_obj.submitting_lab_sample_id,
        ):
            _add_lookup_value(sample_lookup, value, sample_obj.pk)

    metadata_rows = models.MetadataValues.objects.filter(
        schema_property__property__in=[
            "unique_sample_id",
            "isolate_sample_id",
            "sample_id",
        ]
    ).values_list("value", "sample_id")
    for value, sample_pk in metadata_rows:
        _add_lookup_value(sample_lookup, value, sample_pk)

    return sample_lookup, samples_by_pk


def _add_lookup_value(sample_lookup, value, sample_pk):
    value = variant_ingestion._clean_string(value)
    if value:
        sample_lookup[value] = sample_pk


def _resolve_sample_pk_with_lookup(sample_candidates, sample_lookup):
    for sample_identifier in sample_candidates:
        sample_pk = sample_lookup.get(sample_identifier)
        if sample_pk is not None:
            return sample_pk
    raise ValueError(f"Sample not found: {sample_candidates[0]}")


def _load_records(path):
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("records"), list):
        return payload["records"]
    if isinstance(payload, dict):
        return [payload]
    raise CommandError("Unsupported JSON root in %s" % path)


def _write_error(error_log, path, record, error):
    if error_log is None:
        return
    sample_id = (
        record.get("sample_id")
        or record.get("sample_unique_id")
        or record.get("sample_name")
        or record.get("sample")
        or ""
    )
    candidates = []
    for row in record.get("variants") or []:
        if isinstance(row, dict) and row.get("sample") not in candidates:
            candidates.append(row.get("sample"))
    error_log.write(
        "%s\t%s\t%s\t%s\n"
        % (
            path,
            sample_id,
            ",".join(str(item) for item in candidates if item),
            error,
        )
    )
