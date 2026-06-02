# CivitTrack

Standalone local Flask dashboard for tracking CivitAI creator model statistics over time.

CivitTrack saves API snapshots to SQLite, compares them over time, and answers the practical question: which model or version gained downloads, reactions, collection adds, and comments since the last check? The tracked analytics set stays focused on downloads, reactions, collections, comments, followers when available, model counts, and version downloads.

It does not download models or preview images, scrape HTML, or expose the API key to the browser.

## Easy Install

### Windows

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

### Linux

1. Install Python 3.10 or newer, including your distribution's `python3-venv` package when it is packaged separately.
2. After cloning or downloading this repository for the first time, run:

```sh
sh INSTALL_CIVITTRACK.sh
```

3. Edit the generated `.env` file and add your CivitAI API key and username.
4. Start the dashboard:

```sh
sh START_CIVITTRACK.sh
```

The dashboard opens in your default browser when the Linux desktop environment supports it. Keep the terminal open while using CivitTrack. Press `Ctrl+C` in that terminal to stop the app.

Run `sh INSTALL_CIVITTRACK.sh` again when dependencies need to be installed or repaired. It keeps your existing `.env` settings.

The API key stays in the local `.env` file. It is never stored in SQLite and is never sent to the frontend.

Python virtual environments are OS-specific. If you reuse the same working folder after switching between Windows and Linux, remove `.venv` and run the installer for the current OS again. Your `.env` settings and SQLite data are kept outside `.venv`.

## Manual Install

Requires Python 3.10 or newer.

On Windows:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

On Linux:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set:

```dotenv
CIVITAI_API_KEY=your-local-api-key
CIVITAI_USERNAME=your-civitai-username
```

The default model filter is `LORA`.

## Run The Dashboard

For the easy Windows launcher, double-click `START_CIVITTRACK.bat`. On Linux, run `sh START_CIVITTRACK.sh`.

To start the app manually:

```sh
python app.py
```

