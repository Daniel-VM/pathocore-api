# Generic imports
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
from django.db import transaction, IntegrityError

# Local imports
import core.models
import core.api.v1.serializers
import core.api.utils.common_functions
from core.api.authentication import (
    KeycloakJWTAuthentication as SessionAuthentication,
)
from core.api.authentication import (
    LegacyBasicOrSessionAuthentication as BasicAuthentication,
)
from core.api.permissions import HasProjectAccess
from core.api.services import sample_ingestion
from core.api.services import sample_listing
from core.api.services import sample_detail
from core.api.services import sample_metadata
from core.api.services import sample_metadata_ingestion
from core.api.services import sample_history
from core.api.services import schema_ingestion
from core.api.services import schema_listing
from core.api.services import databrowser
from core.api.services import variant_ingestion
from core.api.services import variant_search
from core.api.utils import access_control

# Documentation TAGs for drf-spectacular
TAG_SCHEMAS = "Schemas"
TAG_SAMPLES = "Samples"
TAG_SAMPLE_METADATA = "Sample Metadata"
TAG_SAMPLE_HISTORY = "Sample History"
TAG_DATABROWSER = "Databrowser"
TAG_VARIANTS = "Variants"
TAG_AUTH = "Authentication"


# API-side agination for /samples list endpoint.
class SamplesPagination(PageNumberPagination):
    page_size = 500
    page_size_query_param = "page_size"
    max_page_size = 5000


class VariantsPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 5000


def _reject_generic_databrowser_query_params(
    request, endpoint_name, allowed_params=None
):
    allowed_params = set(allowed_params or [])
    unsupported_params = sorted(set(request.query_params.keys()) - allowed_params)
    if unsupported_params:
        if allowed_params:
            allowed_text = ", ".join(sorted(allowed_params))
            message = (
                f"{endpoint_name} only supports these query parameters: "
                f"{allowed_text}"
            )
        else:
            message = f"{endpoint_name} does not support query parameters"
        return Response(
            {
                "error": message,
                "unsupported_query_params": unsupported_params,
            },
            status=status.HTTP_400_BAD_REQUEST,
        )
    return None


