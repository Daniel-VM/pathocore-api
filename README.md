# pathocore-api

[![python_lint](https://github.com/BU-ISCIII/relecov-tools/actions/workflows/python_lint.yml/badge.svg)](https://github.com/BU-ISCIII/relecov-tools/actions/workflows/python_lint.yml)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Django](https://img.shields.io/static/v1?label=Django&message=3.2.17&color=blue?style=plastic&logo=django)](https://github.com/django/django)
[![Python](https://img.shields.io/static/v1?label=Python&message=3.9.10&color=green?style=plastic&logo=Python)](https://www.python.org/)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-v5.0-blueviolet?style=plastic&logo=Bootstrap)](https://getbootstrap.com)
[![version](https://img.shields.io/badge/version-1.0.0-orange?style=plastic&logo=GitHub)](https://github.com/BIPLAT-CIBERINFEC/pathocore-api)

> THIS REPO IS IN ACTIVE DEVELOPMENT.
>
## Table of contents

* [Installation](#installation)
* [Installation outside Docker](#installation-outside-docker)
* [Documentation](#documentation)

# Installation

## Docker test installation

This is the recommended entry point for developers who want to run PathoCore API
locally for installation testing, smoke tests, demos, or frontend integration work.

The local test stack starts two services:

* `app`: Django API running inside a container
* `db`: MySQL database running inside a container

The database is stored in a Docker volume, so the stack can be stopped and started
without losing data unless the volumes are explicitly removed.

### Prerequisites

Before starting, make sure the machine has:

* `git`
* Docker Engine
* Docker Compose plugin (`docker compose`)

Check the tooling in a terminal:

```bash
git --version
docker --version
docker compose version
```

### 1. Clone the repository

```bash
git clone https://github.com/BIPLAT-CIBERINFEC/pathocore-api.git
cd pathocore-api
git checkout develop
```

### 2. Build and install the local test stack

Run the container installer from the repository root:

```bash
bash container_install.sh --test --git_revision current
```

This command will:

* build the application image
* start `app` and `db`
* install the Django project inside the container
* run database migrations

### 3. Check that the containers are running

```bash
docker compose -f docker-compose.test.yml ps
```

### 4. Follow the application logs

In a separate terminal:

```bash
docker compose -f docker-compose.test.yml logs -f app
```

To inspect the database container logs:

```bash
docker compose -f docker-compose.test.yml logs -f db
```

### 5. Open the API documentation

Once the stack is up, Swagger UI should be available at:

```text
http://localhost:8000/swagger/
```

The OpenAPI schema is available at:

```text
http://localhost:8000/openapi/
```

### 6. Use the test administrative user

The test stack creates an idempotent Django superuser from
`conf/docker_test_settings.txt` so authenticated Swagger/API administration works
after a fresh Docker install:

```text
admin / admin_pass
```

Override `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_EMAIL` and
`DJANGO_SUPERUSER_PASSWORD` before running `container_install.sh` to use different
local credentials. Production compose keeps `PATHOCORE_CREATE_DEFAULT_SUPERUSER`
disabled by default.

### 7. Optional: load a small non-sensitive test dataset

This public repository does not include production data or large internal datasets.
If maintainers provide a small test dump separately, it can be imported into the
local Docker database with a command like this:

```bash
gunzip -c /path/to/pathocore_api_test_dump.sql.gz | \
docker compose -f docker-compose.test.yml exec -T db \
  mysql -u<db_user> -p<db_password> pathocore_api
```

Replace `<db_user>` and `<db_password>` with the values defined for your local test stack.
For the Docker test installation, these testing credentials are defined in
`conf/docker_test_settings.txt`.

### Useful commands

Open a shell in the API container:

```bash
docker compose -f docker-compose.test.yml exec app bash
```

Open a MySQL shell in the database container:

```bash
docker compose -f docker-compose.test.yml exec db mysql -u<db_user> -p<db_password> pathocore_api
```

Stop the containers but keep the database volume:

```bash
docker compose -f docker-compose.test.yml down
```

Stop the containers and remove the database volume:

```bash
docker compose -f docker-compose.test.yml down -v
```

Use `down -v` only when you want to discard the local test database completely.

## Docker Production Installation

`docker-compose.prod.yml` is intended for controlled server deployments behind a
reverse proxy. By default, the API binds only to `127.0.0.1` on the host:

```text
PATHOCORE_API_BIND_HOST=127.0.0.1
PATHOCORE_API_PORT=8000
PATHOCORE_HOST_LOG_DIR=/var/log/local/pathocore-api/apps
```

Prepare a non-committed production install file on the server, based on
`conf/docker_production_settings.txt`. It can live outside the repository, for
example under `/srv/containers/bind/pathocore-api/production_settings.txt`.
Do not commit credentials.

The production install file is consumed by `install.sh` inside the running
container to generate the installed Django settings and `/opt/pathocore-api/.env`.
`container_install.sh` also writes `.env.prod.file` in the repository root for
Docker Compose interpolation. That generated file contains runtime metadata such
as ports, paths and Gunicorn tuning, not database/SMTP/Keycloak secrets.

Start or upgrade the production container with `container_install.sh` so the
Django installation, migrations and runtime `.env` are applied consistently:

```bash
bash container_install.sh \
  --install_conf /srv/containers/bind/pathocore-api/production_settings.txt \
  --git_revision current
```

For upgrades:

```bash
bash container_install.sh \
  --install_conf /srv/containers/bind/pathocore-api/production_settings.txt \
  --action upgrade \
  --git_revision current
```

To repair production bind-mount permissions without rebuilding or bootstrapping:

```bash
bash container_install.sh \
  --install_conf /srv/containers/bind/pathocore-api/production_settings.txt \
  --action fix-permissions
```

Validate from the server itself:

```bash
curl -I http://127.0.0.1:8000/openapi/
curl -I http://127.0.0.1:8000/swagger/
curl -I http://127.0.0.1:8000/v1/databrowser/overview-summary
```

### Databrowser summary cache

The databrowser summary endpoints use precomputed global summaries for the
default unfiltered view:

* `/v1/databrowser/overview-summary`
* `/v1/databrowser/metadata-summary`
* `/v1/databrowser/schema-summary`

Refresh the cache manually after large sample or metadata ingests:

```bash
docker compose -f docker-compose.test.yml exec app bash
cd /opt/pathocore-api
source virtualenv/bin/activate
python manage.py refresh_databrowser_cache
```

In Docker, a lightweight scheduler runs inside the `app` container and refreshes
the cache every Friday at 12:00 by default. The schedule can be overridden with:

```text
DATABROWSER_CACHE_REFRESH_WEEKDAY=4
DATABROWSER_CACHE_REFRESH_TIME=12:00
DATABROWSER_CACHE_REFRESH_ON_START=false
```

### Keycloak authentication

PathoCore validates `Bearer` JWTs issued by Keycloak. The API needs these
settings:

```text
KEYCLOAK_ISSUER=https://<keycloak-host>/realms/<realm>
KEYCLOAK_JWKS_URL=https://<keycloak-host>/realms/<realm>/protocol/openid-connect/certs
KEYCLOAK_AUDIENCE=pathocore-api
KEYCLOAK_CLIENT_ID=pathocore-web
```

Optional settings:

```text
KEYCLOAK_JWKS_CACHE_TTL_SECONDS=300
KEYCLOAK_JWKS_TIMEOUT_SECONDS=5
PATHOCORE_ENABLE_LEGACY_BASIC_AUTH=true
PATHOCORE_ENABLE_PUBLIC_READ_ENDPOINTS=true
PATHOCORE_CREATE_DEFAULT_SUPERUSER=false
DJANGO_SUPERUSER_USERNAME=
DJANGO_SUPERUSER_EMAIL=
DJANGO_SUPERUSER_PASSWORD=
```

Authorization is derived from the JWT `groups` claim. Supported group paths are
`/use-cases/<project>/<view|admin>` and `/superusers`.
The older `viewer` role is accepted as `view` during migration.

Configuration flow:

* Bash install: copy `conf/template_install_settings.txt`, fill the `KEYCLOAK_*`
  values, then run `install.sh`. The installer writes those values to
  `<INSTALL_PATH>/.env`; `template_settings.py` loads that file at runtime.
* Docker install: fill `conf/docker_test_settings.txt` or
  `conf/docker_production_settings.txt`, then run `container_install.sh`.
  The selected install settings are exported for Compose and also written to the
  installed app `.env`.
* Runtime environment variables override the installed `.env` values.

Missing Keycloak values warn while legacy auth is enabled and fail when legacy
auth is disabled.

Swagger UI, Redoc and the OpenAPI schema require authentication. They can be
opened with a valid Keycloak Bearer token or with a Django staff/superuser
session or Basic Auth credentials.

When using Keycloak:

```text
1. Open the configured Keycloak realm URL.
2. Log in with your use-case credentials.
3. Copy the access token.
4. Send API requests with: Authorization: Bearer <token>
```

For local Docker testing, Swagger and admin API access can also use the default
Django superuser credentials:

```text
admin / admin_pass
```

### API rate limiting

Public databrowser/read endpoints remain unauthenticated for the web public
area, while the API uses Django REST Framework `AnonRateThrottle` and
`UserRateThrottle` as basic overuse protection. Public endpoints use the
anonymous throttle path. Configure the shared rate with:

```text
PUBLIC_API_THROTTLE_RATE=500/hour
```

Requests over the public limit return the standard DRF `429 Too Many Requests`
response. This is operational protection for repeated public API calls, not a
replacement for production reverse-proxy or DoS controls.

The same configured DRF rate is used for anonymous and authenticated requests.

## Access Request Workflow

PathoCore keeps pending registration and approval state in its own database.
Keycloak remains the final identity and group store only after approval.

Public users can create requests:

```bash
curl -sS -X POST http://localhost:8000/v1/access-requests \
  -H "Content-Type: application/json" \
  -d '{
    "username": "new_user",
    "email": "new.user@example.org",
    "first_name": "New",
    "last_name": "User",
    "message": "I collaborate with the MEPRAM and RELECOV networks.",
    "requests": [
      {"use_case": "mepram", "role": "view"},
      {"use_case": "relecov", "role": "view"}
    ]
  }' | jq
```

The canonical API prefix is `/v1`. The legacy `/api/v1` prefix remains available temporarily while clients migrate back to `/v1`.

The user receives an email confirming that the request was received and remains
pending review.

Admins can review pending requests:

```bash
curl -sS -u admin:admin_pass \
  "http://localhost:8000/v1/access-requests?status=pending" | jq
```

Approve a request:

```bash
curl -sS -X POST -u admin:admin_pass \
  http://localhost:8000/v1/access-requests/<request_id>/approve \
  -H "Content-Type: application/json" \
  -d '{"review_note": "Approved for MEPRAM view access."}' | jq
```

Reject a request:

```bash
curl -sS -X POST -u admin:admin_pass \
  http://localhost:8000/v1/access-requests/<request_id>/reject \
  -H "Content-Type: application/json" \
  -d '{"review_note": "Missing project justification."}' | jq
```

Revoke a previously approved request:

```bash
curl -sS -X POST -u admin:admin_pass \
  http://localhost:8000/v1/access-requests/<request_id>/revoke \
  -H "Content-Type: application/json" \
  -d '{"review_note": "Access no longer required."}' | jq
```

Approval calls the Keycloak Admin REST API to create or enable the user, trigger
`execute-actions-email` with `UPDATE_PASSWORD` and `VERIFY_EMAIL`, and assign the
approved group path, for example:

```text
/use-cases/mepram/view
```

Configure these values for approval:

```text
KEYCLOAK_ADMIN_BASE_URL=http://keycloak:8080
KEYCLOAK_REALM=ciberisciii_datahub
KEYCLOAK_ADMIN_TOKEN_REALM=master
KEYCLOAK_ADMIN_CLIENT_ID=admin-cli
KEYCLOAK_ADMIN_USERNAME=admin
KEYCLOAK_ADMIN_PASSWORD=admin
```

Do not send temporary passwords by email. Keycloak must have SMTP configured for
`execute-actions-email`; otherwise approval can fail before permissions are
granted.

Request received, rejection, and revocation notifications are sent by
`pathocore-api` through Django email settings:

```text
EMAIL_HOST=mailpit
EMAIL_PORT=1025
EMAIL_USE_TLS=false
DEFAULT_FROM_EMAIL=no-reply@pathocore.local
```

New pending requests are notified to enabled Keycloak users with email in the
matching use-case admin group, for example `/use-cases/mepram/admin`. Configure
`PATHOCORE_ACCESS_REQUEST_ADMIN_EMAILS` only as a fallback or general copy.

In the local Docker test stack these messages are captured by Mailpit:

```text
http://127.0.0.1:8025
```

Revocation removes the approved Keycloak group but does not disable the whole
account.

For local Docker testing without SMTP or Mailpit, keep:

```text
KEYCLOAK_ADMIN_SEND_ACTION_EMAILS=false
```

The generic databrowser and variant read endpoints are intentionally public for
the no-login web experience. They are read-only, query-limited where applicable,
rate-limited through `PUBLIC_API_THROTTLE_RATE`, and can be disabled globally
with:

```text
PATHOCORE_ENABLE_PUBLIC_READ_ENDPOINTS=false
```

Disabling public read endpoints also disables anonymous access from the web app.

For a Dockerized API validating local host-issued tokens, keep the issuer as the
token sees it and point JWKS through the Docker host gateway:

```text
KEYCLOAK_ISSUER=http://127.0.0.1:8090/realms/ciberisciii_datahub
KEYCLOAK_JWKS_URL=http://host.docker.internal:8090/realms/ciberisciii_datahub/protocol/openid-connect/certs
```

## Installation outside Docker

PathoCore API can also be installed directly on a Linux server. This mode is intended
for controlled server deployments where the host already provides the required system
services such as MySQL/MariaDB and, if needed, a reverse proxy.

The installer expects:

* a reachable MySQL/MariaDB database
* a writable installation path, typically `/opt/pathocore-api`
* a configuration file based on `conf/template_install_settings.txt`

Basic flow:

```bash
cp conf/template_install_settings.txt install_settings.txt
nano install_settings.txt
sudo bash install.sh --install dep --conf install_settings.txt
bash install.sh --install app --git_revision develop --conf install_settings.txt
```

If the application is already installed and you need to deploy code changes, use upgrade mode:

```bash
bash install.sh --upgrade app --git_revision develop --conf install_settings.txt
```

# Documentation

This is an API-only project. Authenticated documentation is served via Swagger UI
at `/swagger/` and the OpenAPI schema at `/openapi/`.
