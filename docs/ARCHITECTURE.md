# Architecture

## Request flow

CivitTrack follows a simple server-rendered Flask architecture with client-side enhancements:

```text
Browser
  -> templates/dashboard.html + static/app.js
  -> Flask routes in app.py
  -> services/* business logic
  -> services/civitai_client.py for CivitAI HTTP/tRPC
  -> services/db.py for SQLite
```

Keep those boundaries intact. UI code should not know API keys or CivitAI authentication details. Flask routes should stay thin and delegate meaningful work to services.

## Main files

### `app.py`

Owns Flask routes and HTTP request/response handling.

Responsibilities:

- Validate request shape at the boundary.
- Call the appropriate service function.
- Translate expected `ValueError` / `CivitaiError` failures into JSON errors.
- Render the dashboard with safe public configuration such as the configured profile URL.

Do not put large CivitAI parsing or SQL workflows directly in routes.

### `services/civitai_client.py`

Single integration boundary for CivitAI HTTP calls.

Responsibilities include:

- REST requests.
- tRPC GET/POST calls.
- Batched tRPC calls.
- tRPC payload decoding.
- Retry/rate-limit/network error handling.
- CivitAI-specific response normalization.

If CivitAI changes an endpoint or payload, fix it here first instead of adding endpoint-specific workarounds in the browser.

### `services/db.py`

Owns SQLite schema initialization and connections.

Important table groups:

- Snapshot analytics: `snapshot`, `account_snapshot`, `model_snapshot`, `model_version_snapshot`, `snapshot_quality`.
- Alerts/logs/settings: `local_alert`, `sync_log`, `app_setting`.
- Buzz: `buzz_check`, `buzz_account_snapshot`, `buzz_transaction`.
- Images: `image_sync`, `model_image`, `hidden_image_preference`, `blocked_user_preference`.
- Articles: `article_sync`, `model_article`, `article_metric_snapshot`.
- Local action state: `image_reaction_state`, `comment_reaction_state`, `reaction_action_log`.
- User audit helpers: `comment_reaction_history`, `user_block_exclusion`.

Schema additions must be accompanied by an idempotent migration path in `init_db()` for existing installations when needed.

### Domain services

- `snapshot_service.py` — capture creator/model snapshots.
- `compare_service.py` — compare snapshots and build growth views.
- `quality_service.py` — describe completeness/quality of a snapshot.
- `alert_service.py` — local alert generation and inbox operations.
- `image_service.py` — image sync, filtering, detail, comments, and reactions.
- `image_cache_service.py` — bounded local public-thumbnail cache.
- `article_service.py` — article sync and metric history.
- `buzz_service.py` / `buzz_client.py` — optional Buzz tracking.
- `user_service.py` — user resolution, account relationship state, comment-reaction audit, leaderboards, batch blocking, and protected-user exclusions.
- `backup_service.py` — SQLite backup/restore.
- `settings_service.py` / `config.py` — local configuration.

## Frontend

### `templates/dashboard.html`

Contains the page structure for all left-navigation views. It should define semantic sections, forms, tables, and element IDs only; substantial behavior belongs in JavaScript.

### `static/app.js`

Owns browser state, API calls, filtering, sorting, rendering, and action handlers.

Prefer small shared helpers over duplicating render/action logic. Server-provided booleans such as `blocked`, `following`, and `excluded` should remain authoritative relationship state.

### `static/app.css`

Contains reusable visual states. Relationship/status indicators should use shared badge/row classes rather than one-off inline styles.

## Snapshot flow

```text
Take Snapshot
  -> app.py
  -> snapshot_service
  -> CivitaiClient fetches model/profile data
  -> normalize/enrich available metrics
  -> save snapshot rows in one local database
  -> quality_service records completeness/warnings
  -> compare/alerts can consume the saved snapshot
```

Optional remote failures should generally produce warnings/partial quality instead of destroying already collected core data.

## User workflow flow

```text
User input / leaderboard / comment audit
  -> app.py users routes
  -> user_service
  -> CivitaiClient for remote profile/relationship data
  -> local DB fallbacks/protection state where applicable
  -> normalized user rows
  -> app.js rendering and selection rules
```

The same normalized user row is reused by multiple UI workflows. When adding fields, keep the meaning stable across direct lookup, comment-reaction review, and leaderboard rows.

## Change map

| Change | Primary files | Usually unnecessary |
| --- | --- | --- |
| New CivitAI endpoint | `services/civitai_client.py`, relevant service | Direct browser fetch |
| New Users behavior | `services/user_service.py`, `app.py`, `static/app.js`, possibly `dashboard.html`/`app.css` | DB migration unless state must persist |
| New persisted metric | `services/db.py`, producer service, compare/render consumers | New dependency |
| New UI-only filter/sort | `static/app.js`, possibly `dashboard.html` | Backend change if data already exists |
| New configuration | `services/config.py`, `.env.example`, settings UI/service | Hard-coded constants in JS |

## Invariants

1. API keys and secrets never go to browser JavaScript.
2. `app.py` stays a routing layer, not a second service layer.
3. CivitAI endpoint quirks stay in `civitai_client.py`.
4. Existing local databases must continue to initialize successfully after schema changes.
5. A failure in an optional enrichment endpoint should not erase otherwise valid data.
6. Account-changing actions (follow, block, reactions, comments) must be explicit user actions.
7. Leaderboard position is authoritative ordering. UI convenience sorting must not silently reorder leaderboard results unless the UI clearly offers that sort.
