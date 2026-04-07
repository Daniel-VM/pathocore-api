from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_variant_samplevariant_variantannotation"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="schema",
            index=models.Index(
                fields=["schema_app_name", "schema_name", "schema_version"],
                name="idx_schema_project_name_ver",
            ),
        ),
        migrations.AddIndex(
            model_name="schemaproperties",
            index=models.Index(
                fields=["schemaID", "property"],
                name="idx_schema_prop_schema_prop",
            ),
        ),
        migrations.AddIndex(
            model_name="sample",
            index=models.Index(
                fields=["schema_obj", "created_at"],
                name="idx_sample_schema_created",
            ),
        ),
        migrations.AddIndex(
            model_name="sample",
            index=models.Index(fields=["created_at"], name="idx_sample_created_at"),
        ),
    ]
