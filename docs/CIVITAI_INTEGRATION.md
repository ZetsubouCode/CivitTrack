# CivitAI Integration

CivitTrack deliberately isolates remote CivitAI behavior in `services/civitai_client.py`. Higher-level services should consume client methods rather than rebuild URLs or decode tRPC payloads themselves.

## Transport layers

CivitTrack currently uses both public REST endpoints and CivitAI site/tRPC endpoints.

### REST

`CivitaiClient.get_json()` is the common REST GET helper. It applies:

- `Accept: application/json`
- local `User-Agent`
- bearer authorization when `CIVITAI_API_KEY` is configured
- configured timeout
- bounded retries for server errors
- normalized errors for auth, rate limiting, network failures, and invalid JSON

### tRPC

The client contains helpers for:

- `post_trpc()`
- `get_trpc_batch()`
- tRPC result/error decoding
- indexed payload decoding used by current CivitAI responses

Do not duplicate the decoder in feature services.

## Failure policy

Treat CivitAI site/tRPC integrations as change-prone.

- Core failure: return a clear `CivitaiError` when the requested operation cannot be completed.
- Optional enrichment failure: preserve already valid data and return a warning/partial status when the surrounding workflow supports it.
- Do not silently convert an unknown response into a successful empty result when that would change the meaning of an action.

## Authentication

The API key is read server-side from local configuration and must never be emitted to templates, JavaScript, logs, database rows, or API responses.

Some read endpoints work without an API key; account relationship and write operations may require authenticated access. Services should report unavailable relationship state separately from profile resolution when possible.

## User-related client capabilities

The current client already exposes the primitives used by `user_service.py`, including:

- resolve creator data by numeric user ID
- `fetch_user_profile(username)` via `userProfile.get`
- fetch IDs the configured account is following via `user.getFollowingUsers`
- fetch hidden/blocked preferences
- mutate follow/block relationship state
- fetch supported user leaderboards

### Important relationship semantics

`following` currently means:

> The configured CivitTrack/CivitAI account follows the target user.

It does **not** mean the target user follows the configured account.

Do not rename or display this value as `Follows You`.

If reverse-follow state is added later, expose it as a separate field such as `follows_you`. Only populate it from a verified CivitAI response whose direction is known. A combined `mutual` display state can then be derived from `following && follows_you`.

## Username resolution

The client already has `fetch_user_profile(username)`, which returns a profile object when CivitAI can resolve that username. The profile can supply the canonical numeric user ID.

When extending the User Resolver to accept usernames:

- keep numeric ID parsing used by block/exclusion actions strict;
- add a lookup-specific parser rather than weakening `_parse_user_ids()` globally;
- strip an optional leading `@` from username input;
- compare canonical usernames case-insensitively where appropriate;
- batch username profile requests when practical;
- resolve usernames to canonical IDs before reusing existing ID-based relationship/profile enrichment;
- keep one bad username from failing unrelated valid entries in a mixed lookup batch;
- deduplicate final users by canonical user ID.

## Relationship enrichment

User rows currently combine remote profile data with:

- `following`
- `blocked`
- local `excluded` / protected-user state

Relationship lookup failure should produce a warning while still allowing profile resolution where possible.

## Leaderboards

Leaderboard rows include authoritative position/score information. Preserve API leaderboard ordering by default. Do not apply generic user-table priority sorting to leaderboard results unless the user explicitly chooses a different sort.

## Adding a new CivitAI endpoint

1. Add one focused method to `CivitaiClient`.
2. Reuse existing request/tRPC helpers.
3. Normalize the smallest stable response shape needed by the service.
4. Handle auth/rate-limit/unexpected-response errors through `CivitaiError`.
5. Call the method from a domain service.
6. Keep the Flask route thin.
7. Add UI behavior only after the server contract is stable.
8. Document response-direction semantics for relationship-like fields; names such as `following`, `followers`, `blocked`, and `hidden` are easy to misinterpret.
