# BIPLAT-CIBERINFEC/pathocore-api: Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v1.0.0 pathocore-api - "Initial Release" 2026/06/01

### `Changed`

- Refactored API logic into versioned views, serializers and service modules.
- Standardized sample, schema, metadata and use-case access around project-scoped data.
- Optimized databrowser responses with precomputed summary caches and refresh commands.

### `Added`

- Added Docker-based test and production installation flows.
- Added OpenAPI/Swagger documentation for the public REST API.
- Added schema ingestion/listing, sample ingestion/listing/detail/history and metadata search endpoints.
- Added generic databrowser endpoints for overview, metadata, schema and property distributions.
- Added variant ingestion, summary, reference genome, filter option and search endpoints.
- Added Keycloak JWT authentication and group-derived authorization for use cases, labs and superusers.
- Added use-case data summary and isolate explorer support.

### `Fixed`

- Fixed schema rotation, sample identifier generation and duplicate sample handling.
- Fixed metadata distribution edge cases, geographic summaries and empty-sample rendering behavior.
- Fixed Docker installation, production settings and linting issues found during release preparation.

### `Dependencies`

- 

### `Deprecated`

- Legacy Basic Auth is kept as a configurable compatibility mode and should stay disabled in production deployments.
