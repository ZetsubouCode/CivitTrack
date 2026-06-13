import json
import re
from html import unescape

from .civitai_client import CivitaiClient, CivitaiError
from .config import get_config
from .db import create_connection, dict_rows, transaction, utc_now


MAX_USER_LOOKUP_IDS = 100
MAX_COMMENT_REACTION_USERS = MAX_USER_LOOKUP_IDS
MAX_COMMENT_THREAD_COMMENTS = 500
COMMENT_REACTIONS = {"Like", "Dislike", "Laugh", "Cry", "Heart"}


def _safe_optional_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value, default=None) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return default
    text = str(value).strip()
    return text or default


def _parse_user_ids(value) -> list[int]:
    if isinstance(value, (list, tuple)):
        parts = value
    else:
        text = str(value or "")
        for separator in ",;\n\t":
            text = text.replace(separator, " ")
        parts = text.split(" ")
    ids = []
    seen = set()
    invalid = []
    for part in parts:
        if part is None or str(part).strip() == "":
            continue
        user_id = _safe_optional_int(str(part).strip())
        if user_id is None or user_id <= 0:
            invalid.append(str(part).strip())
            continue
        if user_id not in seen:
            ids.append(user_id)
            seen.add(user_id)
    if invalid:
        sample = ", ".join(invalid[:5])
        suffix = "..." if len(invalid) > 5 else ""
        raise ValueError(f"User IDs must be positive integers. Invalid value(s): {sample}{suffix}")
    if not ids:
        raise ValueError("Enter at least one CivitAI user ID.")
    if len(ids) > MAX_USER_LOOKUP_IDS:
        raise ValueError(f"Lookup is limited to {MAX_USER_LOOKUP_IDS} user IDs at a time.")
    return ids


def _local_user_matches(user_ids: list[int]) -> dict[int, dict]:
    if not user_ids:
        return {}
    placeholders = ", ".join("?" for _ in user_ids)
    local: dict[int, dict] = {}
    queries = (
        (
            "model_image",
            "SELECT creator_user_id AS user_id, username FROM model_image "
            f"WHERE creator_user_id IN ({placeholders}) AND username IS NOT NULL AND username != ''",
        ),
        (
            "model_article",
            "SELECT user_id, username FROM model_article "
            f"WHERE user_id IN ({placeholders}) AND username IS NOT NULL AND username != ''",
        ),
        (
            "buzz_transaction",
            "SELECT user_id, username FROM buzz_transaction "
            f"WHERE user_id IN ({placeholders}) AND username IS NOT NULL AND username != ''",
        ),
        (
            "blocked_user_preference",
            "SELECT user_id, username FROM blocked_user_preference "
            f"WHERE user_id IN ({placeholders}) AND username IS NOT NULL AND username != ''",
        ),
    )
    with create_connection() as connection:
        for source, sql in queries:
            for row in connection.execute(sql, tuple(user_ids)):
                user_id = _safe_optional_int(row["user_id"])
                username = _clean_text(row["username"])
                if user_id and username and user_id not in local:
                    local[user_id] = {
                        "user_id": user_id,
                        "username": username,
                        "source": source,
                    }
    return local


def _profile_url(username: str | None) -> str | None:
    if not username:
        return None
    return f"{get_config().base_url}/user/{username}"


def _lookup_account_state(client: CivitaiClient) -> tuple[set[int], set[int], list[str]]:
    following: set[int] = set()
    blocked: set[int] = set()
    warnings = []
    config = get_config()
    if not config.api_key:
        warnings.append("API key is missing, so follow/block state is unavailable.")
        return following, blocked, warnings
    try:
        following = set(client.fetch_following_user_ids())
    except CivitaiError as exc:
        warnings.append(f"Following state unavailable: {exc}")
    try:
        preferences = client.fetch_hidden_preferences()
        blocked = {
            user_id for user_id in (
                _safe_optional_int(item.get("id"))
                for item in preferences.get("blockedUsers") or []
                if isinstance(item, dict)
            )
            if user_id is not None and user_id > 0
        }
    except CivitaiError as exc:
        warnings.append(f"Blocked-user state unavailable: {exc}")
    return following, blocked, warnings


