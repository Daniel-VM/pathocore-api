# Generic imports
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import (
    authentication_classes,
    permission_classes,
    api_view,
)
from rest_framework import status
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import NotFound
from drf_spectacular.utils import (
    extend_schema,
    OpenApiExample,
    inline_serializer,
    OpenApiParameter,
)
from rest_framework import serializers
from django.core.exceptions import PermissionDenied

# Local imports
import core.models
import core.api.utils.samples
import core.api.v1.serializers
import core.api.utils.metadata_values
import core.api.utils.public_db
import core.api.utils.common_functions
import core.config
from core.api.services import sample_ingestion
from core.api.services import sample_listing
from core.api.services import sample_detail
from core.api.services import sample_metadata
from core.api.services import sample_metadata_ingestion
from core.api.services import sample_history
from core.api.services import schema_ingestion
from core.api.services import schema_listing

# Documentation TAGs for drf-spectacular
TAG_SCHEMAS = "Schemas"
TAG_SAMPLES = "Samples"
TAG_SAMPLE_METADATA = "Sample Metadata"
TAG_SAMPLE_HISTORY = "Sample History"

# API-side agination for /samples list endpoint.
class SamplesPagination(PageNumberPagination):
    page_size = 500
    page_size_query_param = "page_size"
    max_page_size = 5000


