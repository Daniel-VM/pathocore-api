#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-${APP_INSTALL_PATH:-/opt/pathocore-api}}"
APP_READY_FILE="${APP_READY_FILE:-${APP_DIR}/.container_install_ready}"

echo "Databrowser cache scheduler waiting for installation marker: ${APP_READY_FILE}"

while [ ! -f "${APP_READY_FILE}" ]; do
    sleep 2
done

cd "${APP_DIR}"
source "${APP_DIR}/virtualenv/bin/activate"

python -u <<'PY'
import os
import subprocess
import time
from datetime import datetime, timedelta


def log(message):
    timestamp = datetime.now().isoformat(timespec="seconds")
    print(f"[databrowser-cache-scheduler] {timestamp} {message}", flush=True)


def parse_bool(value):
    return str(value).lower() in {"1", "true", "yes", "on"}


def next_run_at(now, weekday, hour, minute):
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    candidate = candidate + timedelta(days=(weekday - now.weekday()) % 7)
    if candidate <= now:
        candidate = candidate + timedelta(days=7)
    return candidate


weekday = int(os.environ.get("DATABROWSER_CACHE_REFRESH_WEEKDAY", "4"))
time_text = os.environ.get("DATABROWSER_CACHE_REFRESH_TIME", "12:00")
hour_text, minute_text = time_text.split(":", 1)
hour = int(hour_text)
minute = int(minute_text)

if not 0 <= weekday <= 6:
    raise SystemExit("DATABROWSER_CACHE_REFRESH_WEEKDAY must be between 0 and 6")
if not 0 <= hour <= 23 or not 0 <= minute <= 59:
    raise SystemExit("DATABROWSER_CACHE_REFRESH_TIME must use HH:MM in 24h format")


def refresh(reason):
    log(f"running refresh_databrowser_cache ({reason})")
    result = subprocess.run(["python", "manage.py", "refresh_databrowser_cache"])
    if result.returncode == 0:
        log("refresh_databrowser_cache finished")
    else:
        log(f"refresh_databrowser_cache failed with exit code {result.returncode}")


if parse_bool(os.environ.get("DATABROWSER_CACHE_REFRESH_ON_START", "false")):
    refresh("startup")

while True:
    now = datetime.now()
    target = next_run_at(now, weekday, hour, minute)
    delay = max(1, int((target - now).total_seconds()))
    log(f"next refresh scheduled at {target.isoformat(timespec='seconds')}")
    time.sleep(delay)
    refresh("scheduled")
PY