@extend_schema(
    tags=[TAG_AUTH],
    summary="Return authenticated user context",
    responses={
        200: inline_serializer(
            name="AuthMeResponse",
            fields={
                "authenticated": serializers.BooleanField(),
                "provider": serializers.CharField(),
                "user": inline_serializer(
                    name="AuthMeUser",
                    fields={
                        "id": serializers.CharField(),
                        "username": serializers.CharField(),
                        "groups": serializers.ListField(
                            child=serializers.CharField(), required=False
                        ),
                        "projects": serializers.ListField(
                            child=serializers.DictField(), required=False
                        ),
                    },
                ),
                "token": serializers.DictField(),
            },
        ),
        401: core.api.v1.serializers.ErrorSerializer,
    },
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def auth_me_view(request):
    user_projects = access_control.get_user_projects(request.user)
    if not user_projects and not access_control.is_keycloak_user(request.user):
        try:
            project_code = access_control.get_user_project_code(request.user)
        except PermissionDenied:
            project_code = None
        if project_code:
            user_projects = [
                {
                    "id": project_code,
                    "labs": [],
                    "role": "admin" if access_control.is_admin_user(request.user) else "",
                }
            ]

    return Response(
        {
            "authenticated": True,
            "provider": getattr(request.user, "auth_provider", "legacy-basic"),
            "user": {
                "id": str(getattr(request.user, "id", "")),
                "username": str(getattr(request.user, "username", "")),
                "groups": list(getattr(request.user, "groups", [])),
                "projects": user_projects,
            },
            "token": request.auth if isinstance(request.auth, dict) else {},
        },
        status=status.HTTP_200_OK,
    )


# FIXME: Sample ingest rejects json containing fields not defined in SampleIngestSerializer
@extend_schema(
    methods=["POST"],
    tags=[TAG_SAMPLES],
    summary="Ingest one sample",
    description=(
        "Create a sample, generate a deterministic fingerprint for deduplication "
        "and assign a sequential `sample_unique_id`. Admin privileges are required."
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
                "sample_unique_id": "SAM-AAA-0001",
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
                "sample_unique_id": "SAM-AAA-0001",
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
                        "sample_unique_id": "SAM-AAA-0001",
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
        # validation before ingestion
        serializer = core.api.v1.serializers.SampleIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        traceability_data = {
            key: value
            for key, value in {
                "sequencing_sample_id": serializer.validated_data.get(
                    "sequencing_sample_id"
                ),
                "submitting_lab_sample_id": serializer.validated_data.get(
                    "submitting_lab_sample_id"
                ),
                "collecting_lab_sample_id": serializer.validated_data.get(
                    "collecting_lab_sample_id"
                ),
                "collecting_lab_isolate_id": serializer.validated_data.get(
                    "collecting_lab_isolate_id"
                ),
            }.items()
            if value is not None and str(value).strip() != ""
        }

        # Create/Ingest Sample
        try:
            sample_create_data = sample_ingestion.prepare_sample_create(
                serializer.validated_data, request_user=request.user
            )
        except PermissionDenied as exc:
            return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as exc:
            error_message = str(exc)
            if error_message == "Sample already exists":
                existing_sample = sample_ingestion.get_existing_sample(
                    serializer.validated_data
                )
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

        try:
            with transaction.atomic():
                sequence_obj = (
                    core.models.SampleIdSequence.objects.select_for_update()
                    .filter(sequence_name="sample_unique_id")
                    .last()
                )
                if sequence_obj is None:
                    next_sample_unique_id = (
                        sample_ingestion.get_initial_sample_unique_id()
                    )
                    sequence_obj = core.models.SampleIdSequence.objects.create(
                        sequence_name="sample_unique_id",
                        last_value=next_sample_unique_id,
                    )
                else:
                    if sequence_obj.last_value:
                        next_sample_unique_id = (
                            sample_ingestion.increase_sample_unique_id(
                                sequence_obj.last_value
                            )
                        )
                    else:
                        next_sample_unique_id = (
                            sample_ingestion.get_initial_sample_unique_id()
                        )
                    sequence_obj.last_value = next_sample_unique_id
                    sequence_obj.save(update_fields=["last_value"])

                sample_obj = core.models.Sample.objects.create(
                    sample_unique_id=next_sample_unique_id,
                    fingerprint=sample_create_data["fingerprint"],
                    schema_obj=sample_create_data["schema_obj"],
                    user=access_control.get_persisted_user(request.user),
                    **sample_create_data["defaults"],
                )
                created = True
        except IntegrityError:
            existing_sample = sample_ingestion.get_existing_sample(
                serializer.validated_data
            )
            if existing_sample:
                core.api.utils.common_functions.record_sample_error(
                    existing_sample,
                    core.api.utils.common_functions.map_error_name(
                        "Sample already exists"
                    ),
                )
                return Response(
                    {
                        "error": "Sample already exists",
                        "sample_unique_id": existing_sample.sample_unique_id,
                        "sequencing_sample_id": existing_sample.sequencing_sample_id,
                        "submitting_lab_sample_id": existing_sample.submitting_lab_sample_id,
                    },
                    status=status.HTTP_409_CONFLICT,
                )
            return Response(
                {"error": "Sample already exists", **traceability_data},
                status=status.HTTP_409_CONFLICT,
            )
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

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
@permission_classes([IsAuthenticated, HasProjectAccess])
def schema_create(request, project_name):
    serializer = core.api.v1.serializers.SchemaIngestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    payload = dict(serializer.validated_data)
    payload["schema_app_name"] = project_name

    try:
        schema_create_data = schema_ingestion.prepare_schema_create(
            payload, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        error_message = str(exc)
        if error_message == "Schema already exists":
            return Response({"error": error_message}, status=status.HTTP_409_CONFLICT)
        return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    # TODO: Re-evaluate whether large transaction-wrapped persistence blocks
    # should remain in views or be moved to a more readable orchestration layer.
    with transaction.atomic():
        deactivate_filter = schema_create_data["deactivate_existing_filter"]
        if deactivate_filter:
            core.models.Schema.objects.filter(**deactivate_filter).update(
                schema_in_use=False
            )

        schema_obj = core.models.Schema.objects.create(
            **schema_create_data["schema_fields"]
        )

        classification_cache = {}
        properties_count = 0
        for property_spec in schema_create_data["property_specs"]:
            classification_obj = None
            classification_name = property_spec["classification_name"]
            if classification_name:
                classification_cache_key = classification_name.lower()
                classification_obj = classification_cache.get(classification_cache_key)
                if classification_obj is None:
                    classification_obj = core.models.Classification.objects.filter(
                        classification_name__iexact=classification_name
                    ).last()
                    if classification_obj is None:
                        classification_obj = core.models.Classification.objects.create(
                            classification_name=classification_name
                        )
                    classification_cache[classification_cache_key] = classification_obj

            property_obj = core.models.SchemaProperties.objects.create(
                schemaID=schema_obj,
                classificationID=classification_obj,
                property=property_spec["property"],
                examples=property_spec["examples"],
                ontology=property_spec["ontology"],
                type=property_spec["type"],
                format=property_spec["format"],
                description=property_spec["description"],
                label=property_spec["label"],
                required=property_spec["required"],
                options=property_spec["options"],
                fill_mode=property_spec["fill_mode"],
            )
            properties_count += 1

            for enum_item in property_spec["enum_values"]:
                core.models.PropertyOptions.objects.create(
                    propertyID=property_obj,
                    enum=enum_item,
                    ontology=property_spec["ontology"],
                )

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
                "sample_unique_id": "SAM-AAA-0001",
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
                    "sample_unique_id": "SAM-AAA-0001",
                    "state": "Defined",
                    "error_name": "No error",
                    "is_current": False,
                    "changed_at": "2026-02-24T09:34:57.167046",
                },
                {
                    "sample_unique_id": "SAM-AAA-0001",
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
                    "sample_unique_id": "SAM-AAA-0001",
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
                    "sample_unique_id": "SAM-AAA-0001",
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
                "sample_unique_id": "SAM-AAA-0001",
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
    try:
        access_control.ensure_sample_write_access(sample_obj, request.user)
        schema_obj = sample_metadata_ingestion.resolve_sample_metadata_schema(
            sample_obj,
            schema_name=schema_name,
            schema_version=schema_version,
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        error_message = str(exc)
        core.api.utils.common_functions.record_sample_error(
            sample_obj,
            core.api.utils.common_functions.map_error_name(error_message),
        )
        return Response(
            {"error": error_message},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        metadata_create_specs = (
            sample_metadata_ingestion.prepare_sample_metadata_create(
                sample_obj, schema_obj, payload
            )
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

    with transaction.atomic():
        for metadata_create_spec in metadata_create_specs:
            core.models.MetadataValues.objects.create(**metadata_create_spec)
    stored_count = len(metadata_create_specs)

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


@extend_schema(
    tags=[TAG_DATABROWSER],
    summary="Databrowser overview summary",
    description=(
        "Return authenticated global overview aggregates for the generic web "
        "databrowser. This endpoint exposes a database-level snapshot, is not "
        "scoped by project/user and does not support query parameters."
    ),
    parameters=[],
    responses={
        200: core.api.v1.serializers.DatabrowserOverviewSummarySerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
    },
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def databrowser_overview_summary_view(request):
    query_params_error = _reject_generic_databrowser_query_params(
        request, "overview-summary"
    )
    if query_params_error is not None:
        return query_params_error
    response_data = databrowser.overview_summary({}, request_user=None)
    response_serializer = core.api.v1.serializers.DatabrowserOverviewSummarySerializer(
        data=response_data
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_DATABROWSER],
    summary="Databrowser metadata summary",
    description=(
        "Return authenticated global priority metadata sections already "
        "aggregated in the backend. This endpoint is not scoped by "
        "project/user and does not support query parameters."
    ),
    parameters=[],
    responses={
        200: core.api.v1.serializers.DatabrowserMetadataSummarySerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
    },
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def databrowser_metadata_summary_view(request):
    query_params_error = _reject_generic_databrowser_query_params(
        request, "metadata-summary"
    )
    if query_params_error is not None:
        return query_params_error
    response_data = databrowser.metadata_summary({}, request_user=None)
    response_serializer = core.api.v1.serializers.DatabrowserMetadataSummarySerializer(
        data=response_data
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_DATABROWSER],
    summary="Databrowser metadata property distribution",
    description=(
        "Return the authenticated global distribution for one metadata "
        "property using backend aggregation. The response keeps the flat "
        "`values` distribution and also includes flexible frontend-ready "
        "cards plus pathogen, year and location breakdowns. This endpoint is "
        "not scoped by project/user. Only the `property` query parameter is "
        "supported."
    ),
    parameters=[core.api.v1.serializers.DatabrowserPropertyDistributionQuerySerializer],
    responses={
        200: core.api.v1.serializers.DatabrowserPropertyDistributionSerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
    },
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def databrowser_metadata_property_distribution_view(request):
    query_params_error = _reject_generic_databrowser_query_params(
        request,
        "metadata/property-distribution",
        allowed_params={"property"},
    )
    if query_params_error is not None:
        return query_params_error
    serializer = core.api.v1.serializers.DatabrowserPropertyDistributionQuerySerializer(
        data=request.query_params
    )
    serializer.is_valid(raise_exception=True)
    try:
        response_data = databrowser.property_distribution(
            serializer.validated_data, request_user=None
        )
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    response_serializer = (
        core.api.v1.serializers.DatabrowserPropertyDistributionSerializer(
            data=response_data
        )
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_DATABROWSER],
    summary="Databrowser schema summary",
    description=(
        "Return authenticated global schema cards, classification distribution "
        "and sample counts per schema without downloading every schema JSON "
        "detail in the frontend. This endpoint is not scoped by project/user "
        "and does not support query parameters."
    ),
    parameters=[],
    responses={
        200: core.api.v1.serializers.DatabrowserSchemaSummarySerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
    },
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def databrowser_schema_summary_view(request):
    query_params_error = _reject_generic_databrowser_query_params(
        request, "schema-summary"
    )
    if query_params_error is not None:
        return query_params_error
    response_data = databrowser.schema_summary({}, request_user=None)
    response_serializer = core.api.v1.serializers.DatabrowserSchemaSummarySerializer(
        data=response_data
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_VARIANTS],
    summary="Search genomic variants",
    description=(
        "Search visible per-sample genomic variants by HGVS genomic notation "
        "(`g.<position><ref>><alt>`) or by position/ref/alt query parameters. "
        "The same project scope rules used by sample endpoints are applied."
    ),
    parameters=[core.api.v1.serializers.VariantSearchQuerySerializer],
    responses={
        200: core.api.v1.serializers.VariantSearchResponseSerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
    },
    examples=[
        OpenApiExample(
            "VariantSearchByHGVS",
            value={
                "query": {
                    "variant": "g.112534G>C",
                    "position": 112534,
                    "reference_allele": "G",
                    "alternate_allele": "C",
                    "reference_genome": "NC_045512.2",
                },
                "summary": {
                    "sample_count": 3,
                    "visible_sample_count": 9,
                    "global_allele_frequency": 0.3333,
                },
                "count": 3,
                "next": None,
                "previous": None,
                "results": [
                    {
                        "sample_id": "SAM-AAA-0010",
                        "variant": "g.112534G>C",
                        "position": 112534,
                        "reference_allele": "G",
                        "alternate_allele": "C",
                        "allele_frequency": 0.82,
                        "effect": "missense_variant",
                        "depth": 45,
                        "type": "SNV",
                        "gene_region": "coding_sequence",
                        "functional_class": "missense",
                        "locus_name": "S",
                        "locus_id": "YP_009724390.1",
                        "aminoacid_change": "p.D614G",
                        "collection_date": "2025-10-21",
                        "sequencing_platform": "Illumina [OBI:0000759]",
                        "reference_genome": "NC_045512.2",
                        "analysis_date": "2026-04-06",
                        "project_name": "relecov",
                    }
                ],
            },
            response_only=True,
            status_codes=["200"],
        )
    ],
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def variant_search_view(request):
    serializer = core.api.v1.serializers.VariantSearchQuerySerializer(
        data=request.query_params
    )
    serializer.is_valid(raise_exception=True)
    try:
        search_result = variant_search.search_variants(
            serializer.validated_data, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    queryset = search_result["queryset"]
    if not queryset.exists():
        return Response(
            {"error": "No variants found"}, status=status.HTTP_404_NOT_FOUND
        )

    paginator = VariantsPagination()
    try:
        page = paginator.paginate_queryset(queryset, request)
    except NotFound as exc:
        return Response({"error": str(exc.detail)}, status=status.HTTP_404_NOT_FOUND)

    results = variant_search.serialize_search_results(page)
    response_data = {
        "query": search_result["query"],
        "summary": search_result["summary"],
        "count": paginator.page.paginator.count,
        "next": paginator.get_next_link(),
        "previous": paginator.get_previous_link(),
        "results": results,
    }
    response_serializer = core.api.v1.serializers.VariantSearchResponseSerializer(
        data=response_data
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_VARIANTS],
    summary="Summarize visible genomic variants",
    parameters=[core.api.v1.serializers.VariantFilterQuerySerializer],
    responses={
        200: core.api.v1.serializers.VariantSummaryResponseSerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
    },
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def variant_summary_view(request):
    serializer = core.api.v1.serializers.VariantFilterQuerySerializer(
        data=request.query_params
    )
    serializer.is_valid(raise_exception=True)
    try:
        response_data = variant_search.variant_summary(
            serializer.validated_data, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    response_serializer = core.api.v1.serializers.VariantSummaryResponseSerializer(
        data=response_data
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_VARIANTS],
    summary="List reference genomes observed in variant data",
    parameters=[core.api.v1.serializers.VariantFilterQuerySerializer],
    responses={
        200: core.api.v1.serializers.VariantReferenceGenomeSerializer(many=True),
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
    },
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def variant_reference_genomes_view(request):
    serializer = core.api.v1.serializers.VariantFilterQuerySerializer(
        data=request.query_params
    )
    serializer.is_valid(raise_exception=True)
    try:
        response_data = variant_search.reference_genomes(
            serializer.validated_data, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    response_serializer = core.api.v1.serializers.VariantReferenceGenomeSerializer(
        data=response_data, many=True
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_VARIANTS],
    summary="List filter options for visible variant data",
    parameters=[core.api.v1.serializers.VariantFilterQuerySerializer],
    responses={
        200: core.api.v1.serializers.VariantFilterOptionsSerializer,
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
    },
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def variant_filter_options_view(request):
    serializer = core.api.v1.serializers.VariantFilterQuerySerializer(
        data=request.query_params
    )
    serializer.is_valid(raise_exception=True)
    try:
        response_data = variant_search.filter_options(
            serializer.validated_data, request_user=request.user
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    response_serializer = core.api.v1.serializers.VariantFilterOptionsSerializer(
        data=response_data
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    tags=[TAG_VARIANTS],
    summary="Ingest genomic variants",
    description=(
        "Store normalized per-sample genomic variants. The endpoint accepts the "
        "single-sample JSON envelope (`sample_id`, `analysis_date`, `variants`) "
        "and long-table JSON records (`sample_name`, "
        "`bioinformatics_analysis_date`, `variants`). Writes are processed in "
        "chunks and are idempotent per sample and analysis date."
    ),
    parameters=[
        OpenApiParameter(
            name="chunk_size",
            type=int,
            required=False,
            location=OpenApiParameter.QUERY,
            description=(
                "Bulk ingest batch size, not pagination. Default 1000, max 5000. "
                "It limits how many input variants are processed per database batch "
                "to balance memory usage and SQL statement size."
            ),
        )
    ],
    request=core.api.v1.serializers.VariantIngestSerializer,
    responses={
        201: core.api.v1.serializers.VariantIngestResponseSerializer,
        400: core.api.v1.serializers.VariantIngestResponseSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.VariantIngestResponseSerializer,
    },
    examples=[
        OpenApiExample(
            "VariantIngestRequest",
            request_only=True,
            value={
                "sample_id": "SAM-AAA-0010",
                "analysis_date": "2026-04-06",
                "variants": [
                    {
                        "chrom": "NC_045512.2",
                        "pos": 112534,
                        "ref": "G",
                        "alt": "C",
                        "depth": 45,
                        "allele_frequency": 0.82,
                        "gene_region": "coding",
                        "effect": "missense_variant",
                        "locus_name": "blaKPC",
                        "locus_id": "KPC-2",
                        "aminoacid_change": "K234R",
                    }
                ],
            },
        ),
        OpenApiExample(
            "VariantIngestResponse",
            response_only=True,
            status_codes=["201"],
            value={
                "data": {
                    "samples_processed": 1,
                    "variants_received": 1,
                    "sample_variants_stored": 1,
                    "sample_variants_replaced": 0,
                    "distinct_variants_seen": 1,
                    "annotations_seen": 1,
                },
                "success": True,
                "errors": [],
            },
        ),
    ],
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def variant_ingest_view(request):
    serializer = core.api.v1.serializers.VariantIngestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        chunk_size = int(request.query_params.get("chunk_size", "1000"))
    except ValueError:
        return Response(
            {"data": {}, "success": False, "errors": ["chunk_size must be an integer"]},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if chunk_size < 1 or chunk_size > 5000:
        return Response(
            {
                "data": {},
                "success": False,
                "errors": ["chunk_size must be between 1 and 5000"],
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        ingest_result = variant_ingestion.ingest_variants(
            serializer.validated_data["payload"],
            request_user=request.user,
            chunk_size=chunk_size,
        )
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
    except ValueError as exc:
        response_data = {"data": {}, "success": False, "errors": [str(exc)]}
        if str(exc).startswith("Sample not found:"):
            return Response(response_data, status=status.HTTP_404_NOT_FOUND)
        return Response(response_data, status=status.HTTP_400_BAD_REQUEST)
    except PermissionDenied as exc:
        return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)

    response_serializer = core.api.v1.serializers.VariantIngestResponseSerializer(
        data={"data": ingest_result, "success": True, "errors": []}
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_201_CREATED)
