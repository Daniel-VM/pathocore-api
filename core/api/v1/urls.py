# Generic imports
from django.urls import path

# Local imports
import core.api.v1.views

app_name = "pathocore_api"

# TODO: keep this in sync with versioned API structure
urlpatterns = [
    path("auth/me", core.api.v1.views.auth_me_view, name="auth_me"),
    path(
        "access-requests",
        core.api.v1.views.access_requests_view,
        name="access_requests",
    ),
    path(
        "access-requests/catalog",
        core.api.v1.views.access_request_catalog_view,
        name="access_request_catalog",
    ),
    path(
        "access-requests/<int:request_id>/approve",
        core.api.v1.views.access_request_approve_view,
        name="access_request_approve",
    ),
    path(
        "access-requests/<int:request_id>/reject",
        core.api.v1.views.access_request_reject_view,
        name="access_request_reject",
    ),
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
    path(
        "databrowser/overview-summary",
        core.api.v1.views.databrowser_overview_summary_view,
        name="databrowser_overview_summary",
    ),
    path(
        "databrowser/metadata-summary",
        core.api.v1.views.databrowser_metadata_summary_view,
        name="databrowser_metadata_summary",
    ),
    path(
        "databrowser/metadata/property-distribution",
        core.api.v1.views.databrowser_metadata_property_distribution_view,
        name="databrowser_metadata_property_distribution",
    ),
    path(
        "databrowser/schema-summary",
        core.api.v1.views.databrowser_schema_summary_view,
        name="databrowser_schema_summary",
    ),
    path(
        "use-cases/data-summary",
        core.api.v1.views.use_case_data_summary_view,
        name="use_case_data_summary",
    ),
    path(
        "use-cases/isolate-explorer",
        core.api.v1.views.use_case_isolate_explorer_view,
        name="use_case_isolate_explorer",
    ),
    path(
        "variants/search",
        core.api.v1.views.variant_search_view,
        name="variant_search",
    ),
    path(
        "variants/summary",
        core.api.v1.views.variant_summary_view,
        name="variant_summary",
    ),
    path(
        "variants/reference-genomes",
        core.api.v1.views.variant_reference_genomes_view,
        name="variant_reference_genomes",
    ),
    path(
        "variants/filter-options",
        core.api.v1.views.variant_filter_options_view,
        name="variant_filter_options",
    ),
    path(
        "variants/ingest",
        core.api.v1.views.variant_ingest_view,
        name="variant_ingest",
    ),
]
