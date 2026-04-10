import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core import models
from core.api.services import sample_ingestion

TAIL_PATTERN = r"[A-Z]{3}-[0-9]{4}"


def _sample_unique_id_regex():
    initial_value = sample_ingestion.get_initial_sample_unique_id()
    prefix = initial_value[: -len("AAA-0001")]
    return rf"^{re.escape(prefix)}{TAIL_PATTERN}$"


class Command(BaseCommand):
    help = (
        "Replace legacy sample_unique_id hash values with sequential matricula-like "
        "IDs while preserving the old value in fingerprint."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview how many legacy sample IDs would be replaced.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="bulk_update batch size. Default: 1000",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        if batch_size < 1:
            raise CommandError("batch-size must be >= 1")

        regex = _sample_unique_id_regex()
        legacy_queryset = models.Sample.objects.exclude(
            sample_unique_id__regex=regex
        ).order_by("id")
        legacy_count = legacy_queryset.count()
        total_count = models.Sample.objects.count()

        sequence_obj = models.SampleIdSequence.objects.filter(
            sequence_name="sample_unique_id"
        ).last()
        sequence_last = sequence_obj.last_value if sequence_obj else ""
        highest_existing = (
            models.Sample.objects.filter(sample_unique_id__regex=regex)
            .order_by("-sample_unique_id")
            .values_list("sample_unique_id", flat=True)
            .first()
            or ""
        )
        current_last = max(
            [value for value in [sequence_last, highest_existing] if value],
            default="",
        )

        self.stdout.write(
            "Detected %s legacy sample_unique_id values out of %s samples"
            % (legacy_count, total_count)
        )
        self.stdout.write(
            "Current sequence baseline: %s"
            % (current_last or "<empty, will start at initial value>")
        )

        if legacy_count == 0:
            self.stdout.write(self.style.SUCCESS("No legacy sample IDs found"))
            return

        preview = []
        preview_last = current_last
        for sample_obj in legacy_queryset[:10]:
            next_value = (
                sample_ingestion.increase_sample_unique_id(preview_last)
                if preview_last
                else sample_ingestion.get_initial_sample_unique_id()
            )
            preview.append((sample_obj.sample_unique_id, next_value))
            preview_last = next_value

        for old_value, new_value in preview:
            self.stdout.write(f"Preview: {old_value} -> {new_value}")

        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry run completed"))
            return

        with transaction.atomic():
            sequence_obj = (
                models.SampleIdSequence.objects.select_for_update()
                .filter(sequence_name="sample_unique_id")
                .last()
            )
            if sequence_obj is None:
                sequence_obj = models.SampleIdSequence.objects.create(
                    sequence_name="sample_unique_id",
                    last_value="",
                )

            highest_existing = (
                models.Sample.objects.select_for_update()
                .filter(sample_unique_id__regex=regex)
                .order_by("-sample_unique_id")
                .values_list("sample_unique_id", flat=True)
                .first()
                or ""
            )
            current_last = max(
                [
                    value
                    for value in [sequence_obj.last_value, highest_existing]
                    if value
                ],
                default="",
            )

            pending_updates = []
            updated_count = 0
            for sample_obj in (
                models.Sample.objects.select_for_update()
                .exclude(sample_unique_id__regex=regex)
                .order_by("id")
                .iterator(chunk_size=batch_size)
            ):
                next_value = (
                    sample_ingestion.increase_sample_unique_id(current_last)
                    if current_last
                    else sample_ingestion.get_initial_sample_unique_id()
                )
                if not sample_obj.fingerprint:
                    sample_obj.fingerprint = sample_obj.sample_unique_id
                sample_obj.sample_unique_id = next_value
                pending_updates.append(sample_obj)
                current_last = next_value
                updated_count += 1

                if len(pending_updates) >= batch_size:
                    models.Sample.objects.bulk_update(
                        pending_updates,
                        ["sample_unique_id", "fingerprint"],
                        batch_size=batch_size,
                    )
                    self.stdout.write(
                        "Updated %s/%s legacy sample IDs"
                        % (updated_count, legacy_count)
                    )
                    pending_updates = []

            if pending_updates:
                models.Sample.objects.bulk_update(
                    pending_updates,
                    ["sample_unique_id", "fingerprint"],
                    batch_size=batch_size,
                )
                self.stdout.write(
                    "Updated %s/%s legacy sample IDs" % (updated_count, legacy_count)
                )

            sequence_obj.last_value = current_last
            sequence_obj.save(update_fields=["last_value"])

        self.stdout.write(
            self.style.SUCCESS(
                "Backfill finished: %s samples updated, sequence now at %s"
                % (legacy_count, current_last)
            )
        )
