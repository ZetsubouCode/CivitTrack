# CivitTrack Documentation

This directory contains developer-facing documentation for the current CivitTrack codebase. Screenshots under `docs/images/` are visual references only; they are not the source of truth for behavior.

## Start here

- [Architecture](ARCHITECTURE.md) — application layers, service responsibilities, storage, and where changes belong.
- [CivitAI integration](CIVITAI_INTEGRATION.md) — REST/tRPC usage, authentication, failure handling, and user relationship semantics.
- [Users workflow](USER_WORKFLOWS.md) — User Resolver, leaderboards, comment-reaction review, block protection, and extension points.
- [Development guide](DEVELOPMENT.md) — local workflow, implementation conventions, and smoke-test checklist.

## Source-of-truth order

When documentation and code disagree, use this order:

1. Current code on the active branch.
2. Database schema and API contracts implemented by the current code.
3. These docs.
4. README usage prose.
5. Screenshots.

Screenshots can become stale after UI changes and should never be used to infer backend behavior.

## Current stack

CivitTrack is intentionally small:

- Flask server (`app.py`)
- Service modules under `services/`
- SQLite storage managed by `services/db.py`
- Vanilla browser JavaScript in `static/app.js`
- Shared styling in `static/app.css`
- Jinja templates under `templates/`
- `requests` for CivitAI HTTP calls
- `python-dotenv` for local configuration

Runtime dependencies are deliberately minimal; avoid adding a new package when the standard library or an existing dependency is sufficient.

## Design goals

- Keep the CivitAI API key server-side.
- Prefer local persistence for analytics/history, not for secrets.
- Preserve useful partial results when an optional CivitAI endpoint fails.
- Keep destructive or account-changing actions explicit.
- Keep UI state understandable: the browser renders data returned by the server; CivitAI-specific request logic belongs in `services/civitai_client.py`.
- Treat CivitAI site/tRPC endpoints as change-prone integrations and isolate them behind client methods.
