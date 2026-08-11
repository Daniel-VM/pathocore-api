# BIPLAT-CIBERINFEC/pathocore-api: Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v1.1.0develop pathocore-api

### `Changed`

- [#19](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/19) Refactor production Docker install workflow
- [#21](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/21) Support multi-use-case access requests and keep API v1 route compatibility.
- Restore `/v1` as the canonical API prefix while keeping `/api/v1` as a compatibility alias.
- [#22](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/22) change base url and add param to provide input sql database to docker installation
- [#23](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/23) Improve access request notification emails
- [#24](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/24) Prefix PathoCore API host settings

### `Added`

- [#14](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/14) Add configurable rate limits to protect API endpoints.
- [#16](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/16) Add DRF throttling for public API endpoints.
- [#17](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/17) Notify use-case admins of pending access requests
- [#18](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/18) Use English copy in API response payloads
- [#26](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/26) Support proxy CSRF settings and v1 documentation routes

### `Fixed`

### `Dependencies`

### `Deprecated`

## v1.0.0 pathocore-api - "Initial Release" 2026/06/01

### `Changed`

- [#1](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/1) Establish the standalone `/v1` Django REST API architecture with views, serializers, services and shared utilities.
- [#1](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/1) Refactor sample identity around internal fingerprints and API-facing `sample_unique_id` values.
- [#5](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/5) Simplify generic databrowser summary endpoints and strip project/use-case context from global responses.
- [#7](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/7) Move access handling toward Keycloak Bearer tokens while keeping legacy auth configurable.
- [#8](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/8) Add the first use-case endpoint strategy for API v1.

### `Added`

- [#1](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/1) Add schema, sample, metadata, history, variant and databrowser endpoints.
- [#1](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/1) Add OpenAPI schema, Swagger UI, Docker install flows and MySQL-backed databrowser summary cache.
- [#2](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/2) Add GitHub lint workflows, contribution docs and issue/PR templates.
- [#4](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/4) Add release-facing README updates and initial changelog structure.
- [#6](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/6) Add frontend-ready metadata property distributions with pathogen, year and location breakdowns.
- [#7](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/7) Add Keycloak configuration, JWT validation and group-derived authorization services.
- [#8](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/8) Add use-case data, isolate explorer and use-case cache refresh support.
- [#9](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/9) Add final v1 release changelog coverage.

### `Fixed`

- [#1](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/1) Fix schema rotation, sample duplicate handling and heavy unfiltered databrowser performance via precomputed caches.
- [#3](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/3) Fix lint tooling requirements.
- [#6](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/6) Fix metadata distribution contracts for frontend maps, tooltips and fallback charts.
- [#7](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/7) Fix auth setup for public generic databrowser access and protected use-case flows.
- [#8](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/8) Fix use-case isolate explorer data handling and remove unused metadata models.
- [#9](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/9) Harden release ignore rules for local env files, certificates, keys and secrets.

### `Dependencies`

| Tool / library | Version |
| -------------- | ------- |
| Python | 3.12 lint target |
| Django | 3.2.17 |
| Django REST Framework | requirements-managed |
| drf-spectacular | requirements-managed |
| PyJWT / JWKS validation | requirements-managed |
| MySQL | 8.0 container in test |
| Black | dev requirements |
| flake8 | dev requirements |

### `Deprecated`

- [#7](https://github.com/BIPLAT-CIBERINFEC/pathocore-api/pull/7) Keep legacy Basic Auth only as a configurable compatibility mode; production deployments should use Keycloak Bearer tokens.
