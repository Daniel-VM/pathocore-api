# Generic imports
from django.urls import path

# Local imports
import core.api.v1.views

app_name = "pathocore_api"

# TODO: keep this in sync with versioned API structure
urlpatterns = [
    path("schema", core.api.v1.views.schema, name="schema"),
    path(
        "schema/project_name=<str:project_name>",
        core.api.v1.views.schema_create,
        name="schema_by_project_name",
    ),
    path(
        "schema/<str:schema_name>/<str:schema_version>",
        core.api.v1.views.schema_detail,
        name="schema_detail",
    ),
    path("samples", core.api.v1.views.samples, name="samples"),
    path(
        "samples/metadata",
        core.api.v1.views.sample_metadata_property_view,
        name="sample_metadata_property",
    ),
    path(
        "samples/metadata/search",
        core.api.v1.views.sample_metadata_search_view,
        name="sample_metadata_search",
    ),
    path(
        "samples/history",
        core.api.v1.views.sample_history_view,
        name="sample_history",
    ),
    path(
        "samples/<str:sample_unique_id>/history",
        core.api.v1.views.sample_history_detail_view,
        name="sample_history_detail",
    ),
    path(
        "samples/<str:sample_unique_id>",
        core.api.v1.views.sample_detail_view,
        name="sample_detail",
    ),
    path(
        "samples/<str:sample_unique_id>/metadata",
        core.api.v1.views.sample_metadata_view,
        name="sample_metadata",
    ),
]
