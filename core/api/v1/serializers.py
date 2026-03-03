# Generic imports
from rest_framework import serializers

# Local imports
import core.models


class SampleIngestSerializer(serializers.ModelSerializer):
    # Input validation lives in serializer; persistence lives in service layer
    # because sample creation requires generated IDs and cross-model checks.
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
            "Preferred collecting identifier used for `sample_unique_id` hash. "
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
        attrs["collecting_id_for_hash"] = (
            collecting_isolate_id or collecting_sample_id
        )
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


class SchemaIngestSerializer(serializers.Serializer):
    # This serializer validates/normalizes schema payload shape only.
    # Object creation and schema-property persistence happen in schema service.
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
        help_text="Mark this schema version as in-use (default: true).",
    )
    schema_default = serializers.BooleanField(
        required=False,
        help_text="Mark this schema version as default (requires schema_in_use=true).",
    )

    def validate(self, attrs):
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
    schema_default = serializers.BooleanField()
    status = serializers.CharField()


class SchemaListFilterSerializer(serializers.Serializer):
    schema_name = serializers.CharField(required=False, allow_blank=False)
    schema_version = serializers.CharField(required=False, allow_blank=False)
    schema_in_use = serializers.BooleanField(required=False)
    schema_default = serializers.BooleanField(required=False)
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
        if "schema_default" not in self.initial_data:
            attrs.pop("schema_default", None)
        return attrs


class SchemaListItemSerializer(serializers.ModelSerializer):
    project_name = serializers.CharField(source="schema_app_name", read_only=True)

    class Meta:
        model = core.models.Schema
        fields = [
            "schema_name",
            "schema_version",
            "schema_in_use",
            "schema_default",
            "project_name",
            "generated_at",
        ]


class SchemaDetailSerializer(serializers.Serializer):
    schema_name = serializers.CharField()
    schema_version = serializers.CharField()
    schema_in_use = serializers.BooleanField()
    schema_default = serializers.BooleanField()
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
        child=serializers.CharField(allow_blank=False), required=False, allow_empty=False
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
    values = serializers.DictField(
        child=serializers.CharField(allow_null=True, allow_blank=True)
    )


class SampleMetadataIngestSerializer(serializers.Serializer):
    # This serializer validates ingest envelope fields.
    # Metadata persistence and schema-property checks are handled in service layer.
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
