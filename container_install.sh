#!/usr/bin/env bash
set -euo pipefail

usage() {
cat << EOF
This script orchestrates PathoCore API installation in containers.

Usage:
  $0 [--test] [--git_revision <branch|tag|sha|current>] [--compose_file <path>] [--install_conf <path>] [--engine docker|podman] [--tables]

Options:
  --test           Use docker-compose.test.yml and conf/docker_test_settings.txt
  --git_revision   Git revision passed to image build/install. Use 'current' to keep current checked-out branch
  --compose_file   Override compose file path
  --install_conf   Override install settings file consumed inside the container
  --engine         docker (default) or podman
  --tables         Load conf/first_install_tables.json after migrate
  --help           Show this help

Examples:
  bash $0 --test --git_revision current
  bash $0 --compose_file docker-compose.prod.yml --install_conf conf/docker_production_settings.txt --git_revision develop
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
        --tables) set -- "$@" -l ;;
        --help) set -- "$@" -h ;;
        *) set -- "$@" "$arg" ;;
    esac
done

mode="production"
git_revision="develop"
compose_file=""
install_conf=""
engine="docker"
load_tables=false

while getopts ":tg:c:s:e:lh" opt; do
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
        l) load_tables=true ;;
        h)
            usage
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

if [ "$mode" = "test" ]; then
    compose_file="${compose_file:-docker-compose.test.yml}"
    install_conf="${install_conf:-conf/docker_test_settings.txt}"
else
    compose_file="${compose_file:-docker-compose.prod.yml}"
    install_conf="${install_conf:-conf/docker_production_settings.txt}"
fi

if [ ! -f "$compose_file" ]; then
    echo "Compose file not found: $compose_file"
    exit 1
fi

if [ ! -f "$install_conf" ]; then
    echo "Install settings file not found: $install_conf"
    exit 1
fi

repo_root="$(pwd)"
temp_install_conf=""

cleanup() {
    if [ -n "$temp_install_conf" ] && [ -f "$temp_install_conf" ]; then
        rm -f "$temp_install_conf"
    fi
}
trap cleanup EXIT

if [[ "$install_conf" = /* ]] && [[ "$install_conf" != "$repo_root/"* ]]; then
    temp_install_conf="$repo_root/.tmp_docker_install_conf_$$.txt"
    cp "$install_conf" "$temp_install_conf"
    install_conf="$temp_install_conf"
fi

if [[ "$install_conf" = "$repo_root/"* ]]; then
    install_conf_container="${install_conf#$repo_root/}"
else
    install_conf_container="$install_conf"
fi

# Export install settings so Docker Compose sees the same Keycloak runtime config
# that install.sh writes into the installed project's .env file.
set -a
. "$install_conf"
set +a

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

service_container_id() {
    compose_exec -f "$compose_file" ps -q "$1" | head -n 1
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

APP_REPO_PATH="${APP_REPO_PATH:-/srv/pathocore-api}"
APP_INSTALL_PATH="${APP_INSTALL_PATH:-/opt/pathocore-api}"
APP_READY_FILE="${APP_READY_FILE:-/opt/pathocore-api/.container_install_ready}"
APP_SERVICE="${APP_SERVICE:-app}"

echo "Building PathoCore API image with compose file: $compose_file"
INSTALL_CONF="$install_conf_container" GIT_REVISION="$git_revision" \
compose_exec -f "$compose_file" build \
    --build-arg GIT_REVISION="$git_revision" \
    --build-arg INSTALL_CONF="$install_conf_container"

echo "Starting containers"
INSTALL_CONF="$install_conf_container" GIT_REVISION="$git_revision" \
compose_exec -f "$compose_file" up -d

if compose_exec -f "$compose_file" config --services | grep -Fxq "db"; then
    echo "Waiting for database container to become healthy"
    wait_for_healthy "db"
fi

echo "Waiting for application container to be running"
wait_for_running "$APP_SERVICE"

echo "Resetting installation marker"
compose_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc "rm -f '$APP_READY_FILE'"

APP_INSTALL_MODE="$(compose_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc \
  "if [ -f '$APP_INSTALL_PATH/manage.py' ]; then echo upgrade; else echo install; fi")"

if [ "$APP_INSTALL_MODE" = "upgrade" ]; then
    echo "Existing Django project detected in $APP_INSTALL_PATH; running install.sh --upgrade app"
    compose_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc \
      "cd '$APP_REPO_PATH' && bash install.sh --upgrade app --docker --git_revision '$git_revision' --conf '$install_conf_container' </dev/null"
else
    echo "Running install.sh --install app inside the container"
    compose_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc \
      "cd '$APP_REPO_PATH' && bash install.sh --install app --docker --git_revision '$git_revision' --conf '$install_conf_container'"
fi

echo "Running database migrations"
compose_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc \
  "cd '$APP_INSTALL_PATH' && source virtualenv/bin/activate && python manage.py migrate"

if [ "$load_tables" = true ]; then
    echo "Loading initial tables"
    compose_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc \
      "cd '$APP_INSTALL_PATH' && source virtualenv/bin/activate && python manage.py loaddata conf/first_install_tables.json"
fi

echo "Marking installation as ready"
compose_exec -f "$compose_file" exec -T "$APP_SERVICE" bash -lc "touch '$APP_READY_FILE'"

echo
echo "PathoCore API container installation finished."
echo "App URL: http://localhost:8000/swagger/"
echo "Useful commands:"
echo "  ${COMPOSE_CMD[*]} -f $compose_file logs -f app"
echo "  ${COMPOSE_CMD[*]} -f $compose_file exec app bash"