Open [http://127.0.0.1:8787](http://127.0.0.1:8787).

## Dashboard Menu Guide

Use the floating navigation tabs on the left side of the dashboard to switch between six focused sections. Dashboard dates use `DD/MM/YYYY`; snapshot and log timestamps keep the local `HH:mm` time after the date. The screenshots below contain example local data for illustration.

### Overview

**Overview** is the main workspace. Click **Take Snapshot** to save the current CivitAI statistics locally. Choose a note type and optionally add local context such as a preview-image change or newly published version. If the previous snapshot is less than five minutes old, the dashboard warns before continuing.

After a successful capture, CivitTrack automatically compares it with the previous snapshot when available. Click **Compare Latest** to repeat that comparison, or use the snapshot selectors and **1 Day**, **7 Days**, and **30 Days** shortcuts for a different range. Period shortcuts use the nearest available historical snapshot on or before the target period. The summary cards show the selected snapshot totals and, after a comparison, their changes. CSV export becomes available after selecting a comparison.

![Overview menu with snapshot controls and account totals](docs/images/overview.png)

After a comparison, **Top Movers** highlights the strongest download, collection, and reaction gains plus the top newly detected model by downloads. **Model Growth** lists the affected models and defaults to newest models first. Use its search, metric filters, unchanged-model checkbox, and sort controls to narrow the results. The collapsible **Version Growth** table shows how much each version contributed to its model's download change.

![Overview model growth comparison](docs/images/overview-model-growth.png)

### Models

**Models** shows the current model portfolio from the latest snapshot. Switch between **Downloads**, **Reactions**, and **Collections** to rank models by a total. Use **Top first**, **Newest**, or **Oldest** to change the order, and use search to find a model by name. The **Share** column shows how much each model contributes to the selected account total. The displayed **Published** date uses the newest available model-version publication or creation date returned by CivitAI.

![Models menu with the latest model portfolio](docs/images/models.png)

Click a model row to open its **Stored Timeline**. The drawer shows its remote CivitAI cover image when available, a link to its CivitAI page, and the locally stored statistics for each snapshot. CivitTrack does not download the cover image into local storage.

![Stored timeline drawer for a model](docs/images/models-stored-timeline.png)

### Buzz

**Buzz** is an optional experimental tracker for Blue, Yellow, and Green Buzz activity. Enable it from **Settings**, select the account types to track, and click **Run Buzz Check** or run `python cli.py buzz-check`. The page shows endpoint availability, recent balances, and how many new transactions were found.

![Buzz Tracker menu with balances and endpoint status](docs/images/buzz.png)

The **Buzz Activity** table can be filtered by account, event type, and direction. Search by source or description to investigate a transaction. CivitTrack links a transaction to a model or image only when the CivitAI response contains enough information; unknown sources are normal. Normal model snapshot tracking continues to work if Buzz tracking is unavailable or the endpoint changes.

![Buzz activity filters and stored transactions](docs/images/buzz-activity.png)

### Snapshots

**Snapshots** lists the stored history used for comparisons. Each row shows when the capture ran, its note, source, quality status, and account totals. Use **Details** to inspect the saved quality report. A **Partial** snapshot still contains usable downloads and reactions, but extra CivitAI data such as collections, creator profile stats, or minor-model discovery may be incomplete. Older snapshots continue to work and show an unavailable quality report. Use **Delete** to remove an unwanted snapshot and its related records after confirmation. **Sync Logs** below the table show local snapshot activity and warnings.

![Snapshots menu with saved history and sync logs](docs/images/snapshots.png)

### Alerts

**Alerts** is a local inbox for actionable snapshot notifications. Alerts can report newly detected or missing models, new versions, milestones, growth changes, download-velocity spikes, generation-support changes, snapshot warnings, and failed snapshot attempts. The first successful snapshot establishes a baseline without producing an alert for every existing model. Open a linked model on CivitAI when a remote link is available, or use **Mark all read** to clear the unread badge.

![Alerts inbox with a newly detected model](docs/images/alerts.png)

### Settings

**Settings** starts with a first-run checklist and the local application configuration editor. Update the CivitAI username, API key, database path, model filters, and server settings here. Secret fields stay masked and are replaced only when you explicitly enter a new value.

![Settings menu with setup checklist and application settings](docs/images/settings.png)

Further down, **Settings** configures Buzz tracking and local alert preferences. Advanced alert thresholds tune when notifications appear. The same page explains snapshot sources and includes SQLite backup and restore controls. Restore validates the uploaded SQLite file before replacing the active database and keeps an automatic pre-restore safety copy under `storage/backups/`.

![Settings menu with alert preferences and data tools](docs/images/settings-alerts-backup.png)

## CLI

The CLI supports local manual runs and future scheduled snapshots:

```sh
python cli.py snapshot
python cli.py compare-latest
python cli.py list-snapshots
python cli.py buzz-check
```

Commands return exit code `0` on success and `1` on failure.

Snapshot history displays **Manual** for dashboard captures and **CLI** for `python cli.py snapshot`, including CLI runs started by Windows Task Scheduler or cron. **Scheduled** is reserved for future scheduler integrations.

## Windows Task Scheduler

To capture a snapshot every 30 minutes, create a scheduled task with:

```text
Program:
path\to\CivitTrack\.venv\Scripts\python.exe

Arguments:
path\to\CivitTrack\cli.py snapshot

Start in:
path\to\CivitTrack
```

## Linux Cron

To capture a snapshot every 30 minutes, add a cron entry using absolute paths:

```cron
*/30 * * * * cd /path/to/CivitTrack && .venv/bin/python cli.py snapshot
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
CIVITAI_INCLUDE_NSFW=true
CIVITAI_INCLUDE_MINOR=true
CIVITAI_MAX_PAGES=100
APP_HOST=127.0.0.1
APP_PORT=8787
SECRET_KEY=dev-only-change-me
```

The same values can be edited from the dashboard **Settings** tab. Secret fields stay masked and are only replaced when a new value is entered.

The SQLite database is created automatically under `storage/`.

`CIVITAI_BASE_URL` controls both API requests and clickable model-page links in the dashboard and CSV exports. The default is `https://civitai.com`.

`CIVITAI_INCLUDE_NSFW=true` is recommended for creator analytics. It tells the CivitAI models API to include restricted models whose showcase content is not visible at the default browsing level.

`CIVITAI_INCLUDE_MINOR=true` is also recommended. CivitAI's public REST listing excludes models flagged as minor even when restricted models are enabled. CivitTrack discovers those creator-owned model IDs through CivitAI's JSON site API, loads their REST details, and merges them into the snapshot without duplicates. If that discovery endpoint is temporarily unavailable, CivitTrack saves the standard REST snapshot and records a warning.

CivitTrack also reads each model's collection count from CivitAI's JSON site API because the public REST listing does not currently include that metric. Snapshots created before collection tracking was added show that value as unavailable.

CivitTrack fetches statistics and metadata only. It does not download showcase images or model files.
