SCHEMAS_UPLOAD_FOLDER = "schemas"

# Allowed project scopes exposed by the public API.
ALLOWED_SCHEMA_PROJECT_NAMES = ["mepram", "relecov", "redlabra"]
# Backward-compatible alias for older code paths.
ALLOWED_SCHEMA_APP_NAMES = ALLOWED_SCHEMA_PROJECT_NAMES

# Sample identity strategy.
SAMPLE_FINGERPRINT_LENGTH = 24
SAMPLE_ID_PREFIX = "SAM-"

# Databrowser snapshot configuration.
DATABROWSER_PRIORITY_PROPERTIES = [
    {
        "group": "sample-metadata",
        "expected_property": "geo_loc_state",
        "display_name": "geo_loc_state",
        "chart_title": "Samples by region",
        "aliases": [
            "geo_loc_state",
            "collecting_institution_geo_loc_state",
            "submitting_geo_loc_state",
        ],
        "strategy": "categorical",
    },
    {
        "group": "sample-metadata",
        "expected_property": "sample_collection_date",
        "display_name": "sample_collection_date",
        "chart_title": "Samples by collection period",
        "aliases": ["sample_collection_date"],
        "strategy": "date",
    },
    {
        "group": "sample-metadata",
        "expected_property": "sample_received_date",
        "display_name": "sample_received_date",
        "chart_title": "Samples by reception period",
        "aliases": ["sample_received_date"],
        "strategy": "date",
    },
    {
        "group": "sample-metadata",
        "expected_property": "anatomical_material",
        "display_name": "anatomical_material",
        "chart_title": "Samples by anatomical material",
        "aliases": ["anatomical_material"],
        "strategy": "categorical",
    },
    {
        "group": "sample-metadata",
        "expected_property": "anatomical_part",
        "display_name": "anatomical_part",
        "chart_title": "Samples by anatomical part",
        "aliases": ["anatomical_part"],
        "strategy": "categorical",
    },
    {
        "group": "sample-metadata",
        "expected_property": "specimen_source",
        "display_name": "specimen_source",
        "chart_title": "Samples by specimen source",
        "aliases": ["specimen_source"],
        "strategy": "categorical",
    },
    {
        "group": "sample-metadata",
        "expected_property": "isolate_delivery_type",
        "display_name": "isolate_delivery_type",
        "chart_title": "Samples by isolate delivery type",
        "aliases": ["isolate_delivery_type"],
        "strategy": "categorical",
    },
    {
        "group": "sample-bioinfo",
        "expected_property": "bioinformatics_protocol_software_name",
        "display_name": "bioinformatics_protocol_software_name",
        "chart_title": "Samples by analysis software",
        "aliases": ["bioinformatics_protocol_software_name"],
        "strategy": "categorical",
    },
    {
        "group": "sample-bioinfo",
        "expected_property": "preprocessing_software_name",
        "display_name": "preprocessing_software_name",
        "chart_title": "Samples by preprocessing software",
        "aliases": ["preprocessing_software_name"],
        "strategy": "categorical",
    },
    {
        "group": "sample-bioinfo",
        "expected_property": "read_length",
        "display_name": "read_length",
        "chart_title": "Samples by read length bucket",
        "aliases": ["read_length"],
        "strategy": "read-length",
    },
    {
        "group": "sample-bioinfo",
        "expected_property": "number_of_reads_sequenced",
        "display_name": "number_of_reads_sequenced",
        "chart_title": "Samples by read count bucket",
        "aliases": ["number_of_reads_sequenced"],
        "strategy": "read-count",
    },
    {
        "group": "sample-bioinfo",
        "expected_property": "assembly_method",
        "display_name": "assembly_method",
        "chart_title": "Samples by assembly method",
        "aliases": ["assembly_method"],
        "strategy": "categorical",
    },
    {
        "group": "sample-bioinfo",
        "expected_property": "annotation_software_name",
        "display_name": "annotation_software_name",
        "chart_title": "Samples by annotation software",
        "aliases": ["annotation_software_name"],
        "strategy": "categorical",
    },
    {
        "group": "sample-bioinfo",
        "expected_property": "reads_genome_coverage_value",
        "display_name": "reads_genome_coverage_value",
        "chart_title": "Samples by coverage bucket",
        "aliases": ["reads_genome_coverage_value"],
        "strategy": "coverage",
    },
    {
        "group": "host-information",
        "expected_property": "host_age_years",
        "display_name": "host_age_years",
        "chart_title": "Samples by host age group",
        "aliases": ["host_age_years"],
        "strategy": "age",
    },
    {
        "group": "host-information",
        "expected_property": "host_gender",
        "display_name": "host_gender",
        "chart_title": "Samples by host gender",
        "aliases": ["host_gender"],
        "strategy": "categorical",
    },
    {
        "group": "host-information",
        "expected_property": "host_common_name",
        "display_name": "host_common_name",
        "chart_title": "Samples by host common name",
        "aliases": ["host_common_name"],
        "strategy": "categorical",
    },
    {
        "group": "host-information",
        "expected_property": "infection_type",
        "display_name": "infection_type",
        "chart_title": "Samples by infection type",
        "aliases": ["infection_type"],
        "strategy": "categorical",
    },
    {
        "group": "host-information",
        "expected_property": "exposure_setting",
        "display_name": "exposure_setting",
        "chart_title": "Samples by exposure setting",
        "aliases": ["exposure_setting"],
        "strategy": "categorical",
    },
    {
        "group": "host-information",
        "expected_property": "Associated with outbreak",
        "display_name": "Associated with outbreak",
        "chart_title": "Samples associated with outbreak",
        "aliases": ["Associated with outbreak"],
        "strategy": "categorical",
    },
]

DATABROWSER_SECTION_META = {
    "sample-metadata": {
        "title": "Sample metadata",
        "description": (
            "Cobertura agregada de recoleccion y procesado de muestras basada "
            "en consultas agregadas de backend."
        ),
        "notes": [
            "La distribucion geografica utiliza fallbacks sobre geo_loc_state cuando el dataset real emplea campos equivalentes por institucion.",
            "Los graficos temporales se representan como linea para mantener legibilidad al crecer el numero de muestras.",
        ],
    },
    "sample-bioinfo": {
        "title": "Sample bioinfo",
        "description": (
            "Panel superior con agregados bioinformaticos y propiedades "
            "priorizadas para tecnologia, software y volumen de datos."
        ),
        "notes": [],
    },
    "host-information": {
        "title": "Host information",
        "description": (
            "Perfil cientifico del host con foco en identidad del hospedador, "
            "infeccion y exposicion visible en la metadata retornada."
        ),
        "notes": [],
    },
}

DATABROWSER_SECTION_ORDER = [
    "sample-metadata",
    "sample-bioinfo",
    "host-information",
]
DATABROWSER_GLOBAL_CACHE_SCOPE = "global"
DATABROWSER_NO_FILTERS_HASH = "no-filters"
DATABROWSER_OVERVIEW_SUMMARY = "overview-summary"
DATABROWSER_METADATA_SUMMARY = "metadata-summary"
DATABROWSER_SCHEMA_SUMMARY = "schema-summary"
DATABROWSER_CACHEABLE_SUMMARIES = (
    DATABROWSER_OVERVIEW_SUMMARY,
    DATABROWSER_METADATA_SUMMARY,
    DATABROWSER_SCHEMA_SUMMARY,
)
