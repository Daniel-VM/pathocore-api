# Generic imports
from rest_framework import serializers

# Local imports
import core.models


class SampleIngestSerializer(serializers.ModelSerializer):
    # Input validation lives in serializer. Persistence is orchestrated in views,
    # while services prepare derived values and domain checks.
    # Extra fields not in the Sample model but needed for lookups/forward-compat.
    schema_name = serializers.CharField(
        required=True, allow_blank=False, allow_null=False, write_only=True
    )
    schema_version = serializers.CharField(
        required=True, allow_blank=False, allow_null=False, write_only=True
    )
    authors = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, write_only=True
    )
    sequencing_sample_id = serializers.CharField(
        required=False,
        allow_blank=False,
        allow_null=True,
        help_text="Sequencing identifier from the laboratory (optional).",
    )
    collecting_lab_sample_id = serializers.CharField(
        required=False,
        allow_blank=False,
        allow_null=True,
        help_text=(
            "Collecting lab sample ID. Required only when "
            "`collecting_lab_isolate_id` is not provided."
        ),
    )
    collecting_lab_isolate_id = serializers.CharField(
        required=False,
        allow_blank=False,
        allow_null=True,
        help_text=(
            "Preferred collecting identifier used for fingerprint generation. "
            "If absent, `collecting_lab_sample_id` is used."
        ),
    )
    sequencing_isolate_id = serializers.CharField(
        required=False, allow_blank=False, allow_null=True
    )
    submitting_lab_isolate_id = serializers.CharField(
        required=False, allow_blank=False, allow_null=True
    )
    submitting_lab_sample_id = serializers.CharField(
        required=True,
        allow_blank=False,
        allow_null=False,
        help_text="Submitting laboratory sample identifier (required).",
    )
    collecting_institution = serializers.CharField(
        required=True,
        allow_blank=False,
        allow_null=False,
        help_text="Collecting institution name (required).",
    )
    # Accept both formats for ingest compatibility:
    # `YYYY-MM-DD` and full ISO datetime (`YYYY-MM-DDThh:mm[:ss][Z|+HH:MM]`).
    sequencing_date = serializers.DateTimeField(
        required=False,
        allow_null=True,
        input_formats=["iso-8601", "%Y-%m-%d"],
        help_text=(
            "Sequencing date. Accepted formats: full ISO-8601 datetime or YYYY-MM-DD. "
            "'Not Provided' placeholders are normalized to null."
        ),
    )
    sequence_file_path_r1 = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        source="r1_fastq_filepath",
        help_text="Absolute/relative path for FASTQ R1 file.",
    )
    sequence_file_path_r2 = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        source="r2_fastq_filepath",
        help_text="Absolute/relative path for FASTQ R2 file.",
    )

    class Meta:
        model = core.models.Sample
        fields = [
            "sequencing_sample_id",
            "authors",
            "collecting_institution",
            "collecting_lab_sample_id",
            "collecting_lab_isolate_id",
            "sequencing_isolate_id",
            "microbiology_lab_sample_id",
            "submitting_lab_sample_id",
            "submitting_lab_isolate_id",
            "schema_name",
            "schema_version",
            "sequencing_date",
            "sequence_file_R1_md5",
            "sequence_file_R2_md5",
            "sequence_file_path_r1",
            "sequence_file_path_r2",
        ]

    def to_internal_value(self, data):
        # Accept payload keys case-insensitively across projects
        # (e.g. sequence_file_path_R1 vs sequence_file_path_r1).
        if isinstance(data, dict):
            normalized = dict(data)
            field_map = {name.lower(): name for name in self.fields.keys()}
            for key, value in data.items():
                canonical = field_map.get(str(key).lower())
                if canonical and canonical not in normalized:
                    normalized[canonical] = value
            # Accept known "not provided" placeholders for nullable datetimes.
            # sequencing_date still supports both YYYY-MM-DD and ISO datetime.
            sequencing_date = normalized.get("sequencing_date")
            if isinstance(sequencing_date, str):
                if sequencing_date.strip().lower().startswith("not provided"):
                    normalized["sequencing_date"] = None
            data = normalized
        return super().to_internal_value(data)

    def validate(self, attrs):
        collecting_sample_id = attrs.get("collecting_lab_sample_id")
        collecting_isolate_id = attrs.get("collecting_lab_isolate_id")
        if not collecting_sample_id and not collecting_isolate_id:
            raise serializers.ValidationError(
                {
                    "error": (
                        "collecting_lab_isolate_id is expected. "
                        "If it is not available, collecting_lab_sample_id is required."
                    )
                }
            )
        # Priority for hash generation: isolate_id first, then sample_id fallback.
        attrs["collecting_id_for_hash"] = collecting_isolate_id or collecting_sample_id
        return attrs


class SampleStateHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = core.models.SampleStateHistory
        fields = "__all__"


class SampleHistoryItemSerializer(serializers.ModelSerializer):
    sample_unique_id = serializers.CharField(
        source="sample.sample_unique_id", read_only=True
    )
    state = serializers.CharField(source="state.state", read_only=True)
    error_name = serializers.CharField(source="error_name.error_name", read_only=True)

    class Meta:
        model = core.models.SampleStateHistory
        fields = [
            "sample_unique_id",
            "state",
            "error_name",
            "is_current",
            "changed_at",
        ]


class SampleIngestResponseSerializer(serializers.Serializer):
    sample_unique_id = serializers.CharField()
    sequencing_sample_id = serializers.CharField(allow_null=True, allow_blank=True)
    created = serializers.BooleanField()
    status = serializers.CharField()


class ErrorSerializer(serializers.Serializer):
    error = serializers.CharField()


class AccessRequestCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    requested_use_case = serializers.CharField(max_length=80)
    requested_lab = serializers.CharField(
        max_length=80,
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    requested_role = serializers.ChoiceField(choices=["view", "admin"])
    message = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=2000,
    )

    def validate(self, attrs):
        from core.api.services import access_requests

        attrs = access_requests.normalize_request_fields(dict(attrs))
        return access_requests.validate_requested_scope(attrs)


class AccessRequestReviewSerializer(serializers.Serializer):
    review_note = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=2000,
    )


class AccessRequestListQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["pending", "approved", "rejected", "revoked"],
        required=False,
    )


class AccessRequestSerializer(serializers.ModelSerializer):
    reviewed_by_username = serializers.CharField(
        source="reviewed_by.username",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = core.models.AccessRequest
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "requested_use_case",
            "requested_lab",
            "requested_role",
            "message",
            "status",
            "created_at",
            "reviewed_at",
            "reviewed_by",
            "reviewed_by_username",
            "reviewed_by_identity",
            "review_note",
            "approved_group",
            "keycloak_user_id",
        ]
        read_only_fields = [
            "id",
            "status",
            "created_at",
            "reviewed_at",
            "reviewed_by",
            "reviewed_by_username",
            "reviewed_by_identity",
            "review_note",
            "approved_group",
            "keycloak_user_id",
        ]


class SchemaIngestSerializer(serializers.Serializer):
    # This serializer validates/normalizes schema payload shape only.
    # Views persist the schema objects; services prepare normalized create data.
    # Input is raw JSON schema (not a FileField), so we validate title/version here
    # and later convert the JSON into a file for Schema.file_name in the service.
    schema = serializers.JSONField(
        required=True,
        help_text="Schema JSON object.",
    )
    schema_name = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Optional override for schema title. Defaults to schema.title",
    )
    schema_version = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Optional override for schema version. Defaults to schema.version",
    )
    schema_in_use = serializers.BooleanField(
        required=False,
        help_text=(
            "Mark this schema version as active. If omitted, the uploaded schema "
            "becomes the active one for the same project and schema name."
        ),
    )

    def validate(self, attrs):
        allowed_keys = set(self.fields.keys())
        provided_keys = set(self.initial_data.keys())
        unknown_keys = provided_keys - allowed_keys
        if unknown_keys:
            raise serializers.ValidationError(
                {"error": f"Unknown field(s): {', '.join(sorted(unknown_keys))}"}
            )

        schema = attrs.get("schema")
        if not isinstance(schema, dict):
            raise serializers.ValidationError({"error": "schema must be a JSON object"})

        title = schema.get("title")
        version = schema.get("version")
        if not title or not isinstance(title, str) or not title.strip():
            raise serializers.ValidationError({"error": "schema title is required"})
        if not version or not isinstance(version, str) or not version.strip():
            raise serializers.ValidationError({"error": "schema version is required"})

        # If not explicitly provided, derive from schema file.
        attrs.setdefault("schema_name", title.strip())
        attrs.setdefault("schema_version", version.strip())
        attrs["schema"] = schema
        return attrs


