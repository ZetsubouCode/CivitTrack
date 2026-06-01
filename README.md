# CivitTrack

Standalone local Flask dashboard for tracking CivitAI creator model statistics over time.

CivitTrack saves API snapshots to SQLite, compares them over time, and answers the practical question: which model or version gained downloads, reactions, favorites, comments, and ratings since the last check?

It does not download models or preview images, scrape HTML, or expose the API key to the browser.

## Easy Install For Windows

1. Install [Python 3.10 or newer](https://www.python.org/downloads/) if Python is not already installed. During Python setup, enable the option to add Python to `PATH`.
2. After cloning or downloading this repository for the first time, double-click `INSTALL_CIVITTRACK.bat`.
3. Wait while the installer creates the local `.venv` folder and installs the required packages.
4. Notepad opens the local `.env` file. Add your CivitAI API key and username:

```dotenv
CIVITAI_API_KEY=your-local-api-key
CIVITAI_USERNAME=your-civitai-username
```

5. Save the file and close Notepad.
6. Double-click `START_CIVITTRACK.bat`. The dashboard opens automatically in your browser at [http://127.0.0.1:8787](http://127.0.0.1:8787).

For later use, only double-click `START_CIVITTRACK.bat`. Keep the command window open while using CivitTrack. Press `Ctrl+C` in that window to stop the app.

Run `INSTALL_CIVITTRACK.bat` again when dependencies need to be installed or repaired. It keeps your existing `.env` settings.

The API key stays in the local `.env` file. It is never stored in SQLite and is never sent to the frontend.

## Manual Install

Requires Python 3.10 or newer.

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set:

```dotenv
CIVITAI_API_KEY=your-local-api-key
CIVITAI_USERNAME=your-civitai-username
```

The default model filter is `LORA`.

## Run The Dashboard

For the easy Windows launcher, double-click `START_CIVITTRACK.bat`.

To start the app manually:

```bat
python app.py
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787).

Click **Take Snapshot Now** to store the first snapshot. Take another snapshot later, then click **Compare Latest vs Previous**. The model table sorts growth by download delta by default, while the version table reveals which model version gained downloads.

The **Current Model Breakdown** table expands the latest account totals into individual models. Switch between **Downloads** and **Reactions** to see which models make up each total without changing the snapshot comparison view.

CSV export becomes available after selecting a comparison.

## CLI

The CLI supports local manual runs and future scheduled snapshots:

```bat
python cli.py snapshot
python cli.py compare-latest
python cli.py list-snapshots
```

Commands return exit code `0` on success and `1` on failure.

## Windows Task Scheduler

To capture a snapshot every 30 minutes, create a scheduled task with:

```text
Program:
path\to\CivSnapStics\.venv\Scripts\python.exe

Arguments:
path\to\CivSnapStics\cli.py snapshot

Start in:
path\to\CivSnapStics
```

## Configuration

Copy `.env.example` to `.env`. Available values:

```dotenv
CIVITAI_API_KEY=
CIVITAI_USERNAME=
CIVITAI_BASE_URL=https://civitai.com
CIVITAI_ANALYTICS_DB=storage/civittrack.sqlite
CIVITAI_TIMEOUT_SECONDS=20
CIVITAI_MODEL_TYPES=LORA
CIVITAI_MAX_PAGES=100
APP_HOST=127.0.0.1
APP_PORT=8787
SECRET_KEY=dev-only-change-me
```

The SQLite database is created automatically under `storage/`.