# FIXME: Sample ingest rejects json containing fields not defined in SampleIngestSerializer
@extend_schema(
    methods=["POST"],
    tags=[TAG_SAMPLES],
    summary="Ingest one sample",
    description=(
        "Create a sample and generate `sample_unique_id` deterministically from "
        "project-relevant identifiers. Admin privileges are required."
    ),
    request=core.api.v1.serializers.SampleIngestSerializer,
    responses={
        200: core.api.v1.serializers.SampleIngestResponseSerializer,
        201: core.api.v1.serializers.SampleIngestResponseSerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
        409: core.api.v1.serializers.ErrorSerializer,
    },
    examples=[
        OpenApiExample(
            "SampleIngestRequest",
            request_only=True,
            value={
                "schema_name": "Mepram Schema",
                "schema_version": "1.0.0dev",
                "sequencing_sample_id": "LAB-0008",
                "collecting_lab_sample_id": "COLL-0008",
                "submitting_lab_sample_id": "SUB-0008",
                "collecting_institution": "Hospital Universitario",
                "sequencing_date": "2026-02-24",
            },
        ),
        OpenApiExample(
            "SampleIngestCreated",
            response_only=True,
            status_codes=["201"],
            value={
                "sample_unique_id": "474e5b6670e8",
                "sequencing_sample_id": "LAB-0008",
                "created": True,
                "status": "created",
            },
        ),
        OpenApiExample(
            "SampleIngestDuplicate",
            response_only=True,
            status_codes=["409"],
            value={
                "error": "Sample already exists",
                "sample_unique_id": "474e5b6670e8",
                "sequencing_sample_id": "LAB-0008",
                "submitting_lab_sample_id": "SUB-0008",
            },
        ),
    ],
)
@extend_schema(
    methods=["GET"],
    tags=[TAG_SAMPLES],
    summary="List samples",
    description=(
        "Return samples visible to the authenticated user, with optional filters. "
        "Non-admin users are automatically restricted to their project scope."
    ),
    parameters=[
        inline_serializer(
            name="SampleListQuery",
            fields={
                "sample_unique_id": serializers.CharField(required=False),
                "sequencing_sample_id": serializers.CharField(required=False),
                "collecting_institution": serializers.CharField(required=False),
                "collecting_lab_sample_id": serializers.CharField(required=False),
                "microbiology_lab_sample_id": serializers.CharField(required=False),
                "submitting_lab_sample_id": serializers.CharField(required=False),
                "schema_name": serializers.CharField(required=False),
                "schema_version": serializers.CharField(required=False),
                "created_at_from": serializers.DateTimeField(required=False),
                "created_at_to": serializers.DateTimeField(required=False),
                "sequencing_date_from": serializers.DateTimeField(required=False),
                "sequencing_date_to": serializers.DateTimeField(required=False),
                "page": serializers.IntegerField(required=False, min_value=1),
                "page_size": serializers.IntegerField(
                    required=False, min_value=1, max_value=5000
                ),
            },
        )
    ],
    responses={
        200: core.api.v1.serializers.SampleListPaginatedResponseSerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
    },
    examples=[
        OpenApiExample(
            "SampleListBySchema",
            value={
                "count": 21317,
                "next": "http://localhost:8000/v1/samples?page=2&page_size=500",
                "previous": None,
                "results": [
                    {
                        "sample_unique_id": "474e5b6670e8",
                        "sequencing_sample_id": "LAB-0008",
                        "created_at": "2026-02-24T09:34:57.167046",
                        "schema_name": "Mepram Schema",
                        "schema_version": "1.0.0dev",
                    }
                ],
            },
            response_only=True,
            status_codes=["200"],
        )
    ],
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def samples(request):
    if request.method == "POST":
        # Few checks
        if not request.user.is_staff:
            return Response(
                {"error": "Admin privileges required"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # validation before ingestion
        serializer = core.api.v1.serializers.SampleIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        traceability_data = {
            key: value
            for key, value in {
                "sequencing_sample_id": serializer.validated_data.get("sequencing_sample_id"),
                "submitting_lab_sample_id": serializer.validated_data.get("submitting_lab_sample_id"),
                "collecting_lab_sample_id": serializer.validated_data.get("collecting_lab_sample_id"),
                "collecting_lab_isolate_id": serializer.validated_data.get("collecting_lab_isolate_id"),
            }.items()
            if value is not None and str(value).strip() != ""
        }

        # Create/Ingest Sample
        try:
            sample_obj, created = sample_ingestion.ingest_sample(
                serializer.validated_data, request_user=request.user
            )
        except ValueError as exc:
            error_message = str(exc)
            if error_message == "Sample already exists":
                generated_sample_id = sample_ingestion.create_sample_unique_id(
                    serializer.validated_data
                )
                existing_sample = core.models.Sample.objects.filter(
                    sample_unique_id=generated_sample_id
                ).last()
                if existing_sample:
                    core.api.utils.common_functions.record_sample_error(
                        existing_sample,
                        core.api.utils.common_functions.map_error_name(error_message),
                    )
                    return Response(
                        {
                            "error": error_message,
                            "sample_unique_id": existing_sample.sample_unique_id,
                            "sequencing_sample_id": existing_sample.sequencing_sample_id,
                            "submitting_lab_sample_id": existing_sample.submitting_lab_sample_id,
                        },
                        status=status.HTTP_409_CONFLICT,
                    )
                return Response(
                    {"error": error_message, **traceability_data},
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                {"error": error_message, **traceability_data},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # If created, add initial state history
        if created:
            state_obj = core.models.SampleState.objects.filter(
                state__exact="Defined"
            ).last()
            if state_obj is None:
                return Response(
                    {"error": "Sample state 'Defined' not configured"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                result = core.api.utils.common_functions.add_sample_state_history(
                    sample_obj, state_id=state_obj.pk, error_name="No error"
                )
            except ValueError as exc:
                return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
            if isinstance(result, Response):
                return result

        # Prepare POST response
        response_serializer = core.api.v1.serializers.SampleIngestResponseSerializer(
            data={
                "sample_unique_id": sample_obj.sample_unique_id,
                "sequencing_sample_id": sample_obj.sequencing_sample_id,
                "created": created,
                "status": "created" if created else "existing",
            }
        )
        response_serializer.is_valid(raise_exception=True)

        # Return
        return Response(
            response_serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    # GET samples with filters
    data = request.data or request.query_params
    filter_serializer = core.api.v1.serializers.SampleFilterSerializer(data=data)
    filter_serializer.is_valid(raise_exception=True)
    try:
        queryset = sample_listing.list_samples(
            filter_serializer.validated_data, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not queryset.exists():
        return Response({"error": "No samples found"}, status=status.HTTP_404_NOT_FOUND)
    queryset = queryset.order_by("id")
    paginator = SamplesPagination()
    try:
        page = paginator.paginate_queryset(queryset, request)
    except NotFound as exc:
        return Response({"error": str(exc.detail)}, status=status.HTTP_404_NOT_FOUND)

    response_serializer = core.api.v1.serializers.SampleListItemSerializer(
        page, many=True
    )
    return paginator.get_paginated_response(response_serializer.data)


@extend_schema(
    tags=[TAG_SCHEMAS],
    summary="List schemas",
    description=(
        "Return schema registry entries. "
        "Non-admin users only see schemas for their own project scope."
    ),
    parameters=[
        inline_serializer(
            name="SchemaListQuery",
            fields={
                "schema_name": serializers.CharField(required=False),
                "schema_version": serializers.CharField(required=False),
                "schema_in_use": serializers.BooleanField(required=False),
                "project_name": serializers.CharField(required=False),
            },
        )
    ],
    responses={
        200: core.api.v1.serializers.SchemaListItemSerializer(many=True),
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
    },
    examples=[
        OpenApiExample(
            "SchemaListResponse",
            response_only=True,
            status_codes=["200"],
            value=[
                {
                    "schema_name": "Mepram Schema",
                    "schema_version": "1.0.0dev",
                    "schema_in_use": True,
                    "project_name": "mepram",
                    "generated_at": "2026-02-20T09:29:29.730943",
                }
            ],
        )
    ],
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def schema(request):
    data = request.query_params
    filter_serializer = core.api.v1.serializers.SchemaListFilterSerializer(data=data)
    filter_serializer.is_valid(raise_exception=True)

    try:
        queryset = schema_listing.list_schemas(
            filter_serializer.validated_data, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    response_serializer = core.api.v1.serializers.SchemaListItemSerializer(
        queryset, many=True
    )
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_SCHEMAS],
    summary="Upload a schema for a project",
    parameters=[
        OpenApiParameter(
            name="project_name",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description=(
                "Project scope to assign the schema. Allowed values: "
                "mepram, relecov, redlabra."
            ),
        )
    ],
    request=core.api.v1.serializers.SchemaIngestSerializer,
    responses={
        201: core.api.v1.serializers.SchemaIngestResponseSerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        409: core.api.v1.serializers.ErrorSerializer,
    },
    description=(
        "Upload a schema JSON using a wrapper payload. "
        "`project_name` is required in the URL and must be one of the allowed "
        "project codes (`mepram`, `relecov`, `redlabra`). "
        "`title` and `version` must exist inside the `schema` object. "
        "If `schema_in_use` is omitted, the uploaded schema becomes the active "
        "schema for the same project and schema name."
    ),
    examples=[
        OpenApiExample(
            "WrapperWithActiveFlag",
            request_only=True,
            value={
                "schema": {
                    "title": "mepram-schema",
                    "version": "1.0.0dev",
                    "type": "object",
                    "properties": {"sample_unique_id": {"type": "string"}},
                    "required": ["sample_unique_id"],
                },
                "schema_in_use": True,
            },
        ),
        OpenApiExample(
            "SchemaCreated",
            response_only=True,
            status_codes=["201"],
            value={
                "schema_name": "Mepram Schema",
                "schema_version": "1.0.0dev",
                "project_name": "mepram",
                "properties_count": 123,
                "schema_in_use": True,
                "status": "created",
            },
        ),
        OpenApiExample(
            "SchemaAlreadyExists",
            response_only=True,
            status_codes=["409"],
            value={"error": "Schema already exists"},
        ),
    ],
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def schema_create(request, project_name):
    if not request.user.is_staff:
        return Response(
            {"error": "Admin privileges required"},
            status=status.HTTP_403_FORBIDDEN,
        )
    serializer = core.api.v1.serializers.SchemaIngestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = dict(serializer.validated_data)
    payload["schema_app_name"] = project_name

    try:
        schema_obj, properties_count = schema_ingestion.ingest_schema(
            payload, request_user=request.user
        )
    except ValueError as exc:
        error_message = str(exc)
        if error_message == "Schema already exists":
            return Response({"error": error_message}, status=status.HTTP_409_CONFLICT)
        return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    response_serializer = core.api.v1.serializers.SchemaIngestResponseSerializer(
        data={
            "schema_name": schema_obj.schema_name,
            "schema_version": schema_obj.schema_version,
            "project_name": schema_obj.schema_app_name,
            "properties_count": properties_count,
            "schema_in_use": schema_obj.schema_in_use,
            "status": "created",
        }
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=[TAG_SCHEMAS],
    summary="Get schema detail",
    description=(
        "Return schema metadata and the full schema JSON content for a "
        "specific `schema_name` + `schema_version`."
    ),
    parameters=[
        OpenApiParameter(
            name="schema_name",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description="Schema title stored in registry",
        ),
        OpenApiParameter(
            name="schema_version",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description="Schema version stored in registry",
        ),
    ],
    responses={
        200: core.api.v1.serializers.SchemaDetailSerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
    },
    examples=[
        OpenApiExample(
            "SchemaDetailResponse",
            response_only=True,
            status_codes=["200"],
            value={
                "schema_name": "Mepram Schema",
                "schema_version": "1.0.0dev",
                "schema_in_use": True,
                "project_name": "mepram",
                "generated_at": "2026-02-20T09:29:29.730943",
                "schema": {
                    "title": "Mepram Schema",
                    "version": "1.0.0dev",
                    "type": "object",
                },
            },
        )
    ],
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def schema_detail(request, schema_name, schema_version):
    try:
        schema_obj, schema_json = schema_listing.get_schema_by_name_version(
            schema_name, schema_version, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    if schema_obj is None:
        return Response({"error": "Schema not found"}, status=status.HTTP_404_NOT_FOUND)
    if schema_json is None:
        return Response(
            {"error": "Schema file could not be read"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    response_serializer = core.api.v1.serializers.SchemaDetailSerializer(
        {
            "schema_name": schema_obj.schema_name,
            "schema_version": schema_obj.schema_version,
            "schema_in_use": schema_obj.schema_in_use,
            "project_name": schema_obj.schema_app_name,
            "generated_at": schema_obj.generated_at,
            "schema": schema_json,
        }
    )
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_SAMPLES],
    summary="Get sample detail",
    description="Return canonical sample fields for one `sample_unique_id`.",
    parameters=[
        OpenApiParameter(
            name="sample_unique_id",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description="Deterministic unique sample identifier",
        )
    ],
    responses={
        200: core.api.v1.serializers.SampleDetailSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
    },
    examples=[
        OpenApiExample(
            "SampleDetailResponse",
            response_only=True,
            status_codes=["200"],
            value={
                "sample_unique_id": "474e5b6670e8",
                "sequencing_sample_id": "LAB-0008",
                "microbiology_lab_sample_id": "MICRO-0008",
                "collecting_lab_sample_id": "COLL-0008",
                "submitting_lab_sample_id": "SUB-0008",
                "collecting_institution": "Hospital Universitario",
                "sequence_file_R1_md5": "8c33257f30626aebd39389b9124fe792",
                "sequence_file_R2_md5": "ca3bec10fe70dfff850a78e5d35fa34e",
                "r1_fastq_filepath": "/data/fastq/LAB-0008_R1.fastq.gz",
                "r2_fastq_filepath": "/data/fastq/LAB-0008_R2.fastq.gz",
                "sequencing_date": "2026-01-08T00:00:00",
                "created_at": "2026-02-24T09:34:57.167046",
                "schema_name": "Mepram Schema",
                "schema_version": "1.0.0dev",
            },
        )
    ],
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sample_detail_view(request, sample_unique_id):
    try:
        sample_obj = sample_detail.get_sample_detail(
            sample_unique_id, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    if sample_obj is None:
        return Response({"error": "Sample not found"}, status=status.HTTP_404_NOT_FOUND)
    response_serializer = core.api.v1.serializers.SampleDetailSerializer(sample_obj)
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_SAMPLE_HISTORY],
    summary="List sample history",
    description=(
        "Return sample state history rows with optional filters "
        "(sample identifiers, state, error and date range)."
    ),
    parameters=[
        inline_serializer(
            name="SampleHistoryQuery",
            fields={
                "sample_id": serializers.IntegerField(required=False),
                "sample_unique_id": serializers.CharField(required=False),
                "sequencing_sample_id": serializers.CharField(required=False),
                "submitting_lab_sample_id": serializers.CharField(required=False),
                "collecting_lab_isolate_id": serializers.CharField(required=False),
                "collecting_lab_sample_id": serializers.CharField(required=False),
                "state_id": serializers.IntegerField(required=False),
                "state": serializers.CharField(required=False),
                "error_name_id": serializers.IntegerField(required=False),
                "error_name": serializers.CharField(required=False),
                "is_current": serializers.BooleanField(required=False),
                "changed_at_from": serializers.DateTimeField(required=False),
                "changed_at_to": serializers.DateTimeField(required=False),
            },
        )
    ],
    responses={
        200: core.api.v1.serializers.SampleHistoryItemSerializer(many=True),
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
    },
    examples=[
        OpenApiExample(
            "SampleHistoryResponse",
            response_only=True,
            status_codes=["200"],
            value=[
                {
                    "sample_unique_id": "474e5b6670e8",
                    "state": "Defined",
                    "error_name": "No error",
                    "is_current": False,
                    "changed_at": "2026-02-24T09:34:57.167046",
                },
                {
                    "sample_unique_id": "474e5b6670e8",
                    "state": "Bioinfo",
                    "error_name": "No error",
                    "is_current": True,
                    "changed_at": "2026-02-24T09:35:45.113002",
                },
            ],
        )
    ],
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sample_history_view(request):
    filter_serializer = core.api.v1.serializers.SampleHistoryFilterSerializer(
        data=request.query_params
    )
    filter_serializer.is_valid(raise_exception=True)
    try:
        queryset = sample_history.list_sample_history(
            filter_serializer.validated_data, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    if not queryset.exists():
        return Response({"error": "No history found"}, status=status.HTTP_404_NOT_FOUND)
    response_serializer = core.api.v1.serializers.SampleHistoryItemSerializer(
        queryset, many=True
    )
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_SAMPLE_HISTORY],
    summary="Get history for one sample",
    description="Return all history rows for one `sample_unique_id`.",
    parameters=[
        OpenApiParameter(
            name="sample_unique_id",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description="Deterministic unique sample identifier",
        )
    ],
    responses={
        200: core.api.v1.serializers.SampleHistoryItemSerializer(many=True),
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
    },
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sample_history_detail_view(request, sample_unique_id):
    try:
        queryset = sample_history.list_sample_history(
            {"sample_unique_id": sample_unique_id}, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    if not queryset.exists():
        return Response({"error": "No history found"}, status=status.HTTP_404_NOT_FOUND)
    response_serializer = core.api.v1.serializers.SampleHistoryItemSerializer(
        queryset, many=True
    )
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_SAMPLE_METADATA],
    summary="Discover metadata by property/value",
    description=(
        "Two modes are supported:\n"
        "1) `classification` only: list available properties for that classification.\n"
        "2) `property`/`value`: return samples matching metadata constraints.\n"
        "When multiple `value` params are sent, `match=any|all` controls matching."
    ),
    parameters=[
        OpenApiParameter(
            name="classification",
            type=str,
            required=False,
            location=OpenApiParameter.QUERY,
            description="Classification name to list properties for",
        ),
        OpenApiParameter(
            name="property",
            type=str,
            required=False,
            location=OpenApiParameter.QUERY,
            description="Metadata property name to search across samples",
        ),
        OpenApiParameter(
            name="value",
            type=str,
            required=False,
            many=True,
            location=OpenApiParameter.QUERY,
            description="Optional value(s) to match. Repeat query param for multiple values.",
        ),
        OpenApiParameter(
            name="match",
            type=str,
            required=False,
            location=OpenApiParameter.QUERY,
            description="When multiple values are provided: all or any (default any)",
        ),
    ],
    responses={
        200: core.api.v1.serializers.SampleMetadataSearchResultSerializer(many=True),
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
    },
    examples=[
        OpenApiExample(
            "MetadataSearchResponse",
            response_only=True,
            status_codes=["200"],
            value=[
                {
                    "sample_unique_id": "474e5b6670e8",
                    "values": {
                        "bioinformatics_protocol_software_version": "3.3.2",
                        "all_in_one_library_kit": "Ion Xpress",
                    },
                }
            ],
        ),
    ],
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sample_metadata_property_view(request):
    classification = request.query_params.get("classification")
    property_name = request.query_params.get("property")
    values = request.query_params.getlist("value")
    match = request.query_params.get("match")

    # Keep backward-compatible mode:
    # classification only -> list available properties in that classification.
    if classification and not property_name and not values:
        filter_serializer = (
            core.api.v1.serializers.SampleMetadataClassificationFilterSerializer(
                data={"classification": classification}
            )
        )
        filter_serializer.is_valid(raise_exception=True)
        try:
            results = sample_metadata.list_properties_by_classification(
                filter_serializer.validated_data["classification"],
                request_user=request.user,
            )
        except PermissionDenied as exc:
            return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if not results:
            return Response(
                {"error": "No properties found"}, status=status.HTTP_404_NOT_FOUND
            )
        response_serializer = (
            core.api.v1.serializers.SampleMetadataClassificationResultSerializer(
                results, many=True
            )
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    data = {}
    if classification:
        data["classification"] = classification
    if property_name:
        data["property"] = property_name
    if values:
        data["value"] = values
    if match:
        data["match"] = match

    filter_serializer = core.api.v1.serializers.SampleMetadataPropertyQuerySerializer(
        data=data
    )
    filter_serializer.is_valid(raise_exception=True)

    try:
        results = sample_metadata.list_samples_by_metadata_query(
            property_name=filter_serializer.validated_data.get("property"),
            values=filter_serializer.validated_data.get("value"),
            match=filter_serializer.validated_data.get("match", "any"),
            classification=filter_serializer.validated_data.get("classification"),
            request_user=request.user,
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not results:
        return Response({"error": "No samples found"}, status=status.HTTP_404_NOT_FOUND)

    response_serializer = core.api.v1.serializers.SampleMetadataSearchResultSerializer(
        results, many=True
    )
    return Response(response_serializer.data, status=status.HTTP_200_OK)


# TODO: Define response body
# TODO: not ready for complex fields
@extend_schema(
    tags=[TAG_SAMPLE_METADATA],
    summary="Search metadata with repeatable filter expressions",
    description=(
        "Search samples using repeatable `filter` query parameters. "
        "Each filter accepts `property`, `property:value`, or `property=value`.\n\n"
        "Examples:\n"
        "- `filter=bioinformatics_protocol_software_version:3.3.2`\n"
        "- `filter=all_in_one_library_kit=Ion Xpress`\n"
        "- `filter=sequence_file_path_R1` (property existence)\n"
        "Use `match=all|any` to combine multiple filters."
    ),
    parameters=[
        OpenApiParameter(
            name="filter",
            type=str,
            required=True,
            many=True,
            location=OpenApiParameter.QUERY,
            description="Repeatable filter: property[:value] or property=value",
        ),
        OpenApiParameter(
            name="match",
            type=str,
            required=False,
            location=OpenApiParameter.QUERY,
            description="Match mode for filters: all (default) or any",
        ),
    ],
    responses={
        200: core.api.v1.serializers.SampleMetadataSearchResultSerializer(many=True),
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
    },
    examples=[
        OpenApiExample(
            "MetadataSearchByTwoFilters",
            response_only=True,
            status_codes=["200"],
            value=[
                {
                    "sample_unique_id": "474e5b6670e8",
                    "values": {
                        "bioinformatics_protocol_software_version": "3.3.2",
                        "all_in_one_library_kit": "Ion Xpress",
                    },
                }
            ],
        ),
        OpenApiExample(
            "MetadataSearchUnknownProperty",
            response_only=True,
            status_codes=["400"],
            value={"error": "Unknown property(ies): property_that_does_not_exist"},
        ),
    ],
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sample_metadata_search_view(request):
    raw_filters = request.query_params.getlist("filter")
    data = {"filter": raw_filters}
    if "match" in request.query_params:
        data["match"] = request.query_params.get("match")
    filter_serializer = core.api.v1.serializers.SampleMetadataSearchSerializer(
        data=data
    )
    filter_serializer.is_valid(raise_exception=True)

    filters = []
    for raw_filter in filter_serializer.validated_data["filter"]:
        raw_filter = raw_filter.strip()
        if not raw_filter:
            return Response(
                {"error": "filter entries cannot be empty"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if ":" in raw_filter:
            prop, _, value = raw_filter.partition(":")
        elif "=" in raw_filter:
            prop, _, value = raw_filter.partition("=")
        else:
            prop, value = raw_filter, None
        prop = prop.strip()
        if not prop:
            return Response(
                {"error": "filter entries must include a property"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if value is not None:
            value = value.strip()
            if not value:
                return Response(
                    {"error": "filter values cannot be empty"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        filters.append({"property": prop, "value": value})

    try:
        results = sample_metadata.search_samples_metadata(
            filters,
            match=filter_serializer.validated_data.get("match", "all"),
            request_user=request.user,
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not results:
        return Response({"error": "No samples found"}, status=status.HTTP_404_NOT_FOUND)

    response_serializer = core.api.v1.serializers.SampleMetadataSearchResultSerializer(
        results, many=True
    )
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    methods=["GET"],
    tags=[TAG_SAMPLE_METADATA],
    summary="Get metadata for one sample",
    description=(
        "Return stored metadata key/value entries for one sample identified by "
        "`sample_unique_id`."
    ),
    parameters=[
        OpenApiParameter(
            name="sample_unique_id",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description="Deterministic unique sample identifier",
        )
    ],
    responses={
        200: core.api.v1.serializers.SampleMetadataItemSerializer(many=True),
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
        400: core.api.v1.serializers.ErrorSerializer,
    },
    examples=[
        OpenApiExample(
            "SampleMetadataGetResponse",
            response_only=True,
            status_codes=["200"],
            value=[
                {"bioinformatics_protocol_software_version": "3.3.2"},
                {"all_in_one_library_kit": "Ion Xpress"},
            ],
        )
    ],
)
@extend_schema(
    methods=["POST"],
    tags=[TAG_SAMPLE_METADATA],
    summary="Ingest metadata for one sample",
    description=(
        "Store metadata values for one sample. Admin privileges are required. "
        "By default the sample's assigned schema is used, or a matching "
        "`schema_name` + `schema_version` can be provided in payload."
    ),
    parameters=[
        OpenApiParameter(
            name="sample_unique_id",
            type=str,
            location=OpenApiParameter.PATH,
            required=True,
            description="Deterministic unique sample identifier",
        )
    ],
    request=core.api.v1.serializers.SampleMetadataIngestSerializer,
    responses={
        201: core.api.v1.serializers.SampleMetadataIngestResponseSerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
        409: core.api.v1.serializers.ErrorSerializer,
    },
    examples=[
        OpenApiExample(
            "SampleMetadataIngestRequest",
            request_only=True,
            value={
                "schema_name": "Mepram Schema",
                "schema_version": "1.0.0dev",
                "bioinformatics_protocol_software_version": "3.3.2",
                "all_in_one_library_kit": "Ion Xpress",
            },
        ),
        OpenApiExample(
            "SampleMetadataIngestResponse",
            response_only=True,
            status_codes=["201"],
            value={
                "sample_unique_id": "474e5b6670e8",
                "stored_count": 139,
                "status": "stored",
            },
        ),
    ],
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def sample_metadata_view(request, sample_unique_id):
    try:
        sample_obj = sample_detail.get_sample_detail(
            sample_unique_id, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    if sample_obj is None:
        return Response({"error": "Sample not found"}, status=status.HTTP_404_NOT_FOUND)
    # TODO: complex fields (grouped metadata) are not exposed yet.

    # GET method
    if request.method == "GET":
        metadata_list = sample_metadata.list_sample_metadata(
            sample_obj,
            classifications=None,
            properties=None,
            request_user=request.user,
        )
        response_serializer = core.api.v1.serializers.SampleMetadataItemSerializer(
            metadata_list, many=True
        )
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    # POST method
    if not request.user.is_staff:
        return Response(
            {"error": "Admin privileges required"},
            status=status.HTTP_403_FORBIDDEN,
        )
    serializer = core.api.v1.serializers.SampleMetadataIngestSerializer(
        data=request.data
    )
    try:
        serializer.is_valid(raise_exception=True)
    except serializers.ValidationError as exc:
        core.api.utils.common_functions.record_sample_error(sample_obj, "Other")
        return Response(exc.detail, status=status.HTTP_400_BAD_REQUEST)
    payload = serializer.validated_data["payload"]

    schema_name = serializer.validated_data.get("schema_name")
    schema_version = serializer.validated_data.get("schema_version")
    if schema_name and schema_version:
        schema_obj = core.models.Schema.objects.filter(
            schema_name=schema_name, schema_version=schema_version
        ).last()
        if schema_obj is None:
            error_message = "Schema not found for provided name/version"
            core.api.utils.common_functions.record_sample_error(
                sample_obj,
                core.api.utils.common_functions.map_error_name(error_message),
            )
            return Response(
                {"error": error_message},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if sample_obj.schema_obj_id and sample_obj.schema_obj_id != schema_obj.id:
            error_message = "Schema does not match sample schema"
            core.api.utils.common_functions.record_sample_error(
                sample_obj,
                core.api.utils.common_functions.map_error_name(error_message),
            )
            return Response(
                {"error": error_message},
                status=status.HTTP_400_BAD_REQUEST,
            )
    else:
        schema_obj = sample_obj.schema_obj
        if schema_obj is None:
            error_message = "Sample has no schema assigned"
            core.api.utils.common_functions.record_sample_error(
                sample_obj,
                core.api.utils.common_functions.map_error_name(error_message),
            )
            return Response(
                {"error": error_message},
                status=status.HTTP_400_BAD_REQUEST,
            )

    try:
        stored_count = sample_metadata_ingestion.ingest_sample_metadata(
            sample_obj, schema_obj, payload
        )
    except ValueError as exc:
        error_message = str(exc)
        if error_message == "Metadata already stored for this sample":
            core.api.utils.common_functions.record_sample_error(
                sample_obj,
                core.api.utils.common_functions.map_error_name(error_message),
            )
            return Response({"error": error_message}, status=status.HTTP_409_CONFLICT)
        core.api.utils.common_functions.record_sample_error(
            sample_obj,
            core.api.utils.common_functions.map_error_name(error_message),
        )
        return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    if stored_count:
        state_obj = core.models.SampleState.objects.filter(
            state__exact="Bioinfo"
        ).last()
        if state_obj is None:
            return Response(
                {"error": "Sample state 'Bioinfo' not configured"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = core.api.utils.common_functions.add_sample_state_history(
                sample_obj, state_id=state_obj.pk, error_name="No error"
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(result, Response):
            return result

    # TODO: document status and stored_counts in api
    response_serializer = (
        core.api.v1.serializers.SampleMetadataIngestResponseSerializer(
            data={
                "sample_unique_id": sample_unique_id,
                "stored_count": stored_count,
                "status": "stored" if stored_count else "no_changes",
            }
        )
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_201_CREATED)
