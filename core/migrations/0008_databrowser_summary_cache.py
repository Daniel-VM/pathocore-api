from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_databrowser_perf_indexes"),
    ]

    operations = [
        migrations.CreateModel(
            name="DatabrowserSummaryCache",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("summary_name", models.CharField(max_length=80)),
                ("scope_key", models.CharField(default="global", max_length=80)),
                (
                    "filters_hash",
                    models.CharField(default="no-filters", max_length=64),
                ),
                ("filters", models.JSONField(blank=True, default=dict)),
                ("payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("generated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "core_databrowser_summary_cache",
            },
        ),
        migrations.AddIndex(
            model_name="databrowsersummarycache",
            index=models.Index(
                fields=["summary_name", "scope_key"],
                name="idx_dbs_cache_summary_scope",
            ),
        ),
        migrations.AddIndex(
            model_name="databrowsersummarycache",
            index=models.Index(
                fields=["generated_at"],
                name="idx_dbs_cache_generated",
            ),
        ),
        migrations.AddConstraint(
            model_name="databrowsersummarycache",
            constraint=models.UniqueConstraint(
                fields=("summary_name", "scope_key", "filters_hash"),
                name="uniq_databrowser_summary_cache",
            ),
        ),
    ]
