# Generic imports
from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.exceptions import ObjectDoesNotExist

# Local imports
import core.config


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    laboratory = models.CharField(max_length=60, null=True, blank=True)
    code_id = models.CharField(max_length=40, null=True, blank=True)

    class Meta:
        db_table = "core_profile"

    def __str__(self):
        return self.user.username

    def get_lab_name(self):
        return "%s" % (self.laboratory)

    def get_lab_code(self):
        return "%s" % (self.code_id)


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    try:
        instance.profile.save()
    except ObjectDoesNotExist:
        Profile.objects.create(user=instance)


# TODO: remove
class BioinfoMetadataFile(models.Model):
    title = models.CharField(max_length=200)
    file_path = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=("created at"))

    class Meta:
        db_table = "core_metadata_values_file"

    def __str__(self):
        return "%s" % (self.title)

    def get_title(self):
        return "%s" % (self.title)

    def get_file_path(self):
        return "%s" % (self.file_path)

    def get_uploaded_file(self):
        return "%s" % (self.uploadedFile)


class SchemaManager(models.Manager):
    def create_new_schema(self, data):
        new_schema = self.create(
            file_name=data["file_name"],
            user_name=data["user_name"],
            schema_name=data["schema_name"],
            schema_version=data["schema_version"],
            schema_default=data.get("schema_default", False),
            schema_in_use=data.get("schema_in_use", True),
            schema_app_name=data["schema_app_name"],
        )
        return new_schema


class Schema(models.Model):
    file_name = models.FileField(upload_to=core.config.SCHEMAS_UPLOAD_FOLDER)
    user_name = models.ForeignKey(User, on_delete=models.CASCADE)
    schema_name = models.CharField(max_length=40)
    schema_version = models.CharField(max_length=10)
    schema_in_use = models.BooleanField(default=True)
    schema_default = models.BooleanField(default=False)
    schema_app_name = models.CharField(max_length=40, null=True, blank=True, db_index=True)
    generated_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        db_table = "core_metadata_schema"

    def __str__(self):
        return "%s_%s" % (self.schema_name, self.schema_version)

    def get_schema_and_version(self):
        return "%s_%s" % (self.schema_name, self.schema_version)

    def get_schema_name(self):
        return "%s" % (self.schema_name)

    def get_schema_id(self):
        return "%s" % (self.pk)

    def get_schema_info(self):
        data = []
        data.append(self.pk)
        data.append(self.schema_name)
        data.append(self.schema_version)
        data.append(self.schema_default)
        data.append(str(self.schema_in_use))
        data.append(self.file_name)
        return data

    def update_default(self, default):
        self.schema_default = default
        self.save()

    objects = SchemaManager()


class ClassificationManager(models.Manager):
    def create_new_classification(self, classification_name):
        new_class_obj = self.create(classification_name=classification_name)
        return new_class_obj


class Classification(models.Model):
    classification_name = models.CharField(max_length=150)
    generated_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        db_table = "core_metadata_classification"

    def __str__(self):
        return "%s" % (self.classification_name)

    def get_classification_id(self):
        return "%s" % (self.pk)

    def get_classification_name(self):
        return "%s" % (self.classification_name)

    objects = ClassificationManager()


class SchemaPropertiesManager(models.Manager):
    def create_new_property(self, data):
        required = True if "required" in data else False
        options = True if "options" in data else False
        format = data["format"] if "format" in data else None
        if Classification.objects.filter(
            classification_name__iexact=data["classification"]
        ).exists():
            classification_id = Classification.objects.filter(
                classification_name=data["classification"]
            ).last()
        else:
            classification_id = Classification.objects.create_new_classification(
                data["classification"]
            )

        new_property_obj = self.create(
            schemaID=data["schemaID"],
            property=data["property"],
            examples=data["examples"],
            ontology=data["ontology"],
            type=data["type"],
            description=data["description"],
            label=data["label"],
            classificationID=classification_id,
            fill_mode=data["fill_mode"],
            required=required,
            options=options,
            format=format,
        )
        return new_property_obj


