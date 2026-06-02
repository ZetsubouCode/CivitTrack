#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"

VENV_PYTHON="$PWD/.venv/bin/python"
READY_MARKER="$PWD/.venv/.civittrack-ready"

fail() {
    printf "\nInstallation did not finish. %s\n" "$1" >&2
    exit 1
}

find_python() {
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 &&
            "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'
        then
            printf "%s\n" "$candidate"
            return 0
        fi
    done
    return 1
}

printf "\n==========================================\n"
printf "  Install CivitTrack\n"
printf "==========================================\n\n"

[ -f "requirements.txt" ] ||
    fail "requirements.txt was not found. Keep INSTALL_CIVITTRACK.sh in the CivitTrack project folder."
[ -f ".env.example" ] ||
    fail ".env.example was not found. Keep INSTALL_CIVITTRACK.sh in the CivitTrack project folder."

if [ -f ".venv/Scripts/python.exe" ] && [ ! -x "$VENV_PYTHON" ]; then
    fail "The existing .venv folder was created for Windows. Remove the .venv folder, then run this installer again on Linux."
fi

if [ ! -x "$VENV_PYTHON" ]; then
    printf "Creating the local Python environment...\n"
    BOOTSTRAP_PYTHON="$(find_python)" ||
        fail "Python 3.10 or newer was not found. Install Python and the python3-venv package, then run this installer again."
    "$BOOTSTRAP_PYTHON" -m venv ".venv" ||
        fail "Python could not create the .venv folder. Install the python3-venv package, then run this installer again."
fi

"$VENV_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' ||
    fail "The local .venv uses Python older than 3.10. Remove the .venv folder, install a current Python release, then run this installer again."

printf "Installing or updating CivitTrack requirements...\n"
"$VENV_PYTHON" -m pip install --disable-pip-version-check -r requirements.txt ||
    fail "Requirements could not be installed. Check your internet connection, then run this installer again."
printf "CivitTrack requirements installed.\n" > "$READY_MARKER"

if [ ! -f ".env" ]; then
    cp ".env.example" ".env"
    printf "\nCreated the local .env configuration file.\n"
    printf "Edit .env and add your CIVITAI_API_KEY and CIVITAI_USERNAME.\n"
else
    printf "Keeping the existing local .env configuration file.\n"
fi

printf "\nInstallation complete.\n"
printf "Run sh START_CIVITTRACK.sh to open the dashboard.\n"
