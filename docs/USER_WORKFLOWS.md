# Users Workflows

The Users view combines several workflows that share normalized user rows but have different ordering and safety rules.

## Normalized user row

Current user-facing workflows commonly rely on fields such as:

```text
user_id
username
profile_url
image
deleted_at
status
source
following
blocked
excluded
```

Additional workflow-specific fields can be attached, for example leaderboard position/score or comment-reaction events.

Keep relationship field names directional and unambiguous:

- `following`: the configured account follows the target user.
- `blocked`: the configured account blocks the target user.
- `excluded`: local CivitTrack protection; the target should not be included in batch blocking.

There is currently no `follows_you` field.

## User Resolver

Current behavior accepts numeric CivitAI user IDs and resolves them through remote creator data with local stored username fallbacks.

The resolver also enriches rows with account relationship state when available.

### Safe extension: username input

The intended extension point for username lookup is the lookup workflow only.

Do not change `_parse_user_ids()` into a permissive ID-or-name parser because it is also used by ID-only actions such as batch blocking and protection-list changes.

Recommended flow:

```text
raw lookup tokens
  -> classify numeric ID vs username
  -> normalize username (`@name` -> `name`)
  -> resolve usernames to canonical user IDs
  -> deduplicate by canonical user ID
  -> reuse ID-based user enrichment
  -> return per-input resolution metadata + normalized users
```

Mixed input should be supported without making one invalid username fail unrelated valid IDs/usernames.

## Resolved Users table

The same result table is also reused by leaderboard loading. This matters for sorting.

For normal direct lookup, relationship-priority sorting can be applied in the browser after the server returns normalized rows.

For leaderboard results, preserve `leaderboard_position` ordering. Do not sort followers/protected/blocked users ahead of their actual leaderboard position.

If reverse-follow state is added later, a sensible direct-lookup priority is:

1. Mutual (`following && follows_you`)
2. Follows you (`follows_you`)
3. Other resolved users
4. Unresolved/not-found

That priority must be disabled for leaderboard results unless the user explicitly chooses another sort.

## Leaderboard review

The current Users view can load supported CivitAI leaderboards into the user result table.

Leaderboard rows can include:

- leaderboard identifier/title
- position
- score
- metrics/delta data when returned
- normal relationship fields
- local protected/exclusion state

Selection rules must continue to protect users that are already blocked or locally excluded.

## Protected users / block exclusions

`user_block_exclusion` is a local protection list. It exists to prevent selected users from being included in batch-block actions.

Important distinction:

- `blocked` is CivitAI account state.
- `excluded` is local CivitTrack safety state.

Do not treat `excluded` as if the user is blocked remotely.

Protection-list operations are ID-based and should remain strict.

## Comment reaction audit

The comment-reaction workflow:

1. Loads a root comment/thread.
2. Traverses replies within the configured bound.
3. Collects reaction events and reactor IDs.
4. Resolves reactor profile/relationship state.
5. Applies UI filters such as selected reaction types, author exclusion, and blocked-user hiding.
6. Renders `Users To Review`.

### Sorting `Users To Review`

Filtering should happen first. Priority sorting should apply only to the remaining visible matches.

When reverse-follow state becomes available, recommended stable priority is:

1. Mutual
2. Follows you
3. Other users

Within the same priority group, preserve the existing stable order unless the UI explicitly exposes another sort.

Blocked/protected state should remain a separate badge/safety concept instead of being mixed into follower priority.

## Relationship labels

Recommended labels once reverse-follow state exists:

| State | Meaning |
| --- | --- |
| `Following` | You follow this user |
| `Follows You` | This user follows you |
| `Mutual` | Both directions are true |
| `Blocked` | You block this user |
| `Protected` | Local CivitTrack exclusion from batch blocking |

Never infer `Follows You` from the current `following` field.

## Failure behavior

- Profile resolution can succeed even if relationship-state enrichment fails.
- Return warnings for unavailable optional relationship state.
- Do not disable the entire Users workflow because one profile cannot be resolved.
- Batch operations should clearly report counts and failed IDs.