def _status_for_creator(username: str | None, deleted_at: str | None) -> str:
    if deleted_at:
        return "deleted"
    return "found" if username else "found_without_username"


def _resolve_rows(user_ids: list[int], remote: dict[int, dict], local: dict[int, dict], following: set[int], blocked: set[int], remote_error: str) -> list[dict]:
    rows = []
    for user_id in user_ids:
        creator = remote.get(user_id)
        if isinstance(creator, dict):
            username = _clean_text(creator.get("username"))
            deleted_at = _clean_text(creator.get("deletedAt"))
            rows.append({
                "user_id": user_id,
                "username": username,
                "profile_url": _profile_url(username),
                "image": _clean_text(creator.get("image")),
                "deleted_at": deleted_at,
                "status": _status_for_creator(username, deleted_at),
                "source": "civitai_trpc",
                "following": user_id in following,
                "blocked": user_id in blocked,
            })
            continue
        match = local.get(user_id)
        if match:
            rows.append({
                "user_id": user_id,
                "username": match["username"],
                "profile_url": _profile_url(match["username"]),
                "image": None,
                "deleted_at": None,
                "status": "local_only",
                "source": match["source"],
                "following": user_id in following,
                "blocked": user_id in blocked,
            })
            continue
        rows.append({
            "user_id": user_id,
            "username": None,
            "profile_url": None,
            "image": None,
            "deleted_at": None,
            "status": "not_found",
            "source": "civitai_trpc" if not remote_error else "unavailable",
            "error": remote_error,
            "following": user_id in following,
            "blocked": user_id in blocked,
        })
    return rows


def resolve_users_by_ids(value) -> dict:
    user_ids = _parse_user_ids(value)
    local = _local_user_matches(user_ids)
    client = CivitaiClient()
    following, blocked, state_warnings = _lookup_account_state(client)
    remote: dict[int, dict] = {}
    remote_error = ""
    try:
        remote = client.fetch_creators_by_ids(user_ids)
    except CivitaiError as exc:
        remote_error = str(exc)
    rows = _resolve_rows(user_ids, remote, local, following, blocked, remote_error)
    return {
        "ok": True,
        "ids": user_ids,
        "users": rows,
        "count": len(rows),
        "found_count": sum(1 for row in rows if row["username"]),
        "remote_error": remote_error,
        "warnings": state_warnings,
    }


