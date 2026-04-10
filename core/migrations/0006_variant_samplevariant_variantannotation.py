# Generated for normalized variant ingestion.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_sample_fingerprint"),
    ]

    operations = [
        migrations.CreateModel(
            name="Variant",
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
                ("chrom", models.CharField(db_index=True, max_length=80)),
                ("position", models.PositiveIntegerField(db_index=True)),
                ("reference", models.CharField(max_length=255)),
                ("alternate", models.CharField(max_length=255)),
                (
                    "variant_type",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=40
                    ),
                ),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "core_variant",
            },
        ),
        migrations.CreateModel(
            name="VariantAnnotation",
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
                (
                    "gene_region",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=120
                    ),
                ),
                (
                    "effect",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=150
                    ),
                ),
                (
                    "functional_class",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=100
                    ),
                ),
                (
                    "locus_name",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=120
                    ),
                ),
                (
                    "locus_id",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=120
                    ),
                ),
                (
                    "aminoacid_change",
                    models.CharField(
                        blank=True, db_index=True, default="", max_length=120
                    ),
                ),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                (
                    "variant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="annotations",
                        to="core.variant",
                    ),
                ),
            ],
            options={
                "db_table": "core_variant_annotation",
            },
        ),
        migrations.CreateModel(
            name="SampleVariant",
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
                ("depth", models.PositiveIntegerField(blank=True, null=True)),
                ("allele_frequency", models.FloatField(blank=True, null=True)),
                ("analysis_date", models.DateField()),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                (
                    "sample",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="variant_observations",
                        to="core.sample",
                    ),
                ),
                (
                    "variant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sample_observations",
                        to="core.variant",
                    ),
                ),
            ],
            options={
                "db_table": "core_sample_variant",
            },
        ),
        migrations.AddConstraint(
            model_name="variant",
            constraint=models.UniqueConstraint(
                fields=("chrom", "position", "reference", "alternate"),
                name="uniq_variant_locus_ref_alt",
            ),
        ),
        migrations.AddIndex(
            model_name="variant",
            index=models.Index(
                fields=["position", "reference", "alternate"],
                name="idx_variant_pos_ref_alt",
            ),
        ),
        migrations.AddIndex(
            model_name="variant",
            index=models.Index(
                fields=["chrom", "position"], name="idx_variant_chrom_pos"
            ),
        ),
        migrations.AddConstraint(
            model_name="variantannotation",
            constraint=models.UniqueConstraint(
                fields=("variant", "gene_region", "effect", "aminoacid_change"),
                name="uniq_variant_annotation_core",
            ),
        ),
        migrations.AddIndex(
            model_name="variantannotation",
            index=models.Index(
                fields=["locus_name", "locus_id"],
                name="idx_va_locus_name_id",
            ),
        ),
        migrations.AddIndex(
            model_name="variantannotation",
            index=models.Index(
                fields=["gene_region", "effect"],
                name="idx_va_region_effect",
            ),
        ),
        migrations.AddConstraint(
            model_name="samplevariant",
            constraint=models.UniqueConstraint(
                fields=("sample", "variant", "analysis_date"),
                name="uniq_sample_variant_analysis",
            ),
        ),
        migrations.AddIndex(
            model_name="samplevariant",
            index=models.Index(
                fields=["sample", "analysis_date"],
                name="idx_sv_sample_analysis",
            ),
        ),
        migrations.AddIndex(
            model_name="samplevariant",
            index=models.Index(
                fields=["variant", "analysis_date"],
                name="idx_sv_variant_analysis",
            ),
        ),
    ]
