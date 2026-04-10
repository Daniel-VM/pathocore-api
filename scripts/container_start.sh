#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/pathocore-api}"
APP_REPO_PATH="${APP_REPO_PATH:-/srv/pathocore-api}"
APP_PORT="${APP_PORT:-8000}"
APP_READY_FILE="${APP_READY_FILE:-${APP_DIR}/.container_install_ready}"
APP_MODE="${APP_MODE:-prod}"

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

# TEMPORTARy, just unfreezing the container logs since gunicorn is not capturing them properly 
exec gunicorn pathocore_api.wsgi:application \
    --bind 0.0.0.0:"${APP_PORT}" \
    --workers 2 \
    --threads 2 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    --capture-output \
    --log-level info
