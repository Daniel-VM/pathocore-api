import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Classification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('classification_name', models.CharField(max_length=150)),
                ('generated_at', models.DateTimeField(auto_now_add=True, null=True)),
            ],
            options={
                'db_table': 'core_metadata_classification',
            },
        ),
        migrations.CreateModel(
            name='ConfigSetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('configuration_name', models.CharField(max_length=80)),
                ('configuration_value', models.CharField(blank=True, max_length=255, null=True)),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'core_config_setting',
            },
        ),
        migrations.CreateModel(
            name='ErrorName',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('error_name', models.CharField(max_length=100)),
                ('error_code', models.CharField(max_length=10)),
                ('error_text', models.CharField(blank=True, max_length=100, null=True)),
            ],
            options={
                'db_table': 'core_error_name',
            },
        ),
        migrations.CreateModel(
            name='PublicDatabaseType',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_type_name', models.CharField(max_length=30)),
                ('public_type_display', models.CharField(max_length=50)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'core_public_database_type',
            },
        ),
        migrations.CreateModel(
            name='SampleIdSequence',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sequence_name', models.CharField(max_length=40, unique=True)),
                ('last_value', models.CharField(blank=True, default='', max_length=12)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'core_sample_id_sequence',
            },
        ),
        migrations.CreateModel(
            name='SampleState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('state', models.CharField(max_length=80)),
                ('display_string', models.CharField(blank=True, max_length=80, null=True)),
                ('description', models.CharField(blank=True, max_length=255, null=True)),
            ],
            options={
                'db_table': 'core_sample_state',
            },
        ),
        migrations.CreateModel(
            name='DatabrowserSummaryCache',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('summary_name', models.CharField(max_length=80)),
                ('scope_key', models.CharField(default='global', max_length=80)),
                ('filters_hash', models.CharField(default='no-filters', max_length=64)),
                ('filters', models.JSONField(blank=True, default=dict)),
                ('payload', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('generated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'core_databrowser_summary_cache',
                'indexes': [models.Index(fields=['summary_name', 'scope_key'], name='idx_dbs_cache_summary_scope'), models.Index(fields=['generated_at'], name='idx_dbs_cache_generated')],
                'constraints': [models.UniqueConstraint(fields=('summary_name', 'scope_key', 'filters_hash'), name='uniq_databrowser_summary_cache')],
            },
        ),
        migrations.CreateModel(
            name='Profile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('laboratory', models.CharField(blank=True, max_length=60, null=True)),
                ('code_id', models.CharField(blank=True, max_length=40, null=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'core_profile',
            },
        ),
        migrations.CreateModel(
            name='PublicDatabaseFields',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('property_name', models.CharField(max_length=60)),
                ('label_name', models.CharField(max_length=80)),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
                ('database_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='core.publicdatabasetype')),
            ],
            options={
                'db_table': 'core_public_database_field',
            },
        ),
        migrations.CreateModel(
            name='Sample',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fingerprint', models.CharField(blank=True, db_index=True, max_length=24, null=True)),
                ('sample_unique_id', models.CharField(db_index=True, max_length=12)),
                ('microbiology_lab_sample_id', models.CharField(blank=True, max_length=80, null=True)),
                ('collecting_lab_sample_id', models.CharField(blank=True, max_length=80, null=True)),
                ('collecting_lab_isolate_id', models.CharField(blank=True, max_length=80, null=True)),
                ('sequencing_sample_id', models.CharField(blank=True, max_length=80, null=True)),
                ('sequencing_isolate_id', models.CharField(blank=True, max_length=80, null=True)),
                ('submitting_lab_sample_id', models.CharField(blank=True, max_length=80, null=True)),
                ('submitting_lab_isolate_id', models.CharField(blank=True, max_length=80, null=True)),
                ('collecting_institution', models.CharField(blank=True, max_length=120, null=True)),
                ('sequence_file_R1_fastq', models.CharField(blank=True, max_length=80, null=True)),
                ('sequence_file_R2_fastq', models.CharField(blank=True, max_length=80, null=True)),
                ('sequence_file_R1_md5', models.CharField(blank=True, max_length=80, null=True)),
                ('sequence_file_R2_md5', models.CharField(blank=True, max_length=80, null=True)),
                ('r1_fastq_filepath', models.CharField(blank=True, max_length=120, null=True)),
                ('r2_fastq_filepath', models.CharField(blank=True, max_length=120, null=True)),
                ('sequencing_date', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'core_sample',
            },
        ),
        migrations.CreateModel(
            name='PublicDatabaseValues',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('value', models.CharField(blank=True, max_length=240, null=True)),
                ('generated_at', models.DateTimeField(auto_now_add=True, null=True)),
                ('public_database_fieldID', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.publicdatabasefields')),
                ('sampleID', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='core.sample')),
            ],
            options={
                'db_table': 'core_public_database_value',
            },
        ),
        migrations.CreateModel(
            name='MetadataGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('group_index', models.IntegerField()),
                ('created_at', models.DateTimeField(blank=True)),
                ('sample', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='metadata_groups', to='core.sample')),
            ],
            options={
                'db_table': 'core_metadata_group',
            },
        ),
        migrations.CreateModel(
            name='SampleStateHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_current', models.BooleanField(default=True)),
                ('changed_at', models.DateTimeField(auto_now_add=True)),
                ('error_name', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.errorname')),
                ('sample', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.sample')),
                ('state', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.samplestate')),
            ],
            options={
                'db_table': 'core_sample_state_history',
            },
        ),
        migrations.CreateModel(
            name='Schema',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file_name', models.FileField(upload_to='schemas')),
                ('schema_name', models.CharField(max_length=40)),
                ('schema_version', models.CharField(max_length=10)),
                ('schema_in_use', models.BooleanField(default=True)),
                ('schema_default', models.BooleanField(default=False)),
                ('schema_app_name', models.CharField(blank=True, db_index=True, max_length=40, null=True)),
                ('generated_at', models.DateTimeField(auto_now_add=True, null=True)),
                ('user_name', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'core_metadata_schema',
            },
        ),
        migrations.AddField(
            model_name='sample',
            name='schema_obj',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='core.schema'),
        ),
        migrations.AddField(
            model_name='publicdatabasefields',
            name='schemaID',
            field=models.ManyToManyField(to='core.schema'),
        ),
        migrations.CreateModel(
            name='SchemaProperties',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('property', models.CharField(db_index=True, max_length=50)),
                ('examples', models.CharField(blank=True, max_length=250, null=True)),
                ('ontology', models.CharField(blank=True, max_length=40, null=True)),
                ('type', models.CharField(max_length=20)),
                ('format', models.CharField(blank=True, max_length=20, null=True)),
                ('description', models.CharField(blank=True, max_length=500, null=True)),
                ('label', models.CharField(blank=True, max_length=200, null=True)),
                ('required', models.BooleanField(default=False)),
                ('options', models.BooleanField(default=False)),
                ('fill_mode', models.CharField(blank=True, max_length=50, null=True)),
                ('classificationID', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='core.classification')),
                ('schemaID', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.schema')),
            ],
            options={
                'db_table': 'core_metadata_schema_properties',
            },
        ),
        migrations.CreateModel(
            name='PropertyOptions',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enum', models.CharField(blank=True, max_length=250, null=True)),
                ('ontology', models.CharField(blank=True, max_length=40, null=True)),
                ('propertyID', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='core.schemaproperties')),
            ],
            options={
                'db_table': 'core_metadata_schema_property_option',
            },
        ),
        migrations.CreateModel(
            name='MetadataValues',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('value', models.CharField(blank=True, max_length=240, null=True)),
                ('generated_at', models.DateTimeField(auto_now_add=True, null=True)),
                ('analysis_date', models.DateField()),
                ('group', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='metadata_values', to='core.metadatagroup')),
                ('sample', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='metadata_values', to='core.sample')),
                ('schema_property', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='metadata_values', to='core.schemaproperties')),
            ],
            options={
                'db_table': 'core_metadata_values',
            },
        ),
        migrations.AddField(
            model_name='metadatagroup',
            name='group_property',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='metadata_groups', to='core.schemaproperties'),
        ),
        migrations.CreateModel(
            name='TemporalSampleStorage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sample_name', models.CharField(max_length=100, null=True)),
                ('field', models.CharField(max_length=100, null=True)),
                ('value', models.CharField(max_length=100, null=True)),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'core_temporal_sample_storage',
            },
        ),
        migrations.CreateModel(
            name='Variant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chrom', models.CharField(db_index=True, max_length=80)),
                ('position', models.PositiveIntegerField(db_index=True)),
                ('reference', models.CharField(max_length=255)),
                ('alternate', models.CharField(max_length=255)),
                ('variant_type', models.CharField(blank=True, db_index=True, default='', max_length=40)),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'core_variant',
                'indexes': [models.Index(fields=['position', 'reference', 'alternate'], name='idx_variant_pos_ref_alt'), models.Index(fields=['chrom', 'position'], name='idx_variant_chrom_pos')],
                'constraints': [models.UniqueConstraint(fields=('chrom', 'position', 'reference', 'alternate'), name='uniq_variant_locus_ref_alt')],
            },
        ),
        migrations.CreateModel(
            name='SampleVariant',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('depth', models.PositiveIntegerField(blank=True, null=True)),
                ('allele_frequency', models.FloatField(blank=True, null=True)),
                ('analysis_date', models.DateField()),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
                ('sample', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='variant_observations', to='core.sample')),
                ('variant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sample_observations', to='core.variant')),
            ],
            options={
                'db_table': 'core_sample_variant',
            },
        ),
        migrations.CreateModel(
            name='VariantAnnotation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('gene_region', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('effect', models.CharField(blank=True, db_index=True, default='', max_length=150)),
                ('functional_class', models.CharField(blank=True, db_index=True, default='', max_length=100)),
                ('locus_name', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('locus_id', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('aminoacid_change', models.CharField(blank=True, db_index=True, default='', max_length=120)),
                ('generated_at', models.DateTimeField(auto_now_add=True)),
                ('variant', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='annotations', to='core.variant')),
            ],
            options={
                'db_table': 'core_variant_annotation',
            },
        ),
        migrations.CreateModel(
            name='AccessRequest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('username', models.CharField(db_index=True, max_length=150)),
                ('email', models.EmailField(db_index=True, max_length=254)),
                ('first_name', models.CharField(max_length=150)),
                ('last_name', models.CharField(max_length=150)),
                ('requested_use_case', models.CharField(db_index=True, max_length=80)),
                ('requested_lab', models.CharField(blank=True, max_length=80, null=True)),
                ('requested_role', models.CharField(choices=[('view', 'View'), ('admin', 'Admin')], default='view', max_length=20)),
                ('message', models.TextField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected'), ('revoked', 'Revoked')], db_index=True, default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('reviewed_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('reviewed_by_identity', models.CharField(blank=True, max_length=255, null=True)),
                ('review_note', models.TextField(blank=True, null=True)),
                ('approved_group', models.CharField(blank=True, max_length=255, null=True)),
                ('keycloak_user_id', models.CharField(blank=True, max_length=80, null=True)),
                ('reviewed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_access_requests', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'core_access_request',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['status', 'created_at'], name='core_access_status_created_idx'), models.Index(fields=['requested_use_case', 'requested_lab'], name='core_access_project_lab_idx')],
            },
        ),
        migrations.AddIndex(
            model_name='schema',
            index=models.Index(fields=['schema_app_name', 'schema_name', 'schema_version'], name='idx_schema_project_name_ver'),
        ),
        migrations.AddIndex(
            model_name='sample',
            index=models.Index(fields=['schema_obj', 'created_at'], name='idx_sample_schema_created'),
        ),
        migrations.AddIndex(
            model_name='sample',
            index=models.Index(fields=['created_at'], name='idx_sample_created_at'),
        ),
        migrations.AddIndex(
            model_name='schemaproperties',
            index=models.Index(fields=['schemaID', 'property'], name='idx_schema_prop_schema_prop'),
        ),
        migrations.AddIndex(
            model_name='metadatavalues',
            index=models.Index(fields=['sample', 'schema_property'], name='core_metada_sample__83c2cc_idx'),
        ),
        migrations.AddIndex(
            model_name='metadatavalues',
            index=models.Index(fields=['value', 'sample'], name='core_metada_value_8ad8c6_idx'),
        ),
        migrations.AddIndex(
            model_name='metadatavalues',
            index=models.Index(fields=['schema_property', 'value', 'sample'], name='core_metada_schema__6d30fa_idx'),
        ),
        migrations.AddConstraint(
            model_name='metadatavalues',
            constraint=models.UniqueConstraint(fields=('group', 'schema_property'), name='uniq_metadata_values_group_schema_property'),
        ),
        migrations.AddIndex(
            model_name='metadatagroup',
            index=models.Index(fields=['sample', 'group_property'], name='core_metada_sample__fc2c10_idx'),
        ),
        migrations.AddConstraint(
            model_name='metadatagroup',
            constraint=models.UniqueConstraint(fields=('sample', 'group_property', 'group_index'), name='uniq_metadata_group_sample_prop_index'),
        ),
        migrations.AddIndex(
            model_name='samplevariant',
            index=models.Index(fields=['sample', 'analysis_date'], name='idx_sv_sample_analysis'),
        ),
        migrations.AddIndex(
            model_name='samplevariant',
            index=models.Index(fields=['variant', 'analysis_date'], name='idx_sv_variant_analysis'),
        ),
        migrations.AddConstraint(
            model_name='samplevariant',
            constraint=models.UniqueConstraint(fields=('sample', 'variant', 'analysis_date'), name='uniq_sample_variant_analysis'),
        ),
        migrations.AddIndex(
            model_name='variantannotation',
            index=models.Index(fields=['locus_name', 'locus_id'], name='idx_va_locus_name_id'),
        ),
        migrations.AddIndex(
            model_name='variantannotation',
            index=models.Index(fields=['gene_region', 'effect'], name='idx_va_region_effect'),
        ),
        migrations.AddConstraint(
            model_name='variantannotation',
            constraint=models.UniqueConstraint(fields=('variant', 'gene_region', 'effect', 'aminoacid_change'), name='uniq_variant_annotation_core'),
        ),
    ]