class SchemaProperties(models.Model):
    schemaID = models.ForeignKey(Schema, on_delete=models.CASCADE)
    classificationID = models.ForeignKey(
        Classification, on_delete=models.CASCADE, null=True, blank=True
    )
    property = models.CharField(max_length=50, db_index=True)
    examples = models.CharField(max_length=250, null=True, blank=True)
    ontology = models.CharField(max_length=40, null=True, blank=True)
    type = models.CharField(max_length=20)
    format = models.CharField(max_length=20, null=True, blank=True)
    description = models.CharField(max_length=500, null=True, blank=True)
    label = models.CharField(max_length=200, null=True, blank=True)
    required = models.BooleanField(default=False)
    options = models.BooleanField(default=False)
    fill_mode = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = "core_metadata_schema_properties"

    def __str__(self):
        return "%s" % (self.property)

    def get_property_name(self):
        return "%s" % (self.property)

    def get_property_id(self):
        return "%s" % (self.pk)

    def get_property_info(self):
        if self.classificationID:
            classification = self.classificationID.get_classification_name()
        else:
            classification = ""
        data = []
        data.append(self.property)
        data.append(self.label)
        data.append(self.required)
        data.append(classification)
        data.append(self.description)
        return data

    def has_options(self):
        return self.options

    def get_label(self):
        return "%s" % (self.label)

    def get_format(self):
        return "%s" % (self.format)

    def get_ontology(self):
        return "%s" % (self.ontology)

    def get_fill_mode(self):
        return "%s" % (self.fill_mode)

    def get_classification(self):
        if self.classificationID is not None:
            return self.classificationID.get_classification_name()
        return ""

    objects = SchemaPropertiesManager()


class PropertyOptionsManager(models.Manager):
    def create_property_options(self, data):
        new_property_option_obj = self.create(
            propertyID=data["propertyID"],
            enum=data["enum"],
            ontology=data["ontology"],
        )
        return new_property_option_obj


class PropertyOptions(models.Model):
    propertyID = models.ForeignKey(SchemaProperties, on_delete=models.CASCADE)
    enum = models.CharField(max_length=250, null=True, blank=True)
    ontology = models.CharField(max_length=40, null=True, blank=True)

    class Meta:
        db_table = "core_metadata_schema_property_option"

    def __str__(self):
        return "%s" % (self.enum)

    def get_enum(self):
        return "%s" % (self.enum)

    objects = PropertyOptionsManager()


class MetadataVisualizationManager(models.Manager):
    def create_metadata_visualization(self, data):
        new_met_visual = self.create(
            schemaID=data["schema_id"],
            property_name=data["property_name"],
            label_name=data["label_name"],
            order=data["order"],
            in_use=data["in_use"],
            fill_mode=data["fill_mode"],
        )
        return new_met_visual

# TODO: remove
class MetadataVisualization(models.Model):
    schemaID = models.ForeignKey(Schema, on_delete=models.CASCADE)
    property_name = models.CharField(max_length=60)
    label_name = models.CharField(max_length=80)
    order = models.IntegerField()
    in_use = models.BooleanField(default=True)
    fill_mode = models.CharField(max_length=40)
    generated_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        db_table = "core_metadata_visualization"

    def __str__(self):
        return "%s" % (self.label_name)

    def get_label(self):
        return "%s" % (self.label_name)

    def get_property(self):
        return "%s" % (self.property_name)

    def get_order(self):
        return "%s" % (self.order)

    def get_schema_obj(self):
        return self.schemaID

    objects = MetadataVisualizationManager()


class MetadataGroup(models.Model):
    sample = models.ForeignKey(
        "core.Sample", on_delete=models.CASCADE, related_name="metadata_groups"
    )
    group_property = models.ForeignKey(
        "core.SchemaProperties",
        on_delete=models.CASCADE,
        related_name="metadata_groups",
    )
    group_index = models.IntegerField()
    created_at = models.DateTimeField(blank=True)

    class Meta:
        db_table = "core_metadata_group"
        # Just to ensure that there are no duplicate groups for the same sample
        constraints = [
            models.UniqueConstraint(
                fields=["sample", "group_property", "group_index"],
                name="uniq_metadata_group_sample_prop_index",
            )
        ]
        indexes = [models.Index(fields=["sample", "group_property"])]

    def __str__(self):
        return f"{self.sample.sample_unique_id}:{self.group_property.property}[{self.group_index}]"