class SchemaIngestResponseSerializer(serializers.Serializer):
    schema_name = serializers.CharField()
    schema_version = serializers.CharField()
    project_name = serializers.CharField()
    properties_count = serializers.IntegerField()
    schema_in_use = serializers.BooleanField()
    status = serializers.CharField()


class SchemaListFilterSerializer(serializers.Serializer):
    schema_name = serializers.CharField(required=False, allow_blank=False)
    schema_version = serializers.CharField(required=False, allow_blank=False)
    schema_in_use = serializers.BooleanField(required=False)
    project_name = serializers.CharField(required=False, allow_blank=False)

    def validate(self, attrs):
        allowed_keys = set(self.fields.keys())
        provided_keys = set(self.initial_data.keys())
        unknown_keys = provided_keys - allowed_keys
        if unknown_keys:
            raise serializers.ValidationError(
                {"error": f"Unknown filter(s): {', '.join(sorted(unknown_keys))}"}
            )
        project_name = attrs.get("project_name")
        if project_name:
            attrs["schema_app_name"] = project_name
        if "schema_in_use" not in self.initial_data:
            attrs.pop("schema_in_use", None)
        return attrs


class SchemaListItemSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source="schema_app_name", read_only=True)

    class Meta:
        model = core.models.Schema
        fields = [
            "schema_name",
            "schema_version",
            "schema_in_use",
            "project_name",
            "generated_at",
        ]


class SchemaDetailSerializer(serializers.Serializer):
    schema_name = serializers.CharField()
    schema_version = serializers.CharField()
    schema_in_use = serializers.BooleanField()
    project_name = serializers.CharField(allow_null=True, allow_blank=True)
    generated_at = serializers.DateTimeField(allow_null=True)
    schema = serializers.JSONField()


# TODO: Add or remove request filters.
class SampleFilterSerializer(serializers.Serializer):
    sample_unique_id = serializers.CharField(required=False, allow_blank=False)
    sequencing_sample_id = serializers.CharField(required=False, allow_blank=False)
    collecting_institution = serializers.CharField(required=False, allow_blank=False)
    collecting_lab_sample_id = serializers.CharField(required=False, allow_blank=False)
    microbiology_lab_sample_id = serializers.CharField(
        required=False, allow_blank=False
    )
    submitting_lab_sample_id = serializers.CharField(required=False, allow_blank=False)
    schema_name = serializers.CharField(required=False, allow_blank=False)
    schema_version = serializers.CharField(required=False, allow_blank=False)
    created_at_from = serializers.DateTimeField(required=False)
    created_at_to = serializers.DateTimeField(required=False)
    sequencing_date_from = serializers.DateTimeField(required=False)
    sequencing_date_to = serializers.DateTimeField(required=False)
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=5000)

    def validate(self, attrs):
        allowed_keys = set(self.fields.keys())
        provided_keys = set(self.initial_data.keys())
        unknown_keys = provided_keys - allowed_keys
        if unknown_keys:
            raise serializers.ValidationError(
                {"error": f"Unknown filter(s): {', '.join(sorted(unknown_keys))}"}
            )
        return attrs


class SampleHistoryFilterSerializer(serializers.Serializer):
    sample_id = serializers.IntegerField(required=False)
    sample_unique_id = serializers.CharField(required=False, allow_blank=False)
    sequencing_sample_id = serializers.CharField(required=False, allow_blank=False)
    submitting_lab_sample_id = serializers.CharField(required=False, allow_blank=False)
    collecting_lab_isolate_id = serializers.CharField(required=False, allow_blank=False)
    collecting_lab_sample_id = serializers.CharField(required=False, allow_blank=False)
    state_id = serializers.IntegerField(required=False)
    state = serializers.CharField(required=False, allow_blank=False)
    error_name_id = serializers.IntegerField(required=False)
    error_name = serializers.CharField(required=False, allow_blank=False)
    is_current = serializers.BooleanField(required=False)
    changed_at_from = serializers.DateTimeField(required=False)
    changed_at_to = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        allowed_keys = set(self.fields.keys())
        provided_keys = set(self.initial_data.keys())
        unknown_keys = provided_keys - allowed_keys
        if unknown_keys:
            raise serializers.ValidationError(
                {"error": f"Unknown filter(s): {', '.join(sorted(unknown_keys))}"}
            )
        if "is_current" not in self.initial_data:
            attrs.pop("is_current", None)
        return attrs


