#!/usr/bin/env bash
set -euo pipefail

PATHOCORE_API_VERSION="1.0.0"

usage() {
cat << EOF
This script installs and upgrades PathoCore API in containers.

Usage:
  $0 [--test] [--git_revision <branch|tag|sha|current>] [--compose_file <path>] [--install_conf <path>] [--engine docker|podman] [--action install|upgrade|fix-permissions] [--tables] [--pathocore_api_sql <path>]

Options:
  --test           Use docker-compose.test.yml and conf/docker_test_settings.txt
  --git_revision   Git revision passed to image build/install. Use 'current' to keep current checked-out branch
  --compose_file   Override compose file path
  --install_conf   Settings file consumed at runtime by install.sh
  --engine         docker (default) or podman
  --action         install (default), upgrade, or fix-permissions
  --tables         Load conf/first_install_tables.json after migrate
  --pathocore_api_sql
                   Import a PathoCore API MySQL seed dump after migrations (.sql or .sql.gz).
                   This requires a Compose-managed db service, as in test mode.
  --help           Show this help
  --version        Show script version

Examples:
  bash $0 --test --git_revision current
  bash $0 --test --git_revision current --pathocore_api_sql ../pathocore_api_testing_seed.sql.gz
  bash $0 --install_conf /srv/containers/bind/pathocore-api/production_settings.txt --git_revision main
  bash $0 --install_conf /srv/containers/bind/pathocore-api/production_settings.txt --action upgrade --git_revision main
EOF
}

reset=true
for arg in "$@"; do
    if [ -n "${reset:-}" ]; then
        unset reset
        set --
    fi
    case "$arg" in
        --test) set -- "$@" -t ;;
        --git_revision) set -- "$@" -g ;;
        --compose_file) set -- "$@" -c ;;
        --install_conf) set -- "$@" -s ;;
        --engine) set -- "$@" -e ;;
        --action) set -- "$@" -a ;;
        --tables) set -- "$@" -l ;;
        --pathocore_api_sql) set -- "$@" -p ;;
        --help) set -- "$@" -h ;;
        --version) set -- "$@" -v ;;
        *) set -- "$@" "$arg" ;;
    esac
done

mode="production"
git_revision=""
compose_file=""
install_conf=""
engine="docker"
action="install"
load_tables=false
pathocore_api_sql=""

while getopts ":tg:c:s:e:a:lp:hv" opt; do
    case "$opt" in
        t) mode="test" ;;
        g) git_revision="$OPTARG" ;;
        c) compose_file="$OPTARG" ;;
        s) install_conf="$OPTARG" ;;
        e)
            engine="$OPTARG"
            if [[ "$engine" != "docker" && "$engine" != "podman" ]]; then
                echo "Invalid engine '$engine'. Use docker or podman."
                exit 1
            fi
            ;;
        a)
            action="$OPTARG"
            if [[ "$action" != "install" && "$action" != "upgrade" && "$action" != "fix-permissions" ]]; then
                echo "Invalid action '$action'. Use install, upgrade, or fix-permissions."
                exit 1
            fi
            ;;
        l) load_tables=true ;;
        p) pathocore_api_sql="$OPTARG" ;;
        h)
            usage
            exit 0
            ;;
        v)
            echo "$PATHOCORE_API_VERSION"
            exit 0
            ;;
        :)
            echo "Option -$OPTARG requires an argument."
            exit 1
            ;;
        \?)
            echo "Invalid option: -$OPTARG"
            exit 1
            ;;
    esac
done
shift $((OPTIND-1))

repo_root="$(pwd)"

if [ "$mode" = "test" ]; then
    compose_file="${compose_file:-docker-compose.test.yml}"
    install_conf="${install_conf:-conf/docker_test_settings.txt}"
    git_revision="${git_revision:-develop}"
