# PathoCore API

Django REST API for PathoCore genomic and epidemiological data.

PathoCore API provides shared schema management, sample and metadata ingestion,
variant ingestion, sample-history tracking, and search and DataBrowser services
for projects such as MEPRAM and RELECOV. It exposes versioned REST endpoints and
OpenAPI documentation, with project and laboratory access derived from
Keycloak groups. Deployment supports Docker, Podman, and reviewed bare-metal
installations through the BU-ISCIII deployment standard.

```mermaid
flowchart LR
    client[Web applications and API clients]

    subgraph deployment[PathoCore deployment]
        apache[Apache reverse proxy]
        api[PathoCore Django REST API]
        scheduler[Supercronic scheduler]
        keycloak[Keycloak identity service]
        keycloak_db[(Keycloak MySQL data)]
    end

    app_db[(PathoCore application database)]
    smtp[SMTP service]

    client -->|REST, OpenAPI and health| apache
    client -->|OIDC authentication| apache
    apache -->|API routes| api
    apache -->|Identity routes| keycloak
    api -->|Samples, metadata and cached summaries| app_db
    api -->|Validate tokens and manage approved access| keycloak
    keycloak --> keycloak_db
    api -.->|Notifications| smtp
    scheduler -->|Refresh DataBrowser caches| api
```

