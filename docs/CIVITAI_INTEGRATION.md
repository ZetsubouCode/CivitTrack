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
- fetch IDs that follow the configured account via paged `user.getList` queries
- fetch hidden/blocked preferences
- mutate follow/block relationship state
- fetch supported user leaderboards

### Important relationship semantics

`following` currently means:

> The configured CivitTrack/CivitAI account follows the target user.

It does **not** mean the target user follows the configured account.

Do not rename or display this value as `Follows You`.

Reverse-follow state is exposed separately as `follows_you`. A combined `Mutual` display state is derived only from `following && follows_you`.

### Verified reverse-follower procedure

CivitAI's current site tRPC router exposes `user.getList`. CivitTrack requests it with:

```text
{
  username: <configured CIVITAI_USERNAME>,
  type: "followers",
  limit: 200,
  page: <1-based page>
}
```

The procedure returns an object with `items`, `currentPage`, `pageSize`, `totalItems`, and `totalPages`. Each follower item includes a canonical numeric `id` plus profile fields such as `username`. The first page establishes the page count; remaining pages are fetched with bounded batched tRPC calls. CivitTrack refuses lists over 50 pages (10,000 users) rather than treating a truncated list as confirmed negative.

The upstream router currently marks `user.getList` as public, so a bearer token is not required for this read. CivitTrack still sends its configured API key when present through the standard client headers. A configured username is required because it identifies whose followers are being queried. Follow/block reads and all relationship mutations retain their existing API-key requirements.

If any follower page fails or has an unexpected shape, the complete reverse-follow set is treated as unavailable: normalized rows receive `follows_you: null` and the workflow returns a warning. It never converts a failed or partial follower read into `false`.

## Username resolution

The client has `fetch_user_profile(username)` for single lookups and `fetch_user_profiles(usernames)` for bounded batched `userProfile.get` lookups. A returned profile supplies the canonical numeric user ID.

The User Resolver accepts usernames as follows:

- keep numeric ID parsing used by block/exclusion actions strict;
- add a lookup-specific parser rather than weakening `_parse_user_ids()` globally;
- strip an optional leading `@` from username input;
- compare canonical usernames case-insensitively where appropriate;
- batch username profile requests in groups of 20;
- resolve usernames to canonical IDs before reusing existing ID-based relationship/profile enrichment;
- keep one bad username from failing unrelated valid entries in a mixed lookup batch;
- deduplicate final users by canonical user ID;
- fall back to case-insensitive local matches from images, articles, Buzz transactions, blocked-user preferences, and protected users when remote username resolution does not produce an ID.

## Relationship enrichment

User rows currently combine remote profile data with:

- `following`
- `follows_you`
- `blocked`
- local `excluded` / protected-user state

Relationship lookup failure should produce a warning while still allowing profile resolution where possible.

Directional meanings are fixed:

- `following`: the configured account follows the target user.
- `follows_you`: the target user follows the configured account (`true`/`false`), or `null` when the complete follower list is unavailable.

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