# TODO: Add or remove response filters.
class SampleListItemSerializer(serializers.ModelSerializer):
    schema_name = serializers.CharField(source="schema_obj.schema_name", read_only=True)
    schema_version = serializers.CharField(
        source="schema_obj.schema_version", read_only=True
    )

    class Meta:
        model = core.models.Sample
        fields = [
            "sample_unique_id",
            "sequencing_sample_id",
            # "collecting_institution",
            "created_at",
            "schema_name",
            "schema_version",
        ]


class SampleListPaginatedResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = SampleListItemSerializer(many=True)


# TODO: Decide response fields for sample detail.
class SampleDetailSerializer(serializers.ModelSerializer):
    schema_name = serializers.CharField(source="schema_obj.schema_name", read_only=True)
    schema_version = serializers.CharField(
        source="schema_obj.schema_version", read_only=True
    )

    class Meta:
        model = core.models.Sample
        fields = [
            "sample_unique_id",
            "sequencing_sample_id",
            "microbiology_lab_sample_id",
            "collecting_lab_sample_id",
            "submitting_lab_sample_id",
            "collecting_institution",
            "sequence_file_R1_md5",
            "sequence_file_R2_md5",
            "r1_fastq_filepath",
            "r2_fastq_filepath",
            "sequencing_date",
            "created_at",
            "schema_name",
            "schema_version",
        ]


class SampleMetadataFilterSerializer(serializers.Serializer):
    classification = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=False
    )
    property = serializers.ListField(
        child=serializers.CharField(), required=False, allow_empty=False
    )


class SampleMetadataPropertyFilterSerializer(serializers.Serializer):
    property = serializers.CharField(required=True, allow_blank=False)
    value = serializers.CharField(required=False, allow_blank=False)


class SampleMetadataPropertyQuerySerializer(serializers.Serializer):
    classification = serializers.CharField(required=False, allow_blank=False)
    property = serializers.CharField(required=False, allow_blank=False)
    value = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        allow_empty=False,
    )
    match = serializers.ChoiceField(
        choices=["all", "any"], required=False, default="any"
    )

    def validate(self, attrs):
        classification = attrs.get("classification")
        property_name = attrs.get("property")
        values = attrs.get("value")

        # classification-only requests are handled by the dedicated branch.
        if classification and not property_name and not values:
            return attrs

        if not property_name and not values:
            raise serializers.ValidationError(
                {"error": "Provide at least one of: property or value"}
            )
        return attrs


class SampleMetadataClassificationFilterSerializer(serializers.Serializer):
    classification = serializers.CharField(required=True, allow_blank=False)


class SampleMetadataSearchSerializer(serializers.Serializer):
    filter = serializers.ListField(child=serializers.CharField(), allow_empty=False)
    match = serializers.ChoiceField(
        choices=["all", "any"], required=False, default="all"
    )


# FIXME: point to metadata values model instead
class SampleMetadataItemSerializer(serializers.Serializer):
    property = serializers.CharField()
    value = serializers.CharField(allow_null=True, allow_blank=True)

    def to_representation(self, instance):
        if isinstance(instance, dict):
            property_name = instance.get("property")
            value = instance.get("value")
        else:
            property_name = getattr(instance, "property", None)
            value = getattr(instance, "value", None)
        return {property_name: value}


class SampleMetadataPropertyResultSerializer(serializers.Serializer):
    sample_unique_id = serializers.CharField()
    value = serializers.CharField(allow_null=True, allow_blank=True)


class SampleMetadataClassificationResultSerializer(serializers.Serializer):
    property = serializers.CharField()

    def to_representation(self, instance):
        if isinstance(instance, dict):
            property_name = instance.get("property")
        else:
            property_name = getattr(instance, "property", None)
        return {property_name: None}


class SampleMetadataSearchResultSerializer(serializers.Serializer):
    sample_unique_id = serializers.CharField()
    values = serializers.JSONField()


class SampleMetadataIngestSerializer(serializers.Serializer):
    # This serializer validates ingest envelope fields.
    # Views persist metadata values; services resolve schema and prepare create data.
    schema_name = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Optional schema title to validate metadata payload.",
    )
    schema_version = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="Optional schema version, must be sent together with schema_name.",
    )

    def validate(self, attrs):
        schema_name = attrs.get("schema_name")
        schema_version = attrs.get("schema_version")
        if (schema_name and not schema_version) or (schema_version and not schema_name):
            raise serializers.ValidationError(
                {"error": "schema_name and schema_version must be provided together"}
            )
        attrs["payload"] = self.initial_data
        return attrs