For bugs, deployment problems, or feature requests, open an issue in the
[PathoCore API issue tracker](https://github.com/BU-ISCIII/pathocore-api/issues).
Do not include credentials, tokens, patient data, or other sensitive deployment
information in public issues.

- [Get the code (required)](#get-the-code-required)
- [Choose your path](#choose-your-path)
- [Minimum requirements](#minimum-requirements)
- [Docker deployment](#docker-deployment)
  - [Local test stack](#local-test-stack)
  - [Production container](#production-container)
  - [Manage containers after installation](#manage-containers-after-installation)
  - [Upgrade docker deployment](#upgrade-docker-deployment)
- [Bare-metal deployment (Ubuntu/CentOS)](#bare-metal-deployment-ubuntucentos)
- [Common operations (Docker + bare-metal)](#common-operations-docker--bare-metal)
- [Final configuration steps](#final-configuration-steps)
- [Developer notes](#developer-notes)
- [Application documentation](#application-documentation)

## Get the code (required)

```bash
git clone https://github.com/BU-ISCIII/pathocore-api.git pathocore-api
cd pathocore-api
```

For an orchestrated deployment, every external build context in the service
table must exist at the declared path relative to this checkout.

## Choose your path

| Capability | Supported | Owner or command |
|---|---:|---|
| Docker local test | Yes | `container_install.sh --test --engine docker` |
| Podman local test | Yes | `container_install.sh --test --engine podman` |
| Docker production | Yes | `container_install.sh --engine docker` |
| Podman production | Yes | `container_install.sh --engine podman` |
| Bare metal | Profile-specific | See [Bare-metal deployment](#bare-metal-deployment-ubuntucentos) |
| Upgrade | Yes | `--action upgrade` |
| Permission repair | Yes | `--action fix-permissions` |
| Backup and restore | Yes | Operator-owned; follow [LEAME.md](LEAME.md) |

Services:

| Service | Profile | Build context | Internal port |
|---|---|---|---:|
| `app` | `django` | `.` | settings: `APP_PORT` |

- Django services build with an ephemeral settings secret, render protected host settings, and run controlled migration/bootstrap steps.
- Scheduled Django jobs run through Supercronic inside the application
  container from the project's `CRONJOBS` setting.

Selected add-ons:

- Apache source configuration lives under `conf/apache/`; customize its virtual hosts and routes there. The installer renders final bind sources under `deployment/apache/`.
- Keycloak provides centralized identity with a health-checked MySQL service, realm import, and persistent database state.

## Minimum requirements

- Git and access to every declared build context.
- Docker Engine with Compose v2, or Podman with a Compose provider.
- Enough disk and memory for image builds and persistent application data.
- A protected production settings file for every application and selected add-on.
- Production DNS, TLS termination, database, storage, email, identity, backup,
  and monitoring services required by the selected profiles.

Copy each application's settings and each `conf/<addon>/*_production_settings.txt`
to protected ignored files, set mode `0600`, and replace every `CHANGE_ME`. The exact
meaning and security classification of settings is in
[`conf/INSTALL_SETTINGS.md`](conf/INSTALL_SETTINGS.md).

Create the ignored deployment settings directory and copy every production
template that this topology consumes:

```bash
install -d -m 0700 deployment/settings
install -m 0600 conf/docker_production_settings.txt deployment/settings/app_production_settings.txt
install -m 0600 conf/apache/apache_production_settings.txt deployment/settings/apache_production_settings.txt
install -m 0600 conf/keycloak/keycloak_production_settings.txt deployment/settings/keycloak_production_settings.txt
```

Edit only the copies under `deployment/settings/`, replace every `CHANGE_ME`,
and keep their mode at `0600`. Both installation workflows below point to
these protected copies.

## Docker deployment

Both engines use the same lifecycle and Compose files. Do not invoke Compose
directly for the first install or an upgrade: the installer also renders
configuration, prepares permissions, waits for readiness, and runs bootstrap.

### Local test stack

Docker:

```bash
bash container_install.sh --test --action install --engine docker \
  --git_revision current
```

Podman:

```bash
bash container_install.sh --test --action install --engine podman \
  --git_revision current
```

Test settings and test services are disposable. Verify either deployment with:

```bash
bash scripts/smoke_test.sh --test --engine docker
# or: bash scripts/smoke_test.sh --test --engine podman
```

Django test installation creates the disposable database declared by the test
Compose profile, waits for it, applies committed migrations, optionally loads
fixtures, runs selected data scripts, collects static files, and performs the
generated health checks.

Migration/data scripts are repeatable `django-extensions` runscript names. Use
`--script_before` for preparation before migrations and `--script` (an alias of
`--script_after`) for a transformation after migrations:

```bash
bash container_install.sh --test --action install --engine docker \
  --script_before prepare_test_data \
  --script migrate_optional_values
```

Fresh installs automatically load `conf/first_install_tables.json` when the
application provides it. Use `--skip_tables` for an exceptional fresh install
without that fixture, or `--tables` to load it explicitly during an upgrade.

`--demo_data_map <service,path>`, `--skip_demo_data`, `--skip_test_data`, and
`--skip_test_data_service <service>` are part of the standard interface.
`--demo_data <path>` remains a single-service compatibility option. A project
that supplies fixtures or demo files must set
`application_supports_test_data=true` and implement `load_test_deployment_data`
in its wrapper; otherwise explicit demo data is rejected. Production never
selects or loads demo data by default, and upgrades never reload it.

PathoCore has no default demo-data download URL. A fresh test install therefore
requires `--demo_data <path>` unless demo loading is explicitly disabled with
`--skip_demo_data` or `--skip_test_data`.

PathoCore accepts `.sql` and `.sql.gz` data-only seeds for fresh test or
production installations when `--demo_data` is explicitly supplied. The seed
must match the checked-out migrations and must not create or replace schema or
`django_migrations` history:

```bash
bash container_install.sh --test --action install --engine docker \
  --demo_data /path/to/pathocore-test-data.sql.gz
```

The reviewed PathoCore seed may replace initial reference rows, but it must not
replace their tables. Fresh installs still run the standard initial fixture
before importing demo data. Production never selects a seed implicitly, and
upgrades never reload one.

For an automatic first administrator, set `CREATE_INITIAL_SUPERUSER=true` and
the `DJANGO_SUPERUSER_*` values in the selected test settings before install.
An existing account is never reset. Open the loopback URL using `APP_PORT` from
the rendered test environment, or `APACHE_PORT` when the Apache add-on is used.

### Production container

Prepare the protected settings files and deploy a reviewed tag or commit.

Docker:

```bash
bash container_install.sh --action install --engine docker \
  --git_revision <reviewed-tag-or-commit> \
  --install_conf_map app,deployment/settings/app_production_settings.txt --install_conf_map apache,deployment/settings/apache_production_settings.txt --install_conf_map keycloak,deployment/settings/keycloak_production_settings.txt
```

Podman:

```bash
bash container_install.sh --action install --engine podman \
  --git_revision <reviewed-tag-or-commit> \
  --install_conf_map app,deployment/settings/app_production_settings.txt --install_conf_map apache,deployment/settings/apache_production_settings.txt --install_conf_map keycloak,deployment/settings/keycloak_production_settings.txt
```

The installer creates `.env.production.file` for later direct Compose
operations. It contains generated runtime values, including secrets copied
from the protected settings sources, so keep it mode `0600`, excluded from Git,
and inside the protected configuration backup. Neither the protected settings
nor this generated environment file is copied into image layers.

#### Persist logs/documents on the host

| Asset | Production location | Backup/rebuild policy |
|---|---|---|
| `app` database | External production database | Database backup before migration |
| `app` documents | `app_documents` named volume | Volume backup |
| `app` static | `app_static` named volume | Replaceable through collectstatic |
| `app` logs | `/var/log/local/pathocore-api/apps` host bind | Retain/rotate per institutional log policy |
| `app` rendered settings | `/srv/containers/bind/pathocore-api/settings/` host bind | Protected configuration backup |
| Apache logs | `/var/log/local/pathocore-api/apache` host bind | Retain/rotate per institutional log policy |
| Rendered Apache configuration | `deployment/apache/` in the deployment checkout | Rebuildable; preserve reviewed source configuration |
| Keycloak database | `keycloak_db_data` MySQL named volume | Database and identity backup |
| Keycloak staged realm | `/srv/containers/bind/pathocore-api/keycloak/realm-import/` read-only host bind | Back up with deployment configuration; reproducible bootstrap input, not authoritative identity state |

The standard fixes application binds below `/srv/containers/bind/pathocore-api`
and logs below `/var/log/local/pathocore-api`. The operator must still record the
backup owner, retention, actual engine volume names, and restore-test evidence
for every non-rebuildable asset. Never treat a container writable layer as
persistent storage.

#### Reverse proxy and application server

The selected profiles and add-ons define the internal application server and
proxy topology. Review public hostnames, TLS ownership, forwarded headers,
request limits, timeouts, health paths, and static/media routing together.

#### Scheduled jobs

PathoCore refreshes its DataBrowser and use-case summary caches every Friday at
12:00 through `core.cron.refresh_databrowser_caches`. Container deployments run
the job through Supercronic from the project's `CRONJOBS` setting and append
output to `logs/crontab.log`. Retry either cache manually with:

```bash
python manage.py refresh_databrowser_cache
python manage.py refresh_use_case_cache
```

For bare-metal deployments, register the same setting with
`python manage.py crontab add` and verify it with
`python manage.py crontab show`.

### Manage containers after installation

Use the engine that performed the installation:

```bash
docker compose --env-file .env.production.file -f docker-compose.prod.yml ps
docker compose --env-file .env.production.file -f docker-compose.prod.yml logs --tail 200
docker compose --env-file .env.production.file -f docker-compose.prod.yml restart
```

```bash
podman compose --env-file .env.production.file -f docker-compose.prod.yml ps
podman compose --env-file .env.production.file -f docker-compose.prod.yml logs --tail 200
podman compose --env-file .env.production.file -f docker-compose.prod.yml restart
```

### Upgrade docker deployment

After taking a consistent backup and reading the version-specific upgrade
notes:

```bash
bash container_install.sh --action upgrade --engine podman \
  --git_revision <new-reviewed-tag-or-commit> \
  --install_conf_map app,deployment/settings/app_production_settings.txt --install_conf_map apache,deployment/settings/apache_production_settings.txt --install_conf_map keycloak,deployment/settings/keycloak_production_settings.txt
```

Replace `podman` with `docker` for a Docker-managed deployment. Stop on build,
readiness, bootstrap, migration, or smoke-test failure. See [LEAME.md](LEAME.md)
for the ordered production checklist and rollback decision.

## Bare-metal deployment (Ubuntu/CentOS)

### Install

#### Clone the repository

Use [Get the code (required)](#get-the-code-required) and check out the reviewed
revision.

#### Prepare the database

Provision the application database and least-privilege account outside the
installer. Confirm that the host can reach it before bootstrap.

#### Configure install_settings.txt

Start from `conf/docker_production_settings.txt`, but review all paths and
container-oriented defaults for the target host. Keep the resulting file
ignored and mode `0600`.

#### Run install.sh

The Django profile includes `install.sh` for application staging and bootstrap,
but system package, database, web-server, service-manager, TLS, and backup
provisioning remain host-specific. Bare-metal installation is supported only
after the application developer documents and tests those integrations.

```bash
# Stage application files and dependencies.
bash install.sh --stage install --git_revision current \
  --conf deployment/settings/app_production_settings.txt

# Bootstrap the prepared runtime (settings, migrations and static files).
bash install.sh --bootstrap install \
  --conf deployment/settings/app_production_settings.txt
```

For upgrades, take a backup and replace both `install` actions with `upgrade`.
Do not use container-oriented paths or defaults on a bare-metal host without an
application-specific review.

For a host-managed Apache 2.4 deployment, adapt the reviewed virtual host from
`conf/apache/` to the distribution path. The generated add-on files target the
container image, so do not copy them blindly without checking module names,
paths, runtime user, TLS ownership, and log locations.

Ubuntu/Debian baseline:

```bash
sudo cp <reviewed-apache-vhost.conf> /etc/apache2/sites-available/pathocore-api.conf
sudo a2enmod proxy proxy_http headers
sudo a2ensite pathocore-api.conf
sudo apache2ctl configtest
sudo systemctl reload apache2
```

CentOS/RHEL baseline:

```bash
sudo cp <reviewed-apache-vhost.conf> /etc/httpd/conf.d/pathocore-api.conf
sudo httpd -t
sudo systemctl reload httpd
```

The reviewed virtual host must define the public `ServerName`, proxy to the
Django `APP_PORT`, serve the correct static/media paths, preserve forwarded
scheme/host headers, and use institutionally managed TLS and logs.

### Upgrade bare-metal deployment

Follow the same staged lifecycle with `upgrade` only after a consistent backup
and review of the version-specific guide.

## Common operations (Docker + bare-metal)

### Database creation, users and grants

Production databases are externally managed unless the application documents a
different supported topology. Create a dedicated schema and least-privilege
account, verify connectivity from the application container, and keep DBA
commands and credentials outside this repository.

Connect as an authorized database administrator without putting the password
on the command line:

```bash
DB_HOST='CHANGE_ME'
DB_PORT='3306'
DB_ADMIN='CHANGE_ME'
DB_NAME='CHANGE_ME'
DB_USER='CHANGE_ME'
mysql --host="$DB_HOST" --port="$DB_PORT" --user="$DB_ADMIN" --password
```

Create the application database and account. Replace every angle-bracket value;
restrict the account host further than `%` when the network topology permits.

```sql
CREATE DATABASE `<db-name>`
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER '<db-user>'@'%' IDENTIFIED BY '<strong-generated-password>';
GRANT ALL PRIVILEGES ON `<db-name>`.* TO '<db-user>'@'%';
FLUSH PRIVILEGES;
```

Verify the same endpoint and least-privilege credentials configured for the
application:

```bash
mysql --host="$DB_HOST" --port="$DB_PORT" --user="$DB_USER" --password \
  --database="$DB_NAME" --execute='SELECT 1;'
```

### Backups

Back up every non-rebuildable row in the persistence table from one consistent
recovery point before installation or upgrade. Record the revision, image IDs,
settings files, and backup identifiers.

```bash
BACKUP_DIR="/srv/containers/backup/pathocore-api/$(date +%Y%m%d_%H%M%S)"
DOCUMENTS_VOLUME='CHANGE_ME'
DB_HOST='CHANGE_ME'
DB_PORT='3306'
DB_NAME='CHANGE_ME'
DB_USER='CHANGE_ME'
mkdir -p "$BACKUP_DIR"
git rev-parse HEAD > "$BACKUP_DIR/git-revision.txt"
cp .env.production.file "$BACKUP_DIR/"
cp deployment/settings/app_production_settings.txt "$BACKUP_DIR/"
cp deployment/settings/apache_production_settings.txt "$BACKUP_DIR/"
cp deployment/settings/keycloak_production_settings.txt "$BACKUP_DIR/"
chmod -R go-rwx "$BACKUP_DIR"

mysqldump --single-transaction --routines --triggers \
  --host="$DB_HOST" --port="$DB_PORT" --user="$DB_USER" --password \
  "$DB_NAME" > "$BACKUP_DIR/database.sql"

podman volume ls | grep 'pathocore-api'
podman volume export "$DOCUMENTS_VOLUME" > "$BACKUP_DIR/documents.tar"
podman compose --env-file .env.production.file -f docker-compose.prod.yml \
  exec -T keycloak_db sh -c \
  'exec mysqldump --single-transaction --routines --triggers -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  > "$BACKUP_DIR/keycloak-database.sql"
tar -C /srv/containers/bind -czf "$BACKUP_DIR/bind-mounts.tar.gz" pathocore-api
sha256sum "$BACKUP_DIR"/* > "$BACKUP_DIR/SHA256SUMS"
```

For Docker, archive a named volume through a temporary container after ensuring
the application is not writing to it:

```bash
docker run --rm \
  --volume "$DOCUMENTS_VOLUME":/data:ro \
  --volume "$BACKUP_DIR":/backup \
  alpine tar -C /data -cf /backup/documents.tar .
```

The full ordered backup checklist, including logs and image metadata, is in
[LEAME.md](LEAME.md).

### Restore / rollback

An image-only rollback is safe only when the previous application version
supports the current schema and persistent-file format. Otherwise stop writes,
restore the database and files from the same recovery point, deploy the recorded
compatible revision, and rerun all smoke tests.

Compatible application-only rollback:

```bash
bash container_install.sh --action upgrade --engine podman \
  --git_revision <previous-reviewed-revision> \
  --install_conf_map app,deployment/settings/app_production_settings.txt --install_conf_map apache,deployment/settings/apache_production_settings.txt --install_conf_map keycloak,deployment/settings/keycloak_production_settings.txt
```

Full restore when schema or persistent-file formats are incompatible must run
from a clean checkout of the revision recorded in `git-revision.txt`:

```bash
BACKUP_DIR='/srv/containers/backup/pathocore-api/CHANGE_ME'
DOCUMENTS_VOLUME='CHANGE_ME'
DB_HOST='CHANGE_ME'
DB_PORT='3306'
DB_NAME='CHANGE_ME'
DB_USER='CHANGE_ME'
podman compose --env-file .env.production.file -f docker-compose.prod.yml down
mysql --host="$DB_HOST" --port="$DB_PORT" --user="$DB_USER" --password \
  "$DB_NAME" < "$BACKUP_DIR/database.sql"
podman volume import "$DOCUMENTS_VOLUME" "$BACKUP_DIR/documents.tar"
tar -C /srv/containers/bind -xzf "$BACKUP_DIR/bind-mounts.tar.gz"
install -d -m 0700 deployment/settings
install -m 0600 "$BACKUP_DIR/app_production_settings.txt" deployment/settings/app_production_settings.txt
install -m 0600 "$BACKUP_DIR/apache_production_settings.txt" deployment/settings/apache_production_settings.txt
install -m 0600 "$BACKUP_DIR/keycloak_production_settings.txt" deployment/settings/keycloak_production_settings.txt
bash container_install.sh --action fix-permissions --engine podman \
  --install_conf_map app,deployment/settings/app_production_settings.txt --install_conf_map apache,deployment/settings/apache_production_settings.txt --install_conf_map keycloak,deployment/settings/keycloak_production_settings.txt
podman compose --env-file .env.production.file -f docker-compose.prod.yml up -d keycloak_db
until podman compose --env-file .env.production.file -f docker-compose.prod.yml \
  exec -T keycloak_db sh -c \
  'mysqladmin ping -h 127.0.0.1 -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" --silent'; do sleep 2; done
podman compose --env-file .env.production.file -f docker-compose.prod.yml \
  exec -T keycloak_db sh -c \
  'exec mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  < "$BACKUP_DIR/keycloak-database.sql"
```

Then deploy the revision recorded in `git-revision.txt`, start the deployment,
and run the smoke test before reopening service. For Docker volume restoration,
reverse the temporary-container archive command by mounting the empty target
volume at `/data` and extracting `/backup/documents.tar` there.

### What to do if something fails

1. Preserve installer output, `compose ps`, image IDs, and service logs.
2. Test the direct application health endpoint and dependencies.
3. Test proxy routing, public DNS, and TLS after direct health succeeds.
4. Run permission repair for reviewed ownership or SELinux drift:

   ```bash
   bash container_install.sh --action fix-permissions --engine podman \
     --install_conf_map app,deployment/settings/app_production_settings.txt --install_conf_map apache,deployment/settings/apache_production_settings.txt --install_conf_map keycloak,deployment/settings/keycloak_production_settings.txt
   ```

5. Do not fake migrations, delete volumes, or rebuild from an unrecorded
   revision as a first response.

### Service-specific operational commands

#### Django service `app`

```bash
# Logs and an interactive shell (replace podman with docker when applicable).
podman compose --env-file .env.production.file -f docker-compose.prod.yml \
  logs --tail 200 app
podman compose --env-file .env.production.file -f docker-compose.prod.yml \
  exec app bash

# Rebuild static assets without running migrations.
podman compose --env-file .env.production.file -f docker-compose.prod.yml \
  exec app bash -lc \
  'cd "$INSTALL_PATH" && source virtualenv/bin/activate && python manage.py collectstatic --noinput'

# Inspect Django and migration state before deciding whether to recover.
podman compose --env-file .env.production.file -f docker-compose.prod.yml \
  exec app bash -lc \
  'cd "$INSTALL_PATH" && source virtualenv/bin/activate && python manage.py check --deploy && python manage.py showmigrations --plan'
```

For bootstrap recovery, fix the cause and rerun `container_install.sh` with the
same revision, protected configuration, and `--action install` or `upgrade`.
This safely recreates the temporary runtime configuration and repeats the
controlled migration/fixture/static lifecycle. Direct `manage.py migrate` is a
diagnostic last resort and must use the same backup and release procedure.

#### Apache service

```bash
podman compose --env-file .env.production.file -f docker-compose.prod.yml \
  logs --tail 200 apache
podman compose --env-file .env.production.file -f docker-compose.prod.yml \
  exec apache httpd -t

APACHE_PORT='CHANGE_ME'
SERVER_STATUS_SERVER_NAME='localhost'
curl --fail --show-error \
  --header "Host: $SERVER_STATUS_SERVER_NAME" \
  "http://127.0.0.1:$APACHE_PORT/server-status?auto"
```

Keep `SERVER_STATUS_ALLOW_FROM` limited to trusted diagnostic hosts. If SELinux
is enabled, inspect the persistent log bind and confirm a container-compatible
label before restarting:

```bash
ls -ldZ /var/log/local/pathocore-api/apache
```

An Apache failure containing `ModSecurity: Failed to open debug log file` often
means the existing `modsec_debug.log` inode has stale ownership or labeling.
Preserve it for diagnosis, run `fix-permissions`, and restart Apache. If it must
be replaced, move it to a timestamped backup instead of deleting evidence:

```bash
sudo mv /var/log/local/pathocore-api/apache/modsec_debug.log \
  /var/log/local/pathocore-api/apache/modsec_debug.log.blocked
bash container_install.sh --action fix-permissions --engine podman \
  --install_conf_map app,deployment/settings/app_production_settings.txt --install_conf_map apache,deployment/settings/apache_production_settings.txt --install_conf_map keycloak,deployment/settings/keycloak_production_settings.txt
podman compose --env-file .env.production.file -f docker-compose.prod.yml restart apache
```

#### Keycloak realm bind

The installer copies repository-owned JSON from `KEYCLOAK_REALM_SOURCE_PATH`
into the deployment-owned `KEYCLOAK_IMPORT_PATH` before Compose starts. With
the generated production default, the read-only bind source is:

```text
/srv/containers/bind/pathocore-api/keycloak/realm-import/
```

Do not change permissions on the repository source. The installer creates the
staging directory when `/srv/containers/bind/pathocore-api` is writable by the
deployment user and assigns staged files to Keycloak as `1000:0` with mode
`0640`. Back up this directory with the other protected deployment binds, but
use `keycloak_db_data` as the authoritative identity backup.

## Final configuration steps

Complete these checks with reviewed non-production identities before accepting
a new installation. Set `PUBLIC_URL` to the externally visible PathoCore base
URL and obtain a valid access token from the configured Keycloak client.

1. Verify the unauthenticated deployment health endpoint:

   ```bash
   PUBLIC_URL='https://pathocore-api.example.org'
   curl --fail --show-error "$PUBLIC_URL/health/"
   ```

2. Confirm that `/swagger/` rejects anonymous access, then opens successfully
   for an authenticated user:

   ```bash
   curl --output /dev/null --silent --write-out '%{http_code}\n' \
     "$PUBLIC_URL/swagger/"
   ACCESS_TOKEN='<reviewed-user-access-token>'
   curl --fail --show-error --header "Authorization: Bearer $ACCESS_TOKEN" \
     "$PUBLIC_URL/swagger/" >/dev/null
   ```

3. Validate OIDC token verification and inspect the derived Keycloak groups,
   use-case roles, and laboratory permissions:

   ```bash
   curl --fail --show-error \
     --header "Authorization: Bearer $ACCESS_TOKEN" \
     "$PUBLIC_URL/v1/auth/me"
   ```

4. Exercise the access-request workflow from `/swagger/`: load the public
   `GET /v1/access-requests/catalog`, submit a controlled request with
   `POST /v1/access-requests`, and approve it with a reviewer token. Confirm
   that PathoCore creates or enables the Keycloak user, assigns the expected
   `/use-cases/...` group, and allows the approved token to access that scope.

5. Confirm SMTP delivery to both the requester and configured administrators
   during the controlled access-request workflow. Check the SMTP relay and
   application logs as well as the recipient inboxes; PathoCore notifications
   use `fail_silently=True`, so API success alone does not prove delivery.

6. Run both cache refreshes once and inspect their output. Then confirm the
   Friday 12:00 job is present in the container and writes to
   `logs/crontab.log`:

   ```bash
   podman compose --env-file .env.production.file -f docker-compose.prod.yml \
     exec app bash -lc \
     'cd "$INSTALL_PATH" && source virtualenv/bin/activate && python manage.py refresh_databrowser_cache && python manage.py refresh_use_case_cache'
   podman compose --env-file .env.production.file -f docker-compose.prod.yml \
     exec app bash -lc 'cat "$INSTALL_PATH/cron/pathocore-api"'
   ```

Record the tested revision, public URL, Keycloak realm/client, test identity,
email evidence, cache result, and acceptance owner without storing tokens or
credentials in the report.

## Developer notes

### Shared container installer library

`container_install.sh` sources the vendored files under
`deployment/lib/container/`. Do not edit those copies. Check or update them
from the standards repository with `scaffold.py check-lib` or `sync-lib`.

### Schema migration workflow

Django migrations MUST be generated, reviewed, tested, and committed with the
release. Installation and production upgrade run `migrate --noinput`; they
MUST NOT run `makemigrations` or silently manufacture schema history.

For a legacy application entering the standard:

1. Generate and commit baseline migrations from the last supported stable tag.
2. Generate and commit new migrations for later model changes.
3. Verify the committed migration history matches the supported production
   database before deploying it.
4. Put ordered data transformations in version-specific upgrade guides and run
   them through `--script_before`, `--script_after`, or `--script`.
5. Verify `showmigrations --plan` has no unapplied entries after bootstrap.

Never use `--fake` to conceal a failed or partially applied migration. New
installations and upgrades use the committed migration graph.

### Persistent host paths

Keep source checkouts, protected configuration, bind mounts, engine-managed
volumes, logs, and backups separate. For rootless Podman, run the installer as
the same unprivileged account every time and use `fix-permissions` instead of
manually changing engine storage.

### Verification of the installation

```bash
bash scripts/smoke_test.sh --engine podman
```

After the baseline smoke test succeeds, complete the authenticated OIDC,
access-request, email and DataBrowser cache checks in
[Final configuration steps](#final-configuration-steps).

## Application documentation

- The deployed OpenAPI interface is available at authenticated `/swagger/` and
  `/swagger/redoc/` routes.
- Deployment configuration is documented in
  [`conf/INSTALL_SETTINGS.md`](conf/INSTALL_SETTINGS.md).
- Report defects and request support through the
  [PathoCore API issue tracker](https://github.com/BU-ISCIII/pathocore-api/issues).
  Never include credentials, access tokens, patient data or protected settings
  in an issue.
