# Generic imports
from django.urls import path

# Local imports
import core.api.v1.views

app_name = "pathocore_api"

# TODO: keep this in sync with versioned API structure
urlpatterns = [
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