class MetadataValuesManager(models.Manager):
    def create_new_value(self, data):
        # Get group object
        group_obj = data.get("group")
        group_id = data.get("group_id")
        if group_obj is not None and not isinstance(group_obj, MetadataGroup):
            group_obj = MetadataGroup.objects.get(pk=group_obj)
        elif group_obj is None and group_id is not None:
            group_obj = MetadataGroup.objects.get(pk=group_id)

        # verify that the value and its group belong to the same sample (sample)
        if group_obj is not None:
            sample_value = data["sample_id"]
            sample_id = getattr(sample_value, "pk", sample_value)
            if isinstance(sample_id, str) and sample_id.isdigit():
                sample_id = int(sample_id)
            # If the group belongs to a sample_id other than the one provided, we throw an error
            if group_obj.sample_id != sample_id:
                raise ValueError(
                    f"Invalid group: group.sample_id ({group_obj.sample_id}) "
                    f"does not match sample_id ({sample_id})"
                )
        # Instance is validated, then create the new value to be stored in db
        new_value = self.create(
            value=data["value"],
            analysis_date=data["analysis_date"],
            sample=data["sample_id"],
            schema_property=data["schema_property_id"],
            group=group_obj,
        )
        return new_value


class MetadataValues(models.Model):
    value = models.CharField(max_length=240, null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    analysis_date = models.DateField()
    sample = models.ForeignKey(
        "core.Sample", on_delete=models.CASCADE, related_name="metadata_values"
    )
    schema_property = models.ForeignKey(
        "core.SchemaProperties",
        on_delete=models.CASCADE,
        related_name="metadata_values",
    )
    group = models.ForeignKey(
        "core.MetadataGroup",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="metadata_values",
    )

    class Meta:
        db_table = "core_metadata_values"
        indexes = [
            models.Index(fields=["sample", "schema_property"]),
            models.Index(fields=["value", "sample"]),
            # Covers search path resolving matching samples per filter while also
            # serving prefix lookups on (schema_property, value).
            models.Index(fields=["schema_property", "value", "sample"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["group", "schema_property"],
                name="uniq_metadata_values_group_schema_property",
            )
        ]

    def __str__(self):
        return "%s" % (self.value)

    def get_value(self):
        return "%s" % (self.value)

    def get_id(self):
        return "%s" % (self.pk)

    def get_b_process_field_id(self):
        return "%s" % (self.schema_property)

    objects = MetadataValuesManager()


class SampleState(models.Model):
    state = models.CharField(max_length=80)
    display_string = models.CharField(max_length=80, null=True, blank=True)
    description = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "core_sample_state"

    def __str__(self):
        return "%s" % (self.state)

    def get_state(self):
        return "%s" % (self.state)

    def get_state_id(self):
        return "%s" % (self.pk)

    def get_state_display_string(self):
        return "%s" % (self.display_string)


class ErrorName(models.Model):
    error_name = models.CharField(max_length=100)
    error_code = models.CharField(max_length=10)
    error_text = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        db_table = "core_error_name"

    def __str__(self):
        return "%s" % (self.error_name)

    def get_error_name(self):
        return "%s" % (self.error_name)

    def get_error_id(self):
        return "%s" % (self.pk)

    def get_error_code(self):
        return "%s" % (self.error_code)

    def get_description(self):
        return "%s" % (self.error_text)


class SampleManager(models.Manager):
    def create_new_sample(self, data):
        # FIXME: Sequencing_date is not supposed to be mandatory, collecting date is
        new_sample = self.create(
            sample_unique_id=data["sample_unique_id"],
            sequencing_sample_id=data["sequencing_sample_id"],
            sequencing_date=data["sequencing_date"],
            metadata_file=data["metadata_file"],
            user=data["user"],
        )
        return new_sample


class Sample(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    schema_obj = models.ForeignKey(
        Schema, on_delete=models.CASCADE, null=True, blank=True
    )
    fingerprint = models.CharField(max_length=24, null=True, blank=True, db_index=True)
    # Frequent lookup key for /samples/{sample_unique_id}.
    sample_unique_id = models.CharField(max_length=12, db_index=True)
    microbiology_lab_sample_id = models.CharField(max_length=80, null=True, blank=True)
    collecting_lab_sample_id = models.CharField(max_length=80, null=True, blank=True)
    collecting_lab_isolate_id = models.CharField(max_length=80, null=True, blank=True)
    sequencing_sample_id = models.CharField(max_length=80, null=True, blank=True)
    sequencing_isolate_id = models.CharField(max_length=80, null=True, blank=True)
    submitting_lab_sample_id = models.CharField(max_length=80, null=True, blank=True)
    submitting_lab_isolate_id = models.CharField(max_length=80, null=True, blank=True)
    collecting_institution = models.CharField(max_length=120, null=True, blank=True)
    # TODO: relace sequence_file* and _filepath properties with the ones in metadataplatforms
    sequence_file_R1_fastq = models.CharField(max_length=80, null=True, blank=True)
    sequence_file_R2_fastq = models.CharField(max_length=80, null=True, blank=True)
    sequence_file_R1_md5 = models.CharField(max_length=80, null=True, blank=True)
    sequence_file_R2_md5 = models.CharField(max_length=80, null=True, blank=True)
    r1_fastq_filepath = models.CharField(max_length=120, null=True, blank=True)
    r2_fastq_filepath = models.CharField(max_length=120, null=True, blank=True)
    sequencing_date = models.DateTimeField(auto_now_add=False, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_sample"

    def __str__(self):
        return "%s" % (self.sequencing_sample_id)

    def get_sample_unique_id(self):
        return "%s" % (self.sample_unique_id)

    def get_fingerprint(self):
        return "%s" % (self.fingerprint)
    
    def get_sample_name(self):
        return "%s" % (self.sequencing_sample_id)

    def get_isolate_name(self):
        return "%s" % (self.sequencing_isolate_id)

    def get_sample_id(self):
        return "%s" % (self.pk)

    def get_sequencing_sample_id(self):
        return "%s" % (self.sequencing_sample_id)

    def get_collecting_lab_sample_id(self):
        return "%s" % (self.collecting_lab_sample_id)

    def get_collecting_institution(self):
        return "%s" % (self.collecting_institution)

    def get_unique_id(self):
        return "%s" % (self.sample_unique_id)

    def get_schema_obj(self):
        if self.schema_obj:
            return self.schema_obj
        return None

    def get_ena_info(self):
        if self.ena_obj is None:
            return ""
        return self.ena_obj.get_ena_data()

    def get_state(self):
        latest_state = SampleStateHistory.objects.filter(
            sample=self, is_current=True
        ).last()
        if latest_state and latest_state.state:
            return "%s" % (latest_state.state.get_state())
        return None

    def get_user(self):
        return "%s" % (self.user)

    def get_info_for_searching(self):
        recorded_date = self.created_at.strftime("%d-%B-%Y")
        try:
            seq_date = self.sequencing_date.strftime("%d-%B-%Y")
        except (TypeError, AttributeError):
            seq_date = ""
        data = []
        data.append(self.pk)
        data.append(self.sequencing_sample_id)
        data.append(self.get_state())
        data.append(seq_date)
        data.append(recorded_date)
        return data

    def get_sample_basic_data(self):
        recorded_date = self.created_at.strftime("%d-%B-%Y")
        data = []
        data.append(self.sequencing_sample_id)
        data.append(self.microbiology_lab_sample_id)
        data.append(self.submitting_lab_sample_id)
        data.append(self.get_state())
        data.append(recorded_date)
        return data

    def get_fastq_data(self):
        data = []
        data.append(self.sequence_file_R1_fastq)
        data.append(self.sequence_file_R2_fastq)
        data.append(self.r1_fastq_filepath)
        data.append(self.r2_fastq_filepath)
        data.append(self.sequence_file_R1_md5)
        data.append(self.sequence_file_R2_md5)
        return data

    def update_state(self, state):
        if not SampleState.objects.filter(state__exact=state).exists():
            return False
        self.state = SampleState.objects.filter(state__exact=state).last()
        self.save()
        return self

    objects = SampleManager()


class SampleIdSequence(models.Model):
    sequence_name = models.CharField(max_length=40, unique=True)
    last_value = models.CharField(max_length=12, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_sample_id_sequence"

    def __str__(self):
        return "%s=%s" % (self.sequence_name, self.last_value)


class PublicDatabaseType(models.Model):
    public_type_name = models.CharField(max_length=30)
    public_type_display = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_public_database_type"

    def __str__(self):
        return "%s" % (self.public_type_name)

    def get_public_type_name(self):
        return "%s" % (self.public_type_name)

    def get_public_type_display(self):
        return "%s" % (self.public_type_display)


class PublicDatabaseFieldsManager(models.Manager):
    def create_new_field(self, data):
        new_field = self.create(
            database_type=data["database_type"],
            property_name=data["property_name"],
            label_name=data["label_name"],
        )
        return new_field


class PublicDatabaseFields(models.Model):
    schemaID = models.ManyToManyField(Schema)
    database_type = models.ForeignKey(
        PublicDatabaseType, on_delete=models.CASCADE, null=True, blank=True
    )
    property_name = models.CharField(max_length=60)
    label_name = models.CharField(max_length=80)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_public_database_field"

    def __str__(self):
        return "%s" % (self.property_name)

    def get_property_name(self):
        return "%s" % (self.property_name)

    def get_label_name(self):
        return "%s" % (self.label_name)

    def get_id(self):
        return "%s" % (self.pk)

    objects = PublicDatabaseFieldsManager()


class PublicDatabaseValues(models.Model):
    public_database_fieldID = models.ForeignKey(
        PublicDatabaseFields, on_delete=models.CASCADE
    )
    sampleID = models.ForeignKey(
        Sample, on_delete=models.CASCADE, null=True, blank=True
    )
    value = models.CharField(max_length=240, null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    class Meta:
        db_table = "core_public_database_value"

    def __str__(self):
        return "%s" % (self.value)

    def get_value(self):
        return "%s" % (self.value)

    def get_id(self):
        return "%s" % (self.pk)


class SampleStateHistory(models.Model):
    sample = models.ForeignKey(Sample, on_delete=models.CASCADE)
    state = models.ForeignKey(SampleState, on_delete=models.CASCADE)
    error_name = models.ForeignKey(ErrorName, on_delete=models.CASCADE)

    is_current = models.BooleanField(default=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_sample_state_history"

    def __str__(self):
        return "%s_%s" % (self.sample, self.sample)

    def get_sample_id(self):
        return "%s" % (self.sample)

    def get_date(self):
        return self.changed_at.strftime("%d-%B-%Y")

    def get_state(self):
        if self.state:
            return "%s" % (self.state.get_state())
        return None

    def update_state(self):
        if not SampleState.objects.filter(state__exact=self.state).exists():
            return False
        self.state = SampleState.objects.filter(state__exact=self.state).last()
        self.save()
        return self


class Variant(models.Model):
    chrom = models.CharField(max_length=80, db_index=True)
    position = models.PositiveIntegerField(db_index=True)
    reference = models.CharField(max_length=255)
    alternate = models.CharField(max_length=255)
    variant_type = models.CharField(max_length=40, blank=True, default="", db_index=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_variant"
        constraints = [
            models.UniqueConstraint(
                fields=["chrom", "position", "reference", "alternate"],
                name="uniq_variant_locus_ref_alt",
            )
        ]
        indexes = [
            models.Index(
                fields=["position", "reference", "alternate"],
                name="idx_variant_pos_ref_alt",
            ),
            models.Index(
                fields=["chrom", "position"],
                name="idx_variant_chrom_pos",
            ),
        ]

    def __str__(self):
        return f"{self.chrom}:g.{self.position}{self.reference}>{self.alternate}"


class SampleVariant(models.Model):
    sample = models.ForeignKey(
        Sample, on_delete=models.CASCADE, related_name="variant_observations"
    )
    variant = models.ForeignKey(
        Variant, on_delete=models.CASCADE, related_name="sample_observations"
    )
    depth = models.PositiveIntegerField(null=True, blank=True)
    allele_frequency = models.FloatField(null=True, blank=True)
    analysis_date = models.DateField()
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_sample_variant"
        constraints = [
            models.UniqueConstraint(
                fields=["sample", "variant", "analysis_date"],
                name="uniq_sample_variant_analysis",
            )
        ]
        indexes = [
            models.Index(
                fields=["sample", "analysis_date"],
                name="idx_sv_sample_analysis",
            ),
            models.Index(
                fields=["variant", "analysis_date"],
                name="idx_sv_variant_analysis",
            ),
        ]

    def __str__(self):
        return f"{self.sample.sample_unique_id}:{self.variant}"


class VariantAnnotation(models.Model):
    variant = models.ForeignKey(
        Variant, on_delete=models.CASCADE, related_name="annotations"
    )
    gene_region = models.CharField(max_length=120, blank=True, default="", db_index=True)
    effect = models.CharField(max_length=150, blank=True, default="", db_index=True)
    functional_class = models.CharField(
        max_length=100, blank=True, default="", db_index=True
    )
    locus_name = models.CharField(max_length=120, blank=True, default="", db_index=True)
    locus_id = models.CharField(max_length=120, blank=True, default="", db_index=True)
    aminoacid_change = models.CharField(
        max_length=120, blank=True, default="", db_index=True
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_variant_annotation"
        constraints = [
            models.UniqueConstraint(
                fields=["variant", "gene_region", "effect", "aminoacid_change"],
                name="uniq_variant_annotation_core",
            )
        ]
        indexes = [
            models.Index(
                fields=["locus_name", "locus_id"],
                name="idx_va_locus_name_id",
            ),
            models.Index(
                fields=["gene_region", "effect"],
                name="idx_va_region_effect",
            ),
        ]

    def __str__(self):
        return f"{self.variant}:{self.effect}:{self.aminoacid_change}"


class TemporalSampleStorageManager(models.Manager):
    def save_temp_data(self, data):
        new_t_data = self.create(
            sample_name=data["sample_name"],
            field=data["field"],
            value=data["value"],
            user=data["user"],
        )
        return new_t_data


class TemporalSampleStorage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    sample_name = models.CharField(max_length=100, null=True)
    field = models.CharField(max_length=100, null=True)
    value = models.CharField(max_length=100, null=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_temporal_sample_storage"

    def __str__(self):
        return "%s,%s" % (self.sample_name, self.field)

    def get_sample_name(self):
        return "%s" % (self.sample_name)

    def get_temp_values(self):
        return {self.field: self.value}

    def update_sent_status(self, value):
        self.sent = value
        self.save()
        return

    objects = TemporalSampleStorageManager()


class ConfigSettingManager(models.Manager):
    def create_config_setting(self, configuration_name, configuration_value):
        new_config_settings = self.create(
            configurationName=configuration_name, configurationValue=configuration_value
        )
        return new_config_settings


class ConfigSetting(models.Model):
    configuration_name = models.CharField(max_length=80)
    configuration_value = models.CharField(max_length=255, null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_config_setting"

    def __str__(self):
        return "%s" % (self.configuration_name)

    def get_configuration_value(self):
        return "%s" % (self.configuration_value)

    def set_configuration_value(self, new_value):
        self.configuration_value = new_value
        self.save()
        return self

    objects = ConfigSettingManager()
