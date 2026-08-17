import gzip
import re
from pathlib import Path

import MySQLdb
from MySQLdb.constants import CLIENT
from django.core.management.base import BaseCommand, CommandError
from django.db import connections


UNSAFE_SQL = re.compile(
    rb"\b(?:CREATE|ALTER|DROP|TRUNCATE)\s+(?:TABLE|DATABASE|SCHEMA)\b"
    rb"|\bdjango_migrations\b",
    re.IGNORECASE,
)


class Command(BaseCommand):
    help = "Import a reviewed data-only .sql or .sql.gz seed into the configured DB."

    def add_arguments(self, parser):
        parser.add_argument("seed_path")

    def handle(self, *args, **options):
        seed_path = Path(options["seed_path"])
        if not seed_path.is_file():
            raise CommandError(f"SQL seed not found: {seed_path}")
        if seed_path.name.endswith(".sql.gz"):
            with gzip.open(seed_path, "rb") as seed_file:
                sql = seed_file.read()
        elif seed_path.name.endswith(".sql"):
            sql = seed_path.read_bytes()
        else:
            raise CommandError("SQL seed must use .sql or .sql.gz")
        if not sql.strip():
            raise CommandError("SQL seed is empty")
        if UNSAFE_SQL.search(sql):
            raise CommandError(
                "SQL seed must be data-only and must not modify schema or "
                "django_migrations"
            )

        connection_params = connections["default"].get_connection_params()
        connection_params["client_flag"] = (
            connection_params.get("client_flag", 0) | CLIENT.MULTI_STATEMENTS
        )
        connection = MySQLdb.connect(**connection_params)
        try:
            connection.query(sql)
            while connection.next_result() == 0:
                pass
            connection.commit()
        except MySQLdb.Error as exc:
            connection.rollback()
            raise CommandError(f"SQL seed import failed: {exc}") from exc
        finally:
            connection.close()

        self.stdout.write(self.style.SUCCESS(f"Imported SQL seed: {seed_path}"))
