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
        "strategy": "geography",
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

DATABROWSER_GEOLOCATION_PROPERTIES = (
    "geo_loc_state",
    "collecting_institution_geo_loc_state",
    "submitting_geo_loc_state",
)

DATABROWSER_GEOLOCATION_CENTROIDS = {
    "andalucia": {
        "admin_level": "autonomous_community",
        "code": "ES-AN",
        "country": "ES",
        "label": "Andalucía",
        "lat": 37.5443,
        "lon": -4.7278,
    },
    "aragon": {
        "admin_level": "autonomous_community",
        "code": "ES-AR",
        "country": "ES",
        "label": "Aragón",
        "lat": 41.5976,
        "lon": -0.9057,
    },
    "principado de asturias": {
        "admin_level": "autonomous_community",
        "code": "ES-AS",
        "country": "ES",
        "label": "Principado de Asturias",
        "lat": 43.3614,
        "lon": -5.8593,
    },
    "asturias": {
        "admin_level": "autonomous_community",
        "code": "ES-AS",
        "country": "ES",
        "label": "Principado de Asturias",
        "lat": 43.3614,
        "lon": -5.8593,
    },
    "illes balears": {
        "admin_level": "autonomous_community",
        "code": "ES-IB",
        "country": "ES",
        "label": "Illes Balears",
        "lat": 39.3588,
        "lon": 2.7356,
    },
    "islas baleares": {
        "admin_level": "autonomous_community",
        "code": "ES-IB",
        "country": "ES",
        "label": "Illes Balears",
        "lat": 39.3588,
        "lon": 2.7356,
    },
    "canarias": {
        "admin_level": "autonomous_community",
        "code": "ES-CN",
        "country": "ES",
        "label": "Canarias",
        "lat": 28.2916,
        "lon": -16.6291,
    },
    "cantabria": {
        "admin_level": "autonomous_community",
        "code": "ES-CB",
        "country": "ES",
        "label": "Cantabria",
        "lat": 43.1828,
        "lon": -3.9878,
    },
    "castilla la mancha": {
        "admin_level": "autonomous_community",
        "code": "ES-CM",
        "country": "ES",
        "label": "Castilla-La Mancha",
        "lat": 39.2796,
        "lon": -3.0977,
    },
    "castilla leon": {
        "admin_level": "autonomous_community",
        "code": "ES-CL",
        "country": "ES",
        "label": "Castilla y León",
        "lat": 41.8357,
        "lon": -4.3976,
    },
    "castilla y leon": {
        "admin_level": "autonomous_community",
        "code": "ES-CL",
        "country": "ES",
        "label": "Castilla y León",
        "lat": 41.8357,
        "lon": -4.3976,
    },
    "cataluna": {
        "admin_level": "autonomous_community",
        "code": "ES-CT",
        "country": "ES",
        "label": "Cataluña",
        "lat": 41.5912,
        "lon": 1.5209,
    },
    "catalunya": {
        "admin_level": "autonomous_community",
        "code": "ES-CT",
        "country": "ES",
        "label": "Cataluña",
        "lat": 41.5912,
        "lon": 1.5209,
    },
    "ceuta": {
        "admin_level": "autonomous_city",
        "code": "ES-CE",
        "country": "ES",
        "label": "Ceuta",
        "lat": 35.8894,
        "lon": -5.3213,
    },
    "comunidad de madrid": {
        "admin_level": "autonomous_community",
        "code": "ES-MD",
        "country": "ES",
        "label": "Comunidad de Madrid",
        "lat": 40.4168,
        "lon": -3.7038,
    },
    "comunidad foral de navarra": {
        "admin_level": "autonomous_community",
        "code": "ES-NC",
        "country": "ES",
        "label": "Comunidad Foral de Navarra",
        "lat": 42.6954,
        "lon": -1.6761,
    },
    "navarra": {
        "admin_level": "autonomous_community",
        "code": "ES-NC",
        "country": "ES",
        "label": "Comunidad Foral de Navarra",
        "lat": 42.6954,
        "lon": -1.6761,
    },
    "comunidad valenciana": {
        "admin_level": "autonomous_community",
        "code": "ES-VC",
        "country": "ES",
        "label": "Comunitat Valenciana",
        "lat": 39.484,
        "lon": -0.7533,
    },
    "comunitat valenciana": {
        "admin_level": "autonomous_community",
        "code": "ES-VC",
        "country": "ES",
        "label": "Comunitat Valenciana",
        "lat": 39.484,
        "lon": -0.7533,
    },
    "extremadura": {
        "admin_level": "autonomous_community",
        "code": "ES-EX",
        "country": "ES",
        "label": "Extremadura",
        "lat": 39.4937,
        "lon": -6.0679,
    },
    "galicia": {
        "admin_level": "autonomous_community",
        "code": "ES-GA",
        "country": "ES",
        "label": "Galicia",
        "lat": 42.5751,
        "lon": -8.1339,
    },
    "la rioja": {
        "admin_level": "autonomous_community",
        "code": "ES-RI",
        "country": "ES",
        "label": "La Rioja",
        "lat": 42.2871,
        "lon": -2.5396,
    },
    "melilla": {
        "admin_level": "autonomous_city",
        "code": "ES-ML",
        "country": "ES",
        "label": "Melilla",
        "lat": 35.2923,
        "lon": -2.9381,
    },
    "pais vasco": {
        "admin_level": "autonomous_community",
        "code": "ES-PV",
        "country": "ES",
        "label": "País Vasco",
        "lat": 43.0756,
        "lon": -2.5857,
    },
    "euskadi": {
        "admin_level": "autonomous_community",
        "code": "ES-PV",
        "country": "ES",
        "label": "País Vasco",
        "lat": 43.0756,
        "lon": -2.5857,
    },
    "region de murcia": {
        "admin_level": "autonomous_community",
        "code": "ES-MC",
        "country": "ES",
        "label": "Región de Murcia",
        "lat": 37.9922,
        "lon": -1.1307,
    },
    "murcia": {
        "admin_level": "autonomous_community",
        "code": "ES-MC",
        "country": "ES",
        "label": "Región de Murcia",
        "lat": 37.9922,
        "lon": -1.1307,
    },
}
