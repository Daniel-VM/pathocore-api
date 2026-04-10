from django.core.management.base import BaseCommand, CommandError

from core.api.services import databrowser


class Command(BaseCommand):
    help = "Refresh global precomputed databrowser summaries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--summary",
            action="append",
            choices=databrowser.CACHEABLE_SUMMARIES,
            help=(
                "Summary to refresh. Can be provided multiple times. "
                "Defaults to all cacheable summaries."
            ),
        )

    def handle(self, *args, **options):
        summary_names = options.get("summary")
        try:
            refreshed = databrowser.refresh_databrowser_summary_cache(summary_names)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        for summary_name, result in refreshed.items():
            generated_at = result["generated_at"].isoformat()
            self.stdout.write(
                self.style.SUCCESS(
                    "Refreshed %s (%s) at %s"
                    % (summary_name, result["scope_key"], generated_at)
                )
            )
