# Generated manually during cleanup of unused legacy metadata models.

from django.db import migrations


def drop_unused_metadata_tables(apps, schema_editor):
    existing_tables = set(schema_editor.connection.introspection.table_names())
    for table_name in ("core_metadata_values_file", "core_metadata_visualization"):
        if table_name in existing_tables:
            schema_editor.execute(
                "DROP TABLE {table}".format(
                    table=schema_editor.quote_name(table_name),
                )
            )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_alter_schema_user_name_nullable"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    drop_unused_metadata_tables,
                    migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.DeleteModel(
                    name="BioinfoMetadataFile",
                ),
                migrations.DeleteModel(
                    name="MetadataVisualization",
                ),
            ],
        ),
    ]
