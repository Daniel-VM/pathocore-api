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
from drf_spectacular.utils import (
    extend_schema,
    OpenApiExample,
    inline_serializer,
    OpenApiResponse,
    OpenApiParameter,
    extend_schema_view,
)
from rest_framework import serializers
from django.http import QueryDict

# Local imports
import core.models
import core.api.utils.samples
import core.api.v1.serializers
import core.api.utils.samples
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


@extend_schema_view(
    post=extend_schema(
        request=core.api.v1.serializers.SampleIngestSerializer,
        responses={
            200: core.api.v1.serializers.SampleIngestResponseSerializer,
            201: core.api.v1.serializers.SampleIngestResponseSerializer,
            400: core.api.v1.serializers.ErrorSerializer,
            404: core.api.v1.serializers.ErrorSerializer,
            409: core.api.v1.serializers.ErrorSerializer,
        },
    ),
    get=extend_schema(
        request=core.api.v1.serializers.SampleFilterSerializer,
        responses={
            200: core.api.v1.serializers.SampleListItemSerializer(many=True),
            401: core.api.v1.serializers.ErrorSerializer,
            404: core.api.v1.serializers.ErrorSerializer,
        },
    ),
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
        serializer = core.api.v1.serializers.SampleIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create/Ingest Sample
        try:
            sample_obj, created = sample_ingestion.ingest_sample(
                serializer.validated_data, request_user=request.user
            )
        except ValueError as exc:
            error_message = str(exc)
            if error_message == "Sample already exists":
                existing_sample = core.models.Sample.objects.filter(
                    sample_unique_id=serializer.validated_data.get("sample_unique_id")
                ).last()
                if existing_sample:
                    core.api.utils.common_functions.record_sample_error(
                        existing_sample,
                        core.api.utils.common_functions.map_error_name(error_message),
                    )
                return Response(
                    {"error": error_message}, status=status.HTTP_409_CONFLICT
                )
            return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

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
        queryset = sample_listing.list_samples(filter_serializer.validated_data)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not queryset.exists():
        return Response({"error": "No samples found"}, status=status.HTTP_404_NOT_FOUND)
    response_serializer = core.api.v1.serializers.SampleListItemSerializer(
        queryset, many=True
    )
    return Response(response_serializer.data, status=status.HTTP_200_OK)

@extend_schema(
    responses={
        200: core.api.v1.serializers.SampleDetailSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
    },
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sample_detail_view(request, sample_unique_id):
    sample_obj = sample_detail.get_sample_detail(sample_unique_id)
    if sample_obj is None:
        return Response({"error": "Sample not found"}, status=status.HTTP_404_NOT_FOUND)
    response_serializer = core.api.v1.serializers.SampleDetailSerializer(sample_obj)
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
    parameters=[
        inline_serializer(
            name="SampleHistoryQuery",
            fields={
                "sample_id": serializers.IntegerField(required=False),
                "sample_unique_id": serializers.CharField(required=False),
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
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sample_history_view(request):
    filter_serializer = core.api.v1.serializers.SampleHistoryFilterSerializer(
        data=request.query_params
    )
    filter_serializer.is_valid(raise_exception=True)
    queryset = sample_history.list_sample_history(filter_serializer.validated_data)
    if not queryset.exists():
        return Response({"error": "No history found"}, status=status.HTTP_404_NOT_FOUND)
    response_serializer = core.api.v1.serializers.SampleHistoryItemSerializer(
        queryset, many=True
    )
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
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
    queryset = sample_history.list_sample_history(
        {"sample_unique_id": sample_unique_id}
    )
    if not queryset.exists():
        return Response({"error": "No history found"}, status=status.HTTP_404_NOT_FOUND)
    response_serializer = core.api.v1.serializers.SampleHistoryItemSerializer(
        queryset, many=True
    )
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema(
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
            location=OpenApiParameter.QUERY,
            description="Optional value to match for the property",
        )
    ],
    responses={
        200: core.api.v1.serializers.SampleMetadataPropertyResultSerializer(many=True),
        400: core.api.v1.serializers.ErrorSerializer,
        401: core.api.v1.serializers.ErrorSerializer,
        403: core.api.v1.serializers.ErrorSerializer,
        404: core.api.v1.serializers.ErrorSerializer,
    },
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sample_metadata_property_view(request):
    classification = request.query_params.get("classification")
    property_name = request.query_params.get("property")

    if classification and property_name:
        return Response(
            {"error": "Use either classification or property, not both"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if classification:
        filter_serializer = (
            core.api.v1.serializers.SampleMetadataClassificationFilterSerializer(
                data={"classification": classification}
            )
        )
        filter_serializer.is_valid(raise_exception=True)
        try:
            results = sample_metadata.list_properties_by_classification(
                filter_serializer.validated_data["classification"]
            )
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

    filter_serializer = core.api.v1.serializers.SampleMetadataPropertyFilterSerializer(
        data=request.query_params
    )
    filter_serializer.is_valid(raise_exception=True)
    property_name = filter_serializer.validated_data["property"]
    value = filter_serializer.validated_data.get("value")

    try:
        results = sample_metadata.list_samples_by_property(property_name, value=value)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not results:
        return Response({"error": "No samples found"}, status=status.HTTP_404_NOT_FOUND)

    response_serializer = core.api.v1.serializers.SampleMetadataPropertyResultSerializer(
        results, many=True
    )
    return Response(response_serializer.data, status=status.HTTP_200_OK)


# TODO: Define response body
# TODO: not ready for complex fields
@extend_schema(
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
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sample_metadata_search_view(request):
    raw_filters = request.query_params.getlist("filter")
    data = {"filter": raw_filters}
    if "match" in request.query_params:
        data["match"] = request.query_params.get("match")
    filter_serializer = core.api.v1.serializers.SampleMetadataSearchSerializer(data=data)
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
            filters, match=filter_serializer.validated_data.get("match", "all")
        )
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    if not results:
        return Response({"error": "No samples found"}, status=status.HTTP_404_NOT_FOUND)

    response_serializer = core.api.v1.serializers.SampleMetadataSearchResultSerializer(
        results, many=True
    )
    return Response(response_serializer.data, status=status.HTTP_200_OK)


@extend_schema_view(
    get=extend_schema(
        responses={
            200: core.api.v1.serializers.SampleMetadataItemSerializer(many=True),
            401: core.api.v1.serializers.ErrorSerializer,
            403: core.api.v1.serializers.ErrorSerializer,
            404: core.api.v1.serializers.ErrorSerializer,
            400: core.api.v1.serializers.ErrorSerializer,
        },
    ),
    post=extend_schema(
        request=core.api.v1.serializers.SampleMetadataIngestSerializer,
        responses={
            201: core.api.v1.serializers.SampleMetadataIngestResponseSerializer,
            400: core.api.v1.serializers.ErrorSerializer,
            401: core.api.v1.serializers.ErrorSerializer,
            403: core.api.v1.serializers.ErrorSerializer,
            404: core.api.v1.serializers.ErrorSerializer,
            409: core.api.v1.serializers.ErrorSerializer,
        },
    ),
)
@authentication_classes([SessionAuthentication, BasicAuthentication])
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def sample_metadata_view(request, sample_unique_id):
    sample_obj = sample_detail.get_sample_detail(sample_unique_id)
    if sample_obj is None:
        return Response({"error": "Sample not found"}, status=status.HTTP_404_NOT_FOUND)
    # TODO: complex fields (grouped metadata) are not exposed yet.

    # GET method
    if request.method == "GET":
        metadata_list = sample_metadata.list_sample_metadata(
            sample_obj,
            classifications=None,
            properties=None,
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
    serializer = core.api.v1.serializers.SampleMetadataIngestSerializer(data=request.data)
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
            return Response(
                {"error": error_message}, status=status.HTTP_409_CONFLICT
            )
        core.api.utils.common_functions.record_sample_error(
            sample_obj,
            core.api.utils.common_functions.map_error_name(error_message),
        )
        return Response({"error": error_message}, status=status.HTTP_400_BAD_REQUEST)

    if stored_count:
        state_obj = core.models.SampleState.objects.filter(state__exact="Bioinfo").last()
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
    response_serializer = core.api.v1.serializers.SampleMetadataIngestResponseSerializer(
        data={
            "sample_unique_id": sample_unique_id,
            "stored_count": stored_count,
            "status": "stored" if stored_count else "no_changes",
        }
    )
    response_serializer.is_valid(raise_exception=True)
    return Response(response_serializer.data, status=status.HTTP_201_CREATED)