else
    compose_file="${compose_file:-docker-compose.prod.yml}"
    git_revision="${git_revision:-main}"
    if [ -z "$install_conf" ]; then
        echo "Production deployments require --install_conf with a non-committed settings file."
        exit 1
    fi
fi

if [ ! -f "$compose_file" ]; then
    echo "Compose file not found: $compose_file"
    exit 1
fi

if [ ! -f "$install_conf" ]; then
    echo "Install settings file not found: $install_conf"
    exit 1
fi

if [ -n "$pathocore_api_sql" ] && [ ! -f "$pathocore_api_sql" ]; then
    echo "PathoCore API SQL file not found: $pathocore_api_sql"
    exit 1
fi

if [[ "$install_conf" = /* ]]; then
    host_install_conf_path="$install_conf"
else
    host_install_conf_path="$repo_root/$install_conf"
fi

read_install_conf_value() {
    local key="$1"
    local file="$2"
    bash -c '
        set -a
        . "$1"
        key="$2"
        printf "%s" "${!key-}"
    ' _ "$file" "$key"
}

config_value_or_default() {
    local key="$1"
    local default_value="$2"
    local env_value="${!key:-}"
    local config_value=""

    if [ -n "$env_value" ]; then
        echo "$env_value"
        return 0
    fi

    config_value="$(read_install_conf_value "$key" "$host_install_conf_path")"
    if [ -n "$config_value" ]; then
        echo "$config_value"
    else
        echo "$default_value"
    fi
}

if [ "$git_revision" = "current" ]; then
    git_revision="$(git rev-parse --abbrev-ref HEAD)"
fi

if [ "$engine" = "docker" ]; then
    command -v docker >/dev/null 2>&1 || { echo "docker not found"; exit 1; }
    COMPOSE_CMD=(docker compose)
    ENGINE_CMD=(docker)
else
    command -v podman >/dev/null 2>&1 || { echo "podman not found"; exit 1; }
    if command -v podman-compose >/dev/null 2>&1; then
        COMPOSE_CMD=(podman-compose)
    else
        COMPOSE_CMD=(podman compose)
    fi
    ENGINE_CMD=(podman)
fi

compose_exec() {
    "${COMPOSE_CMD[@]}" "$@"
}

engine_exec() {
    "${ENGINE_CMD[@]}" "$@"
}

APP_REPO_PATH="${APP_REPO_PATH:-/srv/pathocore-api}"
APP_INSTALL_PATH="$(config_value_or_default INSTALL_PATH /opt/pathocore-api)"
APP_READY_FILE="${APP_READY_FILE:-${APP_INSTALL_PATH}/.container_install_ready}"
APP_SERVICE="${APP_SERVICE:-app}"
APP_PORT="$(config_value_or_default APP_PORT 8000)"
PATHOCORE_API_BIND_HOST="$(config_value_or_default PATHOCORE_API_BIND_HOST 127.0.0.1)"
PATHOCORE_API_PORT="$(config_value_or_default PATHOCORE_API_PORT "$APP_PORT")"
PATHOCORE_HOST_LOG_DIR="$(config_value_or_default PATHOCORE_HOST_LOG_DIR /var/log/local/pathocore-api/apps)"
WEB_CONCURRENCY="$(config_value_or_default WEB_CONCURRENCY 2)"
GUNICORN_THREADS="$(config_value_or_default GUNICORN_THREADS 2)"
GUNICORN_TIMEOUT="$(config_value_or_default GUNICORN_TIMEOUT 120)"
GUNICORN_KEEPALIVE="$(config_value_or_default GUNICORN_KEEPALIVE 5)"
DATABROWSER_CACHE_SCHEDULER_ENABLED="$(config_value_or_default DATABROWSER_CACHE_SCHEDULER_ENABLED true)"
DATABROWSER_CACHE_REFRESH_WEEKDAY="$(config_value_or_default DATABROWSER_CACHE_REFRESH_WEEKDAY 4)"
DATABROWSER_CACHE_REFRESH_TIME="$(config_value_or_default DATABROWSER_CACHE_REFRESH_TIME 12:00)"
DATABROWSER_CACHE_REFRESH_ON_START="$(config_value_or_default DATABROWSER_CACHE_REFRESH_ON_START false)"

if [ "$mode" = "production" ]; then
    build_install_conf_container="${PATHOCORE_BUILD_INSTALL_CONF:-conf/docker_production_settings.txt}"
else
    build_install_conf_container="${PATHOCORE_BUILD_INSTALL_CONF:-conf/docker_test_settings.txt}"
fi
runtime_install_conf_container="${APP_REPO_PATH}/.runtime_install_conf.txt"

compose_env_file="$repo_root/.env.prod.file"

write_compose_env_file() {
    if [ "$mode" != "production" ]; then
        return 0
    fi

    cat > "$compose_env_file" << EOF
# Generated by container_install.sh from $(basename "$host_install_conf_path").
# Used by Docker Compose for docker-compose.prod.yml interpolation.
# It intentionally contains runtime metadata, not database/SMTP/Keycloak secrets.
GIT_REVISION=$git_revision
INSTALL_CONF=$build_install_conf_container
APP_INSTALL_PATH=$APP_INSTALL_PATH
APP_REPO_PATH=$APP_REPO_PATH
APP_READY_FILE=$APP_READY_FILE
APP_PORT=$APP_PORT
PATHOCORE_API_BIND_HOST=$PATHOCORE_API_BIND_HOST
PATHOCORE_API_PORT=$PATHOCORE_API_PORT
PATHOCORE_HOST_LOG_DIR=$PATHOCORE_HOST_LOG_DIR
WEB_CONCURRENCY=$WEB_CONCURRENCY
GUNICORN_THREADS=$GUNICORN_THREADS
GUNICORN_TIMEOUT=$GUNICORN_TIMEOUT
GUNICORN_KEEPALIVE=$GUNICORN_KEEPALIVE
DATABROWSER_CACHE_SCHEDULER_ENABLED=$DATABROWSER_CACHE_SCHEDULER_ENABLED
DATABROWSER_CACHE_REFRESH_WEEKDAY=$DATABROWSER_CACHE_REFRESH_WEEKDAY
DATABROWSER_CACHE_REFRESH_TIME=$DATABROWSER_CACHE_REFRESH_TIME
DATABROWSER_CACHE_REFRESH_ON_START=$DATABROWSER_CACHE_REFRESH_ON_START
EOF
    echo "Wrote Compose environment file: $compose_env_file"
}

compose_with_env_exec() {
    if [ "$mode" = "production" ] && [ -f "$compose_env_file" ]; then
        compose_exec --env-file "$compose_env_file" "$@"
    else
        compose_exec "$@"
    fi
}

service_container_id() {
    compose_with_env_exec -f "$compose_file" ps -q "$1" | head -n 1
}

compose_has_service() {
    local service="$1"
    compose_with_env_exec -f "$compose_file" config --services | grep -Fxq "$service"
}

wait_for_running() {
    local service="$1"
    local container_id=""
    local attempts=60
    local running=""

    while [ "$attempts" -gt 0 ]; do
        container_id="$(service_container_id "$service")"
        if [ -n "$container_id" ]; then
            running="$(engine_exec inspect -f '{{.State.Running}}' "$container_id" 2>/dev/null || true)"
            if [ "$running" = "true" ]; then
                return 0
            fi
        fi
        attempts=$((attempts - 1))
        sleep 2
    done

    echo "Service '$service' is not running."
    if [ -n "$container_id" ]; then
        engine_exec logs "$container_id" || true
    fi
    exit 1
}

wait_for_healthy() {
    local service="$1"
    local container_id=""
    local attempts=90
    local health=""

    while [ "$attempts" -gt 0 ]; do
        container_id="$(service_container_id "$service")"
        if [ -n "$container_id" ]; then
            health="$(engine_exec inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}' "$container_id" 2>/dev/null || true)"
            if [ "$health" = "healthy" ] || [ "$health" = "running" ]; then
                return 0
            fi
        fi
        attempts=$((attempts - 1))
        sleep 2
    done

    echo "Service '$service' did not become healthy."
    if [ -n "$container_id" ]; then
        engine_exec logs "$container_id" || true
    fi
    exit 1
}

import_pathocore_api_sql() {
    local sql_path="$1"
    local db_user db_password db_name

    if ! compose_has_service "db"; then
        echo "Cannot import --pathocore_api_sql because compose file '$compose_file' has no 'db' service."
        echo "Use this option with the isolated test stack, or import the dump manually into the external production database."
        exit 1
    fi

    db_user="$(config_value_or_default DB_USER django)"
    db_password="$(config_value_or_default DB_PASSWORD djangopass)"
    db_name="$(config_value_or_default DB_NAME pathocore_api)"

    echo "Importing PathoCore API SQL into service db database '$db_name'"
    if [[ "$sql_path" == *.gz ]]; then
        gzip -dc "$sql_path" | compose_with_env_exec -f "$compose_file" exec -T db \
          mysql -u"$db_user" -p"$db_password" "$db_name"
    else
        compose_with_env_exec -f "$compose_file" exec -T db \
          mysql -u"$db_user" -p"$db_password" "$db_name" < "$sql_path"
    fi
}

ensure_seed_migration_state() {
    local db_user db_password db_name

    if ! compose_has_service "db"; then
        return 0
    fi

    db_user="$(config_value_or_default DB_USER django)"
    db_password="$(config_value_or_default DB_PASSWORD djangopass)"
    db_name="$(config_value_or_default DB_NAME pathocore_api)"

    echo "Ensuring PathoCore API seed migration state"
    compose_with_env_exec -f "$compose_file" exec -T db \
      mysql -u"$db_user" -p"$db_password" "$db_name" -e "
        INSERT IGNORE INTO django_migrations (app, name, applied)
        VALUES
            ('core', '0009_alter_schema_user_name_nullable', NOW()),
            ('core', '0010_remove_unused_metadata_models', NOW()),
            ('core', '0011_access_request', NOW()),
            ('core', '0012_access_request_revoked_status', NOW());
    "
}

prepare_host_bind_mount_permissions() {
    if [ "$mode" != "production" ]; then
        return 0
    fi

    mkdir -p "$PATHOCORE_HOST_LOG_DIR"
    chmod 0775 "$PATHOCORE_HOST_LOG_DIR" || true
}

copy_runtime_install_conf() {
    local container_id
    container_id="$(service_container_id "$APP_SERVICE")"
    if [ -z "$container_id" ]; then
        echo "Unable to resolve app container for copying runtime install config."
        exit 1
    fi
    echo "Copying runtime install config into the running container."
    engine_exec cp "$host_install_conf_path" "${container_id}:${runtime_install_conf_container}"
}

prepare_app_mount_permissions() {
    if [ "$mode" != "production" ]; then
        return 0
    fi

    compose_with_env_exec -f "$compose_file" exec -T --user 0 "$APP_SERVICE" bash -lc "
        set -e
        mkdir -p '$APP_INSTALL_PATH/logs' '$APP_INSTALL_PATH/static' '$APP_INSTALL_PATH/documents'
        chmod -R u+rwX,g+rwX '$APP_INSTALL_PATH/logs' '$APP_INSTALL_PATH/static' '$APP_INSTALL_PATH/documents'
    " || true
}

if [ "$action" = "fix-permissions" ]; then
    if [ "$mode" != "production" ]; then
        echo "fix-permissions is only needed for production bind mounts. Nothing to repair in test mode."
        exit 0
    fi
    app_container_id=""
    write_compose_env_file
    prepare_host_bind_mount_permissions
    app_container_id="$(service_container_id "$APP_SERVICE" 2>/dev/null || true)"
    if [ -n "$app_container_id" ] \
        && [ "$(engine_exec inspect -f '{{.State.Running}}' "$app_container_id" 2>/dev/null || true)" = "true" ]; then
        prepare_app_mount_permissions
    else
        echo "App container is not running; repaired host bind mount permissions only."
    fi
    echo "PathoCore API production permissions repaired."
    exit 0
fi

write_compose_env_file
prepare_host_bind_mount_permissions

echo "Building PathoCore API image with compose file: $compose_file"
compose_with_env_exec -f "$compose_file" build \
    --build-arg GIT_REVISION="$git_revision" \
    --build-arg INSTALL_CONF="$build_install_conf_container"

echo "Starting containers"
compose_with_env_exec -f "$compose_file" up -d

if compose_with_env_exec -f "$compose_file" config --services | grep -Fxq "db"; then
    echo "Waiting for database container to become healthy"
    wait_for_healthy "db"
fi

echo "Waiting for application container to be running"
wait_for_running "$APP_SERVICE"
copy_runtime_install_conf

echo "Resetting installation marker"
compose_with_env_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc "rm -f '$APP_READY_FILE'"

APP_INSTALL_MODE="$action"
if [ "$APP_INSTALL_MODE" = "install" ]; then
    detected_mode="$(compose_with_env_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc \
      "if [ -f '$APP_INSTALL_PATH/manage.py' ]; then echo upgrade; else echo install; fi")"
    APP_INSTALL_MODE="$detected_mode"
fi

if [ "$APP_INSTALL_MODE" = "upgrade" ]; then
    echo "Running install.sh --upgrade app inside the container"
    compose_with_env_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc \
      "cd '$APP_REPO_PATH' && bash install.sh --upgrade app --docker --git_revision '$git_revision' --conf '$runtime_install_conf_container' </dev/null"
else
    echo "Running install.sh --install app inside the container"
    compose_with_env_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc \
      "cd '$APP_REPO_PATH' && bash install.sh --install app --docker --git_revision '$git_revision' --conf '$runtime_install_conf_container'"
fi

echo "Running database migrations"
compose_with_env_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc \
  "cd '$APP_INSTALL_PATH' && source virtualenv/bin/activate && python manage.py migrate --noinput"

if [ -n "$pathocore_api_sql" ]; then
    import_pathocore_api_sql "$pathocore_api_sql"
    ensure_seed_migration_state
else
    echo "Skipping PathoCore API SQL import"
fi

if [ "$load_tables" = true ]; then
    echo "Loading initial tables"
    compose_with_env_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc \
      "cd '$APP_INSTALL_PATH' && source virtualenv/bin/activate && python manage.py loaddata conf/first_install_tables.json"
fi

if [ "$(read_install_conf_value PATHOCORE_CREATE_DEFAULT_SUPERUSER "$host_install_conf_path")" = "true" ]; then
    echo "Ensuring default Django superuser exists"
    compose_with_env_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc \
      "cd '$APP_INSTALL_PATH' && source virtualenv/bin/activate && python manage.py ensure_default_superuser"
fi

prepare_app_mount_permissions

echo "Marking installation as ready"
compose_with_env_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc "touch '$APP_READY_FILE'"

echo
echo "PathoCore API container installation finished."
echo "Running services and published ports:"
compose_with_env_exec -f "$compose_file" ps
echo "App URL: http://${PATHOCORE_API_BIND_HOST}:${PATHOCORE_API_PORT}/swagger/"
echo "Useful commands:"
echo "  ${COMPOSE_CMD[*]} --env-file .env.prod.file -f $compose_file logs -f app"
echo "  ${COMPOSE_CMD[*]} --env-file .env.prod.file -f $compose_file exec app bash"
