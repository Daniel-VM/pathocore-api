from django.core.management.base import BaseCommand, CommandError

from core.api.services import use_case_data


class Command(BaseCommand):
    help = "Refresh precomputed use-case data summaries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--project",
            action="append",
            help=(
                "Use-case/project name to refresh. Can be provided multiple times. "
                "Defaults to all projects with registered schemas."
            ),
        )

    def handle(self, *args, **options):
        project_names = options.get("project")
        try:
            refreshed = use_case_data.refresh_use_case_data_summary_cache(
                project_names
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        if not refreshed:
            self.stdout.write(self.style.WARNING("No use-case projects to refresh"))
            return

        for project_name, result in refreshed.items():
            generated_at = result["generated_at"].isoformat()
            self.stdout.write(
                self.style.SUCCESS(
                    "Refreshed %s (%s) at %s"
                    % (project_name, result["scope_key"], generated_at)
                )
            )
