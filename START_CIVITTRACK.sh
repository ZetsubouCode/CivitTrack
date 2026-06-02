#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

VENV_PYTHON="$PWD/.venv/bin/python"
APP_URL="http://127.0.0.1:8787"

fail() {
    printf "\nCivitTrack could not start. %s\n" "$1" >&2
    exit 1
}

printf "\n==========================================\n"
printf "  CivitTrack - local creator analytics\n"
printf "==========================================\n\n"

[ -x "$VENV_PYTHON" ] ||
    fail "CivitTrack is not installed yet. Run sh INSTALL_CIVITTRACK.sh first."
[ -f ".env" ] ||
    fail "The local .env configuration file is missing. Run sh INSTALL_CIVITTRACK.sh to create it."
"$VENV_PYTHON" -c 'import flask, requests, dotenv' >/dev/null 2>&1 ||
    fail "Required Python packages are missing. Run sh INSTALL_CIVITTRACK.sh to repair the installation."

APP_URL="$("$VENV_PYTHON" -c "from services.config import get_config; c=get_config(); print(f'http://{c.app_host}:{c.app_port}')")" ||
    fail "The application URL could not be loaded from .env."

if [ "${1:-}" = "--check" ]; then
    printf "Starter check passed for %s.\n" "$APP_URL"
    exit 0
fi

printf "Starting CivitTrack at %s\n" "$APP_URL"
printf "Keep this terminal open while using the dashboard.\n"
printf "Press Ctrl+C in this terminal to stop CivitTrack.\n\n"

APP_URL="$APP_URL" "$VENV_PYTHON" -c \
    'import os, time, webbrowser; time.sleep(2); webbrowser.open(os.environ["APP_URL"])' \
    >/dev/null 2>&1 &

exec "$VENV_PYTHON" app.py