class SampleMetadataIngestResponseSerializer(serializers.Serializer):
    sample_unique_id = serializers.CharField()
    stored_count = serializers.IntegerField()
    status = serializers.CharField()


class VariantIngestSerializer(serializers.Serializer):
    payload = serializers.JSONField(required=True)

    def to_internal_value(self, data):
        # Accept the variant payload directly, without requiring a wrapper field.
        # This avoids a second large list allocation for high-volume ingests.
        return {"payload": data}

    def validate(self, attrs):
        payload = attrs["payload"]
        if not isinstance(payload, (dict, list)):
            raise serializers.ValidationError(
                {"error": "Payload must be a JSON object or a list of JSON objects"}
            )
        return attrs


class VariantIngestResponseSerializer(serializers.Serializer):
    data = serializers.DictField()
    success = serializers.BooleanField()
    errors = serializers.ListField(child=serializers.CharField())


class VariantSearchQuerySerializer(serializers.Serializer):
    variant = serializers.CharField(required=False, allow_blank=False)
    position = serializers.IntegerField(required=False, min_value=1)
    ref = serializers.CharField(required=False, allow_blank=False)
    alt = serializers.CharField(required=False, allow_blank=False)
    reference_genome = serializers.CharField(required=False, allow_blank=False)
    collection_date_from = serializers.DateField(required=False)
    collection_date_to = serializers.DateField(required=False)
    sequencing_platform = serializers.CharField(required=False, allow_blank=False)
    sample_id = serializers.CharField(required=False, allow_blank=False)
    locus_name = serializers.CharField(required=False, allow_blank=False)
    locus_id = serializers.CharField(required=False, allow_blank=False)
    effect = serializers.CharField(required=False, allow_blank=False)
    aminoacid_change = serializers.CharField(required=False, allow_blank=False)
    project_name = serializers.CharField(required=False, allow_blank=False)
    schema_name = serializers.CharField(required=False, allow_blank=False)
    schema_version = serializers.CharField(required=False, allow_blank=False)
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=5000)

    def validate(self, attrs):
        allowed_keys = set(self.fields.keys())
        provided_keys = set(self.initial_data.keys())
        unknown_keys = provided_keys - allowed_keys
        if unknown_keys:
            raise serializers.ValidationError(
                {"error": f"Unknown filter(s): {', '.join(sorted(unknown_keys))}"}
            )
        if not attrs.get("variant"):
            missing = [
                field_name
                for field_name in ("position", "ref", "alt")
                if not attrs.get(field_name)
            ]
            if missing:
                raise serializers.ValidationError(
                    {"error": "Provide variant or position/ref/alt"}
                )
        start = attrs.get("collection_date_from")
        end = attrs.get("collection_date_to")
        if start and end and start > end:
            raise serializers.ValidationError(
                {"error": "collection_date_from cannot be after collection_date_to"}
            )
        if attrs.get("ref"):
            attrs["ref"] = attrs["ref"].upper()
        if attrs.get("alt"):
            attrs["alt"] = attrs["alt"].upper()
        return attrs


class VariantFilterQuerySerializer(serializers.Serializer):
    reference_genome = serializers.CharField(required=False, allow_blank=False)
    collection_date_from = serializers.DateField(required=False)
    collection_date_to = serializers.DateField(required=False)
    sequencing_platform = serializers.CharField(required=False, allow_blank=False)
    sample_id = serializers.CharField(required=False, allow_blank=False)
    locus_name = serializers.CharField(required=False, allow_blank=False)
    locus_id = serializers.CharField(required=False, allow_blank=False)
    effect = serializers.CharField(required=False, allow_blank=False)
    aminoacid_change = serializers.CharField(required=False, allow_blank=False)
    project_name = serializers.CharField(required=False, allow_blank=False)
    schema_name = serializers.CharField(required=False, allow_blank=False)
    schema_version = serializers.CharField(required=False, allow_blank=False)
    created_at_from = serializers.DateTimeField(required=False)
    created_at_to = serializers.DateTimeField(required=False)

    def validate(self, attrs):
        allowed_keys = set(self.fields.keys())
        provided_keys = set(self.initial_data.keys())
        unknown_keys = provided_keys - allowed_keys
        if unknown_keys:
            raise serializers.ValidationError(
                {"error": f"Unknown filter(s): {', '.join(sorted(unknown_keys))}"}
            )
        collection_start = attrs.get("collection_date_from")
        collection_end = attrs.get("collection_date_to")
        if collection_start and collection_end and collection_start > collection_end:
            raise serializers.ValidationError(
                {"error": "collection_date_from cannot be after collection_date_to"}
            )
        created_start = attrs.get("created_at_from")
        created_end = attrs.get("created_at_to")
        if created_start and created_end and created_start > created_end:
            raise serializers.ValidationError(
                {"error": "created_at_from cannot be after created_at_to"}
            )
        return attrs


