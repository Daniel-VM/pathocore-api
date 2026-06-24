# Generic imports
from django.urls import path

# Local imports
import core.api.v1.views
from core.api.ratelimit import apply_api_ratelimit

app_name = "pathocore_api"


def api_path(route, view, *, name, ratelimit_category="authenticated"):
    if ratelimit_category is None:
        return path(route, view, name=name)
    return path(
        route,
        apply_api_ratelimit(view, category=ratelimit_category),
        name=name,
    )


# TODO: keep this in sync with versioned API structure
urlpatterns = [
    api_path("auth/me", core.api.v1.views.auth_me_view, name="auth_me"),
    api_path(
        "access-requests",
        core.api.v1.views.access_requests_view,
        name="access_requests",
        ratelimit_category="write",
    ),
    api_path(
        "access-requests/catalog",
        core.api.v1.views.access_request_catalog_view,
        name="access_request_catalog",
        ratelimit_category=None,
    ),
    api_path(
        "access-requests/<int:request_id>/approve",
        core.api.v1.views.access_request_approve_view,
        name="access_request_approve",
        ratelimit_category="write",
    ),
    api_path(
        "access-requests/<int:request_id>/reject",
        core.api.v1.views.access_request_reject_view,
        name="access_request_reject",
        ratelimit_category="write",
    ),
    api_path(
        "access-requests/<int:request_id>/revoke",
        core.api.v1.views.access_request_revoke_view,
        name="access_request_revoke",
        ratelimit_category="write",
    ),
    api_path("schema", core.api.v1.views.schema, name="schema"),
    api_path(
        "schema/project_name=<str:project_name>",
        core.api.v1.views.schema_create,
        name="schema_by_project_name",
        ratelimit_category="write",
    ),
    api_path(
        "schema/<str:schema_name>/<str:schema_version>",
        core.api.v1.views.schema_detail,
        name="schema_detail",
    ),
    api_path(
        "samples",
        core.api.v1.views.samples,
        name="samples",
        ratelimit_category="write",
    ),
    api_path(
        "samples/metadata",
        core.api.v1.views.sample_metadata_property_view,
        name="sample_metadata_property",
        ratelimit_category="expensive",
    ),
    api_path(
        "samples/metadata/search",
        core.api.v1.views.sample_metadata_search_view,
        name="sample_metadata_search",
        ratelimit_category="expensive",
    ),
    api_path(
        "samples/history",
        core.api.v1.views.sample_history_view,
        name="sample_history",
        ratelimit_category="expensive",
    ),
    api_path(
        "samples/<str:sample_unique_id>/history",
        core.api.v1.views.sample_history_detail_view,
        name="sample_history_detail",
        ratelimit_category="expensive",
    ),
    api_path(
        "samples/<str:sample_unique_id>",
        core.api.v1.views.sample_detail_view,
        name="sample_detail",
    ),
    api_path(
        "samples/<str:sample_unique_id>/metadata",
        core.api.v1.views.sample_metadata_view,
        name="sample_metadata",
        ratelimit_category="expensive",
    ),
    api_path(
        "databrowser/overview-summary",
        core.api.v1.views.databrowser_overview_summary_view,
        name="databrowser_overview_summary",
        ratelimit_category=None,
    ),
    api_path(
        "databrowser/metadata-summary",
        core.api.v1.views.databrowser_metadata_summary_view,
        name="databrowser_metadata_summary",
        ratelimit_category=None,
    ),
    api_path(
        "databrowser/metadata/property-distribution",
        core.api.v1.views.databrowser_metadata_property_distribution_view,
        name="databrowser_metadata_property_distribution",
        ratelimit_category=None,
    ),
    api_path(
        "databrowser/schema-summary",
        core.api.v1.views.databrowser_schema_summary_view,
        name="databrowser_schema_summary",
        ratelimit_category=None,
    ),
    api_path(
        "use-cases/data-summary",
        core.api.v1.views.use_case_data_summary_view,
        name="use_case_data_summary",
        ratelimit_category="expensive",
    ),
    api_path(
        "use-cases/isolate-explorer",
        core.api.v1.views.use_case_isolate_explorer_view,
        name="use_case_isolate_explorer",
        ratelimit_category="expensive",
    ),
    api_path(
        "variants/search",
        core.api.v1.views.variant_search_view,
        name="variant_search",
        ratelimit_category=None,
    ),
    api_path(
        "variants/summary",
        core.api.v1.views.variant_summary_view,
        name="variant_summary",
        ratelimit_category=None,
    ),
    api_path(
        "variants/reference-genomes",
        core.api.v1.views.variant_reference_genomes_view,
        name="variant_reference_genomes",
        ratelimit_category=None,
    ),
    api_path(
        "variants/filter-options",
        core.api.v1.views.variant_filter_options_view,
        name="variant_filter_options",
        ratelimit_category=None,
    ),
    api_path(
        "variants/ingest",
        core.api.v1.views.variant_ingest_view,
        name="variant_ingest",
        ratelimit_category="write",
    ),
]
