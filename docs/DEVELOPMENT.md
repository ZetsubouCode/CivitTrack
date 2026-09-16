# Development Guide

## Local setup

CivitTrack intentionally has a small dependency surface:

```text
Flask
requests
python-dotenv
```

Use the repository installers for normal local setup, or create `.venv`, install `requirements.txt`, and copy `.env.example` to `.env`.

Secrets belong in `.env`, never in committed files.

## Before changing code

1. Read the relevant service and its current caller before editing.
2. Check whether a similar CivitAI request helper already exists in `CivitaiClient`.
3. Check whether the same normalized data is reused by multiple views.
4. Preserve current database compatibility unless the feature truly needs persistent state.
5. Avoid adding dependencies for small parsing, sorting, or formatting work.

## Implementation boundaries

### Browser/UI

Use `templates/dashboard.html` for structure and `static/app.js` for behavior.

Good browser responsibilities:

- local filters/search/sort over data already returned by the server
- rendering badges/rows/cards
- selection state
- explicit action submission

Bad browser responsibilities:

- calling CivitAI directly
- storing API secrets
- reverse-engineering tRPC payloads
- duplicating server relationship logic

### Flask routes

Keep routes small:

```text
parse request
-> validate request shape
-> call service
-> jsonify result
```

Do not put SQL or large remote-fetch workflows directly in `app.py`.

### Services

Services own application rules and data normalization. CivitAI URL/protocol quirks belong in `civitai_client.py`; SQLite persistence belongs through `db.py` helpers/transactions.

## API response conventions

Successful JSON actions should expose `ok: true` where the existing endpoint family does so.

Expected user/config/remote errors should become useful JSON messages, not raw tracebacks.

For batch operations, prefer structured counts and per-item status instead of failing the complete request because one item is invalid or unavailable, when partial completion is safe.

## User-feature checklist

Changes to the Users view deserve extra care because direct lookup, leaderboard review, comment reaction review, batch blocking, and protected-user state share components.

Before changing user-row behavior verify:

- Is this field directional? (`following` vs future `follows_you`)
- Does this sort apply to direct lookup only, or would it reorder leaderboard position?
- Does selection still disable already-blocked/protected users?
- Does an account-state failure still allow profile lookup?
- Are ID-only action parsers still strict?
- Does the row still contain canonical `user_id` for actions?

## Database changes

Only add a table/column when state must survive a process restart and cannot be cheaply reconstructed.

When schema changes are necessary:

1. Add the new schema to `SCHEMA`.
2. Add safe migration logic in `init_db()` for existing databases where required.
3. Keep initialization idempotent.
4. Do not store API keys/tokens in SQLite.
5. Confirm backup/restore remains compatible.

## Manual smoke test

There is currently no committed automated test suite, so every functional change should at least run this focused manual pass:

1. Start the Flask app with an existing local database.
2. Load every navigation view and check the browser console for errors.
3. Run the changed workflow with a normal successful case.
4. Run one empty/invalid input case and confirm a readable error.
5. If a CivitAI endpoint is involved, confirm a remote failure does not corrupt local state.
6. If SQLite changed, restart the app and confirm `init_db()` succeeds against the existing DB.
7. If a batch action changed, test mixed eligible/ineligible rows and verify counts/selections.
8. If the Users table changed, test direct lookup, leaderboard loading, protected users, and comment-reaction review separately.

## Useful focused checks

### User Resolver

- one valid ID
- multiple IDs
- unresolved ID
- relationship endpoint unavailable
- follow/unfollow action followed by rerender
- block/unblock action followed by rerender
- protected user cannot be batch-selected
- leaderboard still ordered by `leaderboard_position`

When username lookup is added, also test:

- exact username
- `@username`
- mixed ID + username
- duplicate ID and username pointing to the same account
- unknown username mixed with valid input

The resolver route must also retain compatibility with the legacy `{ "ids": ... }` request body while the browser uses `{ "values": ... }`.

When reverse-follow state is added, also test:

- following only
- follows-you only
- mutual
- neither
- relationship lookup unavailable
- priority sort on direct lookup and comment review
- no priority reorder for leaderboard rows

For an unavailable or incomplete `user.getList` follower response, verify every affected row uses `follows_you: null` and the response includes a warning; do not accept false negatives from partial pagination.

## Commit scope

Prefer small commits with one purpose, for example:

```text
feat: support username user lookup
feat: surface reverse follow relationship
fix: preserve leaderboard ordering in user table
docs: document user workflow contracts
```

Do not mix unrelated UI restyling, schema changes, and remote-client refactors unless they are required by the same feature.

## Documentation maintenance

Update docs when a change affects:

- architectural boundaries
- CivitAI endpoint semantics
- persistent schema
- relationship-field meaning
- a workflow's safety/selection rules

Screenshots are optional visual references. Behavioral documentation should be text-first and tied to the current code.