class VariantSearchResultSerializer(serializers.Serializer):
    sample_id = serializers.CharField()
    variant = serializers.CharField()
    position = serializers.IntegerField()
    reference_allele = serializers.CharField()
    alternate_allele = serializers.CharField()
    allele_frequency = serializers.FloatField(allow_null=True)
    effect = serializers.CharField(allow_blank=True)
    depth = serializers.IntegerField(allow_null=True)
    type = serializers.CharField(allow_blank=True)
    gene_region = serializers.CharField(allow_blank=True)
    functional_class = serializers.CharField(allow_blank=True)
    locus_name = serializers.CharField(allow_blank=True)
    locus_id = serializers.CharField(allow_blank=True)
    aminoacid_change = serializers.CharField(allow_blank=True)
    collection_date = serializers.CharField(allow_null=True, allow_blank=True)
    sequencing_platform = serializers.CharField(allow_null=True, allow_blank=True)
    reference_genome = serializers.CharField()
    analysis_date = serializers.DateField()
    project_name = serializers.CharField(allow_null=True, allow_blank=True)


class VariantSearchSummarySerializer(serializers.Serializer):
    sample_count = serializers.IntegerField()
    visible_sample_count = serializers.IntegerField()
    global_allele_frequency = serializers.FloatField()


class VariantSearchResponseSerializer(serializers.Serializer):
    query = serializers.DictField()
    summary = VariantSearchSummarySerializer()
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True)
    previous = serializers.CharField(allow_null=True)
    results = VariantSearchResultSerializer(many=True)


class LabelValueSerializer(serializers.Serializer):
    label = serializers.CharField()
    value = serializers.IntegerField()


class VariantSummaryTotalsSerializer(serializers.Serializer):
    visible_sample_count = serializers.IntegerField()
    samples_with_variants = serializers.IntegerField()
    variant_observations = serializers.IntegerField()
    distinct_variants = serializers.IntegerField()


class VariantSummaryResponseSerializer(serializers.Serializer):
    totals = VariantSummaryTotalsSerializer()
    reference_genomes = LabelValueSerializer(many=True)
    variant_counts = LabelValueSerializer(many=True)
    impact_classes = LabelValueSerializer(many=True)
    projects = LabelValueSerializer(many=True)


class VariantReferenceGenomeSerializer(serializers.Serializer):
    reference_genome = serializers.CharField()
    sample_count = serializers.IntegerField()
    variant_observation_count = serializers.IntegerField()
    distinct_variant_count = serializers.IntegerField()


class VariantFilterOptionsSerializer(serializers.Serializer):
    collection_date = serializers.DictField()
    sequencing_platforms = serializers.ListField(child=serializers.DictField())


class DatabrowserPropertyDistributionQuerySerializer(serializers.Serializer):
    property = serializers.CharField(required=True, allow_blank=False)


class DatabrowserOverviewSummarySerializer(serializers.Serializer):
    kpis = serializers.ListField(child=serializers.DictField())
    sample_growth = serializers.ListField(child=serializers.DictField())
    pathogens = serializers.ListField(child=serializers.DictField())
    geography = serializers.ListField(child=serializers.DictField())
    schema_mix = serializers.ListField(child=serializers.DictField())
    projects = serializers.ListField(child=serializers.DictField())
    notes = serializers.ListField(child=serializers.CharField())
    coverage_notes = serializers.ListField(child=serializers.CharField())
    metrics = serializers.DictField()


class DatabrowserMetadataSummarySerializer(serializers.Serializer):
    schema_options = serializers.ListField(child=serializers.DictField())
    schema_scopes = serializers.ListField(child=serializers.DictField())
    sections = serializers.ListField(child=serializers.DictField())
    notes = serializers.ListField(child=serializers.CharField())
    stats = serializers.ListField(child=serializers.DictField())


