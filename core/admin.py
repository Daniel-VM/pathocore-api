# Generic imports
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

# Local imports
import core.models


def custom_date_format(self):
    # SampleStateHistory stores timestamp in `changed_at`.
    if self.changed_at:
        return self.changed_at.strftime("%d %b %Y")
    return ""


custom_date_format.short_description = "Changed at"
custom_date_format.admin_order_field = "changed_at"


class ProfileInLine(admin.StackedInline):
    model = core.models.Profile
    can_delete = False
    verbose_name_plural = "Profile"
    fk_name = "user"


class CustomUserAdmin(UserAdmin):
    inlines = (ProfileInLine,)

    def get_inline_instances(self, request, obj=None):
        if not obj:
            return list()
        return super(CustomUserAdmin, self).get_inline_instances(request, obj)


class MetadataValuesAdmin(admin.ModelAdmin):
    list_display = ["value", "sample", "schema_property", "analysis_date"]
    search_fields = ("value__icontains",)


class ClassificationAdmin(admin.ModelAdmin):
    list_display = ["classification_name"]


class ConfigSettingAdmin(admin.ModelAdmin):
    list_display = ["configuration_name", "configuration_value"]


class SampleStateHistoryAdmin(admin.ModelAdmin):
    list_display = [
        "is_current",
        custom_date_format,
        "sample_id",
        "state_id",
        "error_name_id",
    ]


class ErrorNameAdmin(admin.ModelAdmin):
    list_display = ["error_name", "error_code", "error_text"]


class PublicDatabaseTypeAdmin(admin.ModelAdmin):
    list_display = ["public_type_name", "public_type_display"]


class PublicDatabaseFieldsAdmin(admin.ModelAdmin):
    list_display = ["property_name", "database_type"]


class PublicDatabaseValuesAdmin(admin.ModelAdmin):
    list_display = ["value", "sampleID", "public_database_fieldID"]
    search_fields = ["value__icontains", "sampleID__sequencing_sample_id__icontains"]


class SampleAdmin(admin.ModelAdmin):
    list_display = [
        "sample_unique_id",
        "sequencing_sample_id",
        "submitting_lab_sample_id",
        "collecting_lab_sample_id",
    ]
    search_fields = ["sample_unique_id__icontains", "sequencing_sample_id__icontains"]
    list_filter = ["created_at"]


class SampleStateAdmin(admin.ModelAdmin):
    list_display = ["state", "description"]


class SampleIdSequenceAdmin(admin.ModelAdmin):
    list_display = ["sequence_name", "last_value", "updated_at"]


class DatabrowserSummaryCacheAdmin(admin.ModelAdmin):
    list_display = ["summary_name", "scope_key", "filters_hash", "generated_at"]
    search_fields = ["summary_name", "scope_key", "filters_hash"]
    list_filter = ["summary_name", "scope_key", "generated_at"]


class SchemaAdmin(admin.ModelAdmin):
    list_display = [
        "schema_name",
        "schema_version",
        "schema_default",
        "schema_in_use",
        "schema_app_name",
    ]


class SchemaPropertiesAdmin(admin.ModelAdmin):
    list_display = ["property", "label", "schemaID", "required"]
    search_fields = ["property__icontains"]


class TemporalSampleStorageAdmin(admin.ModelAdmin):
    list_display = ["sample_name", "field", "value", "user"]


class PropertyOptionsAdmin(admin.ModelAdmin):
    list_display = ["propertyID", "enum", "ontology"]


class MetadataVisualizationAdmin(admin.ModelAdmin):
    list_display = [
        "property_name",
        "label_name",
        "fill_mode",
        "in_use",
    ]


class VariantAdmin(admin.ModelAdmin):
    list_display = ["chrom", "position", "reference", "alternate", "variant_type"]
    search_fields = ["chrom", "reference", "alternate"]
    list_filter = ["chrom", "variant_type"]


class SampleVariantAdmin(admin.ModelAdmin):
    list_display = ["sample", "variant", "depth", "allele_frequency", "analysis_date"]
    search_fields = ["sample__sample_unique_id", "variant__chrom"]
    list_filter = ["analysis_date"]


class VariantAnnotationAdmin(admin.ModelAdmin):
    list_display = [
        "variant",
        "gene_region",
        "effect",
        "functional_class",
        "locus_name",
        "locus_id",
        "aminoacid_change",
    ]
    search_fields = [
        "gene_region",
        "effect",
        "locus_name",
        "locus_id",
        "aminoacid_change",
    ]
    list_filter = ["effect", "functional_class"]


# Register models
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
admin.site.register(core.models.ConfigSetting, ConfigSettingAdmin)
admin.site.register(core.models.Sample, SampleAdmin)
admin.site.register(core.models.SampleIdSequence, SampleIdSequenceAdmin)
admin.site.register(core.models.DatabrowserSummaryCache, DatabrowserSummaryCacheAdmin)
admin.site.register(core.models.SampleState, SampleStateAdmin)
admin.site.register(core.models.Schema, SchemaAdmin)
admin.site.register(core.models.SchemaProperties, SchemaPropertiesAdmin)
admin.site.register(core.models.PropertyOptions, PropertyOptionsAdmin)
admin.site.register(core.models.PublicDatabaseType, PublicDatabaseTypeAdmin)
admin.site.register(core.models.PublicDatabaseFields, PublicDatabaseFieldsAdmin)
admin.site.register(core.models.PublicDatabaseValues, PublicDatabaseValuesAdmin)
admin.site.register(core.models.MetadataVisualization, MetadataVisualizationAdmin)
admin.site.register(core.models.MetadataValues, MetadataValuesAdmin)
admin.site.register(core.models.Classification, ClassificationAdmin)
admin.site.register(core.models.TemporalSampleStorage, TemporalSampleStorageAdmin)
admin.site.register(core.models.ErrorName, ErrorNameAdmin)
admin.site.register(core.models.SampleStateHistory, SampleStateHistoryAdmin)
admin.site.register(core.models.Variant, VariantAdmin)
admin.site.register(core.models.SampleVariant, SampleVariantAdmin)
admin.site.register(core.models.VariantAnnotation, VariantAnnotationAdmin)