def _plain_comment_text(value: str | None, limit: int = 180) -> str:
    text = re.sub(r"<br\s*/?>", "\n", str(value or ""), flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", unescape(text)).strip()
    if len(text) > limit:
        return text[:limit - 1].rstrip() + "..."
    return text


def _normalize_comment(comment: dict, parent_id: int | None, root_id: int) -> dict:
    user = comment.get("user") if isinstance(comment.get("user"), dict) else {}
    reactions = []
    for item in comment.get("reactions") or []:
        if not isinstance(item, dict):
            continue
        reaction_user = item.get("user") if isinstance(item.get("user"), dict) else {}
        user_id = _safe_optional_int(item.get("userId") or reaction_user.get("id"))
        reaction = _clean_text(item.get("reaction"))
        if user_id and reaction:
            reactions.append({
                "user_id": user_id,
                "reaction": reaction,
                "username": _clean_text(reaction_user.get("username")),
                "deleted_at": _clean_text(reaction_user.get("deletedAt")),
            })
    comment_id = _safe_optional_int(comment.get("id"))
    return {
        "comment_id": comment_id,
        "parent_comment_id": parent_id,
        "root_comment_id": root_id,
        "kind": "main" if comment_id == root_id else "reply",
        "thread_id": _safe_optional_int(comment.get("threadId")),
        "created_at": _clean_text(comment.get("createdAt")),
        "author_user_id": _safe_optional_int(user.get("id")),
        "author_username": _clean_text(user.get("username")),
        "content_preview": _plain_comment_text(comment.get("content")),
        "reaction_count": _safe_optional_int(comment.get("reactionCount")) or len(reactions),
        "reactions": reactions,
    }


def _fetch_comment_tree(client: CivitaiClient, root_comment_id: int) -> tuple[list[dict], list[str]]:
    legacy = True
    try:
        root = client.fetch_legacy_comment_by_id(root_comment_id)
    except CivitaiError:
        root = None
    if not root:
        legacy = False
        root = client.fetch_comment_by_id(root_comment_id)
    if not root:
        raise ValueError("CivitAI comment could not be found.")
    comments = [_normalize_comment(root, None, root_comment_id)]
    queue = [root_comment_id]
    seen = {root_comment_id}
    warnings = []
    while queue and len(comments) < MAX_COMMENT_THREAD_COMMENTS:
        parent_id = queue.pop(0)
        try:
            reply_count = (
                client.fetch_legacy_comment_reply_count(parent_id)
                if legacy else client.fetch_comment_reply_count(parent_id)
            )
            if reply_count < 1:
                continue
            replies = (
                client.fetch_legacy_comment_replies(parent_id)
                if legacy else client.fetch_comment_replies(parent_id, limit=100)
            )
        except CivitaiError as exc:
            warnings.append(f"Replies unavailable for comment {parent_id}: {exc}")
            continue
        for reply in replies:
            reply_id = _safe_optional_int(reply.get("id"))
            if not reply_id or reply_id in seen:
                continue
            seen.add(reply_id)
            comments.append(_normalize_comment(reply, parent_id, root_comment_id))
            queue.append(reply_id)
            if len(comments) >= MAX_COMMENT_THREAD_COMMENTS:
                warnings.append(f"Stopped at {MAX_COMMENT_THREAD_COMMENTS} comments to keep the scan bounded.")
                break
    return comments, warnings


def analyze_comment_reactions(comment_id) -> dict:
    parsed = _safe_optional_int(comment_id)
    if parsed is None or parsed <= 0:
        raise ValueError("comment_id must be a positive integer.")
    client = CivitaiClient()
    comments, warnings = _fetch_comment_tree(client, parsed)
    author_ids = {
        comment["author_user_id"] for comment in comments
        if comment.get("author_user_id")
    }
    reaction_events = []
    reactor_ids = []
    seen_reactors = set()
    reaction_usernames: dict[int, str] = {}
    for comment in comments:
        for reaction in comment["reactions"]:
            reaction_name = reaction["reaction"]
            user_id = reaction["user_id"]
            if reaction.get("username") and user_id not in reaction_usernames:
                reaction_usernames[user_id] = reaction["username"]
            event = {
                "user_id": user_id,
                "reaction": reaction_name,
                "comment_id": comment["comment_id"],
                "comment_kind": comment["kind"],
                "comment_author_user_id": comment["author_user_id"],
                "comment_author_username": comment["author_username"],
            }
            reaction_events.append(event)
            if user_id not in seen_reactors:
                reactor_ids.append(user_id)
                seen_reactors.add(user_id)
    if len(reactor_ids) > MAX_COMMENT_REACTION_USERS:
        warnings.append(
            f"Resolved the first {MAX_COMMENT_REACTION_USERS} reacting users; "
            "remaining reactor IDs are still shown without profile state."
        )
    resolved = resolve_users_by_ids(reactor_ids[:MAX_COMMENT_REACTION_USERS]) if reactor_ids else {
        "users": [], "warnings": [],
    }
    warnings.extend(resolved.get("warnings", []))
    user_map = {row["user_id"]: row for row in resolved.get("users", [])}
    candidates = []
    for user_id in reactor_ids:
        events = [event for event in reaction_events if event["user_id"] == user_id]
        reactions = sorted({event["reaction"] for event in events})
        user = user_map.get(user_id, {
            "user_id": user_id,
            "username": reaction_usernames.get(user_id),
            "profile_url": _profile_url(reaction_usernames.get(user_id)),
            "following": False,
            "blocked": False,
            "status": "found" if reaction_usernames.get(user_id) else "unresolved",
            "source": "comment_reaction",
        })
        if not user.get("username") and reaction_usernames.get(user_id):
            user = {
                **user,
                "username": reaction_usernames[user_id],
                "profile_url": _profile_url(reaction_usernames[user_id]),
                "status": "found",
            }
        candidates.append({
            **user,
            "reaction_types": reactions,
            "reaction_count": len(events),
            "is_comment_author": user_id in author_ids,
            "events": events,
        })
    reaction_totals = {
        reaction: sum(1 for event in reaction_events if event["reaction"] == reaction)
        for reaction in sorted({event["reaction"] for event in reaction_events} | COMMENT_REACTIONS)
    }
    result = {
        "ok": True,
        "comment_id": parsed,
        "comments": comments,
        "comment_count": len(comments),
        "reaction_count": len(reaction_events),
        "reaction_totals": reaction_totals,
        "reaction_users": candidates,
        "reaction_user_count": len(candidates),
        "warnings": warnings,
    }
    _save_comment_reaction_history(result)
    return result


def _save_comment_reaction_history(result: dict) -> None:
    comments = result.get("comments") or []
    root = comments[0] if comments else {}
    now = utc_now()
    with transaction() as connection:
        existing = connection.execute(
            "SELECT first_seen_at FROM comment_reaction_history WHERE comment_id = ?",
            (result["comment_id"],),
        ).fetchone()
        first_seen_at = existing["first_seen_at"] if existing else now
        connection.execute(
            "INSERT INTO comment_reaction_history "
            "(comment_id, first_seen_at, last_checked_at, author_user_id, author_username, "
            "content_preview, comment_count, reaction_count, reaction_user_count, "
            "reaction_totals_json, warnings_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(comment_id) DO UPDATE SET "
            "last_checked_at = excluded.last_checked_at, "
            "author_user_id = excluded.author_user_id, "
            "author_username = excluded.author_username, "
            "content_preview = excluded.content_preview, "
            "comment_count = excluded.comment_count, "
            "reaction_count = excluded.reaction_count, "
            "reaction_user_count = excluded.reaction_user_count, "
            "reaction_totals_json = excluded.reaction_totals_json, "
            "warnings_json = excluded.warnings_json",
            (
                result["comment_id"],
                first_seen_at,
                now,
                root.get("author_user_id"),
                root.get("author_username"),
                root.get("content_preview"),
                result.get("comment_count", 0),
                result.get("reaction_count", 0),
                result.get("reaction_user_count", 0),
                json.dumps(result.get("reaction_totals") or {}, ensure_ascii=True),
                json.dumps(result.get("warnings") or [], ensure_ascii=True),
            ),
        )


def list_comment_reaction_history(limit: int = 80) -> dict:
    try:
        limit = min(200, max(1, int(limit)))
    except (TypeError, ValueError):
        limit = 80
    with create_connection() as connection:
        rows = dict_rows(
            connection.execute(
                "SELECT comment_id, first_seen_at, last_checked_at, author_user_id, "
                "author_username, content_preview, comment_count, reaction_count, "
                "reaction_user_count, reaction_totals_json, warnings_json "
                "FROM comment_reaction_history "
                "ORDER BY last_checked_at DESC, comment_id DESC LIMIT ?",
                (limit,),
            )
        )
    for row in rows:
        row["reaction_totals"] = json.loads(row.pop("reaction_totals_json") or "{}")
        row["warnings"] = json.loads(row.pop("warnings_json") or "[]")
    return {"ok": True, "history": rows}


def _comment_reaction_totals(comment: dict) -> dict:
    totals = {reaction: 0 for reaction in COMMENT_REACTIONS}
    for item in comment.get("reactions") or []:
        if not isinstance(item, dict):
            continue
        reaction = _clean_text(item.get("reaction"))
        if reaction:
            totals[reaction] = totals.get(reaction, 0) + 1
    return totals


def list_my_comment_anchors(limit: int = 100, include_replies: bool = True) -> dict:
    config = get_config()
    if not config.username:
        raise ValueError("CivitAI username is missing. Add CIVITAI_USERNAME in Settings first.")
    try:
        limit = min(500, max(1, int(limit)))
    except (TypeError, ValueError):
        limit = 100
    client = CivitaiClient(config)
    profile = client.fetch_user_profile(config.username)
    user_id = _safe_optional_int((profile or {}).get("id"))
    if not user_id:
        raise ValueError("Could not resolve the configured CivitAI username to a user ID.")
    comments = client.fetch_legacy_comments_by_user(user_id, limit=min(100, limit), max_pages=max(1, (limit + 99) // 100))
    anchors = []
    for comment in comments:
        comment_id = _safe_optional_int(comment.get("id"))
        if not comment_id:
            continue
        parent_id = _safe_optional_int(comment.get("parentId"))
        if parent_id and not include_replies:
            continue
        model = comment.get("model") if isinstance(comment.get("model"), dict) else {}
        reactions = comment.get("reactions") or []
        reply_count = (comment.get("_count") or {}).get("comments") if isinstance(comment.get("_count"), dict) else None
        anchors.append({
            "comment_id": comment_id,
            "parent_comment_id": parent_id,
            "kind": "reply" if parent_id else "main",
            "created_at": _clean_text(comment.get("createdAt")),
            "model_id": _safe_optional_int(comment.get("modelId")),
            "model_name": _clean_text(model.get("name")),
            "content_preview": _plain_comment_text(comment.get("content"), limit=150),
            "reaction_count": len(reactions) if isinstance(reactions, list) else 0,
            "reply_count": _safe_optional_int(reply_count) or 0,
            "reaction_totals": _comment_reaction_totals(comment),
        })
        if len(anchors) >= limit:
            break
    return {
        "ok": True,
        "username": config.username,
        "user_id": user_id,
        "comments": anchors,
        "count": len(anchors),
    }


def block_users_by_ids(user_ids) -> dict:
    ids = _parse_user_ids(user_ids)
    config = get_config()
    if not config.api_key:
        raise ValueError("CivitAI API key is missing. Add CIVITAI_API_KEY before blocking users.")
    client = CivitaiClient(config)
    blocked = []
    failures = []
    for user_id in ids:
        try:
            client.set_blocked_user(user_id, True)
            blocked.append(user_id)
        except CivitaiError as exc:
            failures.append({"user_id": user_id, "error": str(exc)})
    resolved = resolve_users_by_ids(blocked) if blocked else {"users": [], "warnings": []}
    return {
        "ok": True,
        "blocked_ids": blocked,
        "blocked_count": len(blocked),
        "failures": failures,
        "failed_count": len(failures),
        "users": resolved.get("users", []),
        "warnings": resolved.get("warnings", []),
    }


def update_user_relationship(user_id, action: str) -> dict:
    parsed = _safe_optional_int(user_id)
    if parsed is None or parsed <= 0:
        raise ValueError("user_id must be a positive integer.")
    action = _clean_text(action, "").lower()
    if action not in {"follow", "block", "unblock"}:
        raise ValueError("Action must be follow, block, or unblock.")
    config = get_config()
    if not config.api_key:
        raise ValueError("CivitAI API key is missing. Add CIVITAI_API_KEY before changing user relationships.")
    client = CivitaiClient(config)
    if action == "follow":
        action_result = client.toggle_follow_user(parsed)
    else:
        action_result = client.set_blocked_user(parsed, action == "block")
    resolved = resolve_users_by_ids([parsed])
    user = resolved["users"][0] if resolved["users"] else {"user_id": parsed}
    return {
        "ok": True,
        "action": action,
        "user": user,
        "result": action_result,
        "warnings": resolved.get("warnings", []),
    }
