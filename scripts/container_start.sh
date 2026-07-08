#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/pathocore-api}"
APP_REPO_PATH="${APP_REPO_PATH:-/srv/pathocore-api}"
APP_PORT="${APP_PORT:-8000}"
APP_READY_FILE="${APP_READY_FILE:-${APP_DIR}/.container_install_ready}"
APP_MODE="${APP_MODE:-prod}"
GUNICORN_THREADS="${GUNICORN_THREADS:-2}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"
GUNICORN_KEEPALIVE="${GUNICORN_KEEPALIVE:-5}"

echo "PathoCore API container started."
echo "Waiting for installation marker at: ${APP_READY_FILE}"

while [ ! -f "${APP_READY_FILE}" ]; do
    sleep 2
done

cd "${APP_DIR}"
source "${APP_DIR}/virtualenv/bin/activate"

if [ "${DATABROWSER_CACHE_SCHEDULER_ENABLED:-true}" = "true" ]; then
    "${APP_REPO_PATH}/scripts/databrowser_cache_scheduler.sh" &
fi

if [ "${APP_MODE}" = "dev" ]; then
    exec python "${APP_DIR}/manage.py" runserver 0.0.0.0:"${APP_PORT}"
fi

if [ -n "${WEB_CONCURRENCY:-}" ]; then
    GUNICORN_WORKERS="${WEB_CONCURRENCY}"
else
    cpu_count="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || echo 1)"
    if [ "${cpu_count}" -le 2 ]; then
        GUNICORN_WORKERS=2
    else
        GUNICORN_WORKERS=4
    fi
fi

exec gunicorn pathocore_api.wsgi:application \
    --bind 0.0.0.0:"${APP_PORT}" \
    --workers "${GUNICORN_WORKERS}" \
    --threads "${GUNICORN_THREADS}" \
    --timeout "${GUNICORN_TIMEOUT}" \
    --keep-alive "${GUNICORN_KEEPALIVE}" \
    --access-logfile - \
    --error-logfile - \
    --capture-output \
    --log-level info