class DatabrowserSchemaSummarySerializer(serializers.Serializer):
    stats = serializers.ListField(child=serializers.DictField())
    schema_distribution = serializers.ListField(child=serializers.DictField())
    classification_distribution = serializers.ListField(child=serializers.DictField())
    schema_cards = serializers.ListField(child=serializers.DictField())
    schema_options = serializers.ListField(child=serializers.DictField())
    notes = serializers.ListField(child=serializers.CharField())


class DatabrowserPropertyDistributionSerializer(serializers.Serializer):
    property = serializers.CharField()
    aliases = serializers.ListField(child=serializers.CharField())
    strategy = serializers.CharField()
    data_contract_version = serializers.CharField()
    coverage = serializers.DictField()
    metadata = serializers.DictField()
    total_samples = serializers.IntegerField()
    matched_samples = serializers.IntegerField()
    values = serializers.ListField(child=serializers.DictField())
    breakdowns = serializers.DictField()
    cards = serializers.ListField(child=serializers.DictField())
    ui_hints = serializers.DictField()


class UseCaseDataSummaryQuerySerializer(serializers.Serializer):
    project_name = serializers.CharField(required=True, allow_blank=False)

    def validate(self, attrs):
        allowed_keys = set(self.fields.keys())
        provided_keys = set(self.initial_data.keys())
        unknown_keys = provided_keys - allowed_keys
        if unknown_keys:
            raise serializers.ValidationError(
                {"error": f"Unknown filter(s): {', '.join(sorted(unknown_keys))}"}
            )
        return attrs


class UseCaseIsolateExplorerQuerySerializer(serializers.Serializer):
    project_name = serializers.CharField(required=True, allow_blank=False)
    search = serializers.CharField(required=False, allow_blank=True)
    pathogen = serializers.CharField(required=False, allow_blank=True)
    region = serializers.CharField(required=False, allow_blank=True)
    province = serializers.CharField(required=False, allow_blank=True)
    sequence_type = serializers.CharField(required=False, allow_blank=True)
    gene = serializers.CharField(required=False, allow_blank=True)
    allele = serializers.CharField(required=False, allow_blank=True)
    classification = serializers.CharField(required=False, allow_blank=True)
    bla_group = serializers.CharField(required=False, allow_blank=True)
    center = serializers.CharField(required=False, allow_blank=True)
    infection_type = serializers.CharField(required=False, allow_blank=True)
    collection_date_from = serializers.DateField(required=False)
    collection_date_to = serializers.DateField(required=False)
    page = serializers.IntegerField(required=False, min_value=1)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=5000)

    def validate(self, attrs):
        allowed_keys = set(self.fields.keys())
        provided_keys = set(self.initial_data.keys())
        unknown_keys = provided_keys - allowed_keys
        if unknown_keys:
            raise serializers.ValidationError(
                {"error": f"Unknown filter(s): {', '.join(sorted(unknown_keys))}"}
            )
        date_from = attrs.get("collection_date_from")
        date_to = attrs.get("collection_date_to")
        if date_from and date_to and date_from > date_to:
            raise serializers.ValidationError(
                {"error": "collection_date_from cannot be after collection_date_to"}
            )
        return attrs


class UseCaseDataSummarySerializer(serializers.Serializer):
    data_contract_version = serializers.CharField()
    project_name = serializers.CharField()
    project_label = serializers.CharField()
    generated_at = serializers.DateTimeField()
    project = serializers.DictField()
    cache = serializers.DictField()
    metrics = serializers.DictField()
    dimensions = serializers.DictField()
    time_series = serializers.DictField()
    geography = serializers.DictField()
    visualization_hints = serializers.DictField()
    overview = serializers.DictField()
    data_quality = serializers.DictField()


class UseCaseIsolateExplorerSerializer(serializers.Serializer):
    data_contract_version = serializers.CharField()
    project_name = serializers.CharField()
    project_label = serializers.CharField()
    generated_at = serializers.DateTimeField()
    project = serializers.DictField()
    query = serializers.DictField()
    columns = serializers.ListField(child=serializers.DictField())
    rows = serializers.ListField(child=serializers.DictField())
    filter_options = serializers.DictField()
    total_samples = serializers.IntegerField()
    matched_samples = serializers.IntegerField()
    total_loaded = serializers.IntegerField()
    data_quality = serializers.DictField()
    notes = serializers.ListField(child=serializers.CharField())
