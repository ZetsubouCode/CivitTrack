import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urlparse

import requests

from .civitai_client import CivitaiClient, CivitaiError
from .config import get_config
from .db import create_connection, dict_rows, insert_sync_log, transaction, utc_now


IMAGE_SYNC_DEFAULT_PAGES = 1
IMAGE_SYNC_MAX_PAGES = 5
IMAGE_SYNC_DEFAULT_MAX_VERSIONS = 12
IMAGE_SYNC_MAX_VERSIONS = 200
IMAGE_PAGE_LIMIT = 100
IMAGE_LIST_LIMIT = 80
IMAGE_LIST_MAX_LIMIT = 240
IMAGE_STATS_REFRESH_SECONDS = 300
IMAGE_STATS_REFRESH_MAX_ROWS = 48
IMAGE_STATS_REFRESH_WORKERS = 6
REACTION_TYPES = {"Like", "Heart", "Laugh", "Cry"}
COMMENT_REACTION_TYPES = {"Like", "Laugh", "Cry", "Heart"}
REACTION_COUNT_COLUMNS = {
    "Like": "like_count",
    "Heart": "heart_count",
    "Laugh": "laugh_count",
    "Cry": "cry_count",
}
RATING_FILTERS = {
    "pg": ("pg", "none", "sfw"),
    "pg13": ("pg-13", "pg13", "soft"),
    "r": ("r", "mature"),
    "x": ("x",),
    "xxx": ("xxx",),
}


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


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


def _http_url(value) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    return text if urlparse(text).scheme in {"http", "https"} else None


def _json(payload) -> str:
    return json.dumps(deepcopy(payload), ensure_ascii=True, separators=(",", ":"))


def _bool_filter(value) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _selected_rating_filters(filters) -> list[str]:
    values = []
    if hasattr(filters, "getlist"):
        values.extend(filters.getlist("rating"))
    else:
        value = filters.get("rating")
        if isinstance(value, (list, tuple, set)):
            values.extend(value)
        else:
            values.append(value)
    selected = []
    for value in values:
        for part in str(value or "").split(","):
            key = part.strip().lower()
            if key in RATING_FILTERS and key not in selected:
                selected.append(key)
    return selected


def _append_rating_filter(clauses: list[str], values: list, filters) -> None:
    selected = _selected_rating_filters(filters)
    if not selected:
        return
    names = []
    for rating in selected:
        for name in RATING_FILTERS[rating]:
            if name not in names:
                names.append(name)
    placeholders = ", ".join("?" for _ in names)
    if "pg" in selected:
        clauses.append(f"(LOWER(COALESCE(nsfw_level, '')) IN ({placeholders}) OR nsfw = 0)")
    else:
        clauses.append(f"LOWER(COALESCE(nsfw_level, '')) IN ({placeholders})")
    values.extend(names)


def _parse_timestamp(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stats_are_stale(value) -> bool:
    refreshed_at = _parse_timestamp(value)
    if not refreshed_at:
        return True
    age = datetime.now(timezone.utc) - refreshed_at
    return age > timedelta(seconds=IMAGE_STATS_REFRESH_SECONDS)


def _local_day_utc_bounds() -> tuple[str, str, str]:
    start_local = datetime.now().astimezone().replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    end_local = start_local + timedelta(days=1)
    return (
        start_local.date().isoformat(),
        start_local.astimezone(timezone.utc).isoformat(timespec="microseconds"),
        end_local.astimezone(timezone.utc).isoformat(timespec="microseconds"),
    )


def get_reaction_usage(connection=None) -> dict:
    limit = get_config().reaction_daily_bonus_warning_limit
    day, start_at, end_at = _local_day_utc_bounds()
    owns_connection = connection is None
    connection = connection or create_connection()
    try:
        count = connection.execute(
            "SELECT COUNT(*) FROM reaction_action_log "
            "WHERE created_at >= ? AND created_at < ?",
            (start_at, end_at),
        ).fetchone()[0]
    finally:
        if owns_connection:
            connection.close()
    return {
        "date": day,
        "today_count": int(count or 0),
        "warning_limit": limit,
        "warning_enabled": limit > 0,
        "remaining_before_warning": max(0, limit - int(count or 0)) if limit > 0 else None,
    }


def _record_reaction_action(
    connection, entity_type: str, entity_id: int, reaction: str, created_at: str
) -> None:
    connection.execute(
        "INSERT INTO reaction_action_log (entity_type, entity_id, reaction, created_at) "
        "VALUES (?, ?, ?, ?)",
        (entity_type, entity_id, reaction, created_at),
    )


def _latest_snapshot_versions(
    connection,
    username: str,
    model_id: int | None = None,
    model_version_id: int | None = None,
    max_versions: int = IMAGE_SYNC_DEFAULT_MAX_VERSIONS,
) -> list[dict]:
    snapshot = connection.execute(
        "SELECT id FROM snapshot WHERE username = ? AND api_ok = 1 "
        "ORDER BY checked_at DESC, id DESC LIMIT 1",
        (username,),
    ).fetchone()
    if not snapshot:
        return []
    clauses = ["snapshot_id = ?"]
    values = [snapshot["id"]]
    if model_id:
        clauses.append("model_id = ?")
        values.append(model_id)
    if model_version_id:
        clauses.append("model_version_id = ?")
        values.append(model_version_id)
    return dict_rows(
        connection.execute(
            "SELECT model_id, model_name, model_version_id, version_name, base_model "
            f"FROM model_version_snapshot WHERE {' AND '.join(clauses)} "
            "ORDER BY published_at DESC, model_version_id DESC LIMIT ?",
            (*values, max_versions),
        )
    )


def _normalize_image(
    image: dict,
    version: dict,
    sync_id: int,
    checked_at: str,
    base_url: str,
) -> dict | None:
    image_id = _safe_optional_int(image.get("id"))
    model_id = _safe_optional_int(version.get("model_id"))
    model_version_id = _safe_optional_int(version.get("model_version_id"))
    if not image_id or not model_id or not model_version_id:
        return None
    stats = image.get("stats") or {}
    return {
        "image_id": image_id,
        "post_id": _safe_optional_int(image.get("postId")),
        "model_id": model_id,
        "model_name": _clean_text(version.get("model_name"), f"Model {model_id}"),
        "model_version_id": model_version_id,
        "version_name": _clean_text(version.get("version_name")),
        "base_model": _clean_text(image.get("baseModel"), _clean_text(version.get("base_model"))),
        "image_url": _http_url(image.get("url")),
        "image_page_url": f"{base_url.rstrip('/')}/images/{image_id}",
        "creator_user_id": _safe_optional_int(image.get("userId") or (image.get("user") or {}).get("id")),
        "width": _safe_optional_int(image.get("width")),
        "height": _safe_optional_int(image.get("height")),
        "nsfw_level": _clean_text(image.get("nsfwLevel")),
        "nsfw": int(bool(image.get("nsfw"))),
        "image_type": _clean_text(image.get("type")),
        "published_at": _clean_text(image.get("createdAt")),
        "username": _clean_text(image.get("username")),
        "cry_count": _safe_int(stats.get("cryCount")),
        "laugh_count": _safe_int(stats.get("laughCount")),
        "like_count": _safe_int(stats.get("likeCount")),
        "dislike_count": _safe_int(stats.get("dislikeCount")),
        "heart_count": _safe_int(stats.get("heartCount")),
        "comment_count": _safe_int(stats.get("commentCount")),
        "stats_refreshed_at": checked_at,
        "reaction_refreshed_at": None,
        "model_version_ids_json": json.dumps(image.get("modelVersionIds") or [], ensure_ascii=True),
        "last_seen_at": checked_at,
        "latest_sync_id": sync_id,
        "raw_json": _json(image),
    }


def _upsert_image(connection, row: dict, checked_at: str) -> bool:
    existing = connection.execute(
        "SELECT id FROM model_image WHERE image_id = ?", (row["image_id"],)
    ).fetchone()
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    assignments = ", ".join(
        f"{column} = excluded.{column}"
        for column in row
        if column not in {"image_id"}
    )
    connection.execute(
        f"INSERT INTO model_image ({columns}, first_seen_at) "
        f"VALUES ({placeholders}, ?) "
        "ON CONFLICT(image_id) DO UPDATE SET "
        f"{assignments}",
        (*row.values(), checked_at),
    )
    return existing is None


def _image_stat_counts(image: dict) -> dict:
    stats = image.get("stats") if isinstance(image, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    return {
        "cry_count": _safe_int(stats.get("cryCount", stats.get("cryCountAllTime"))),
        "laugh_count": _safe_int(stats.get("laughCount", stats.get("laughCountAllTime"))),
        "like_count": _safe_int(stats.get("likeCount", stats.get("likeCountAllTime"))),
        "dislike_count": _safe_int(stats.get("dislikeCount", stats.get("dislikeCountAllTime"))),
        "heart_count": _safe_int(stats.get("heartCount", stats.get("heartCountAllTime"))),
        "comment_count": _safe_int(stats.get("commentCount", stats.get("commentCountAllTime"))),
    }


def _image_user_reactions(image: dict) -> list[str] | None:
    if not isinstance(image, dict) or "reactions" not in image:
        return None
    reactions = image.get("reactions") or []
    if not isinstance(reactions, list):
        return []
    active = {
        item.get("reaction")
        for item in reactions
        if isinstance(item, dict) and item.get("reaction") in REACTION_TYPES
    }
    return sorted(active)


def _write_image_reaction_state(
    connection, image_id: int, reactions: list[str], refreshed_at: str
) -> None:
    active = set(reactions)
    for reaction in sorted(REACTION_TYPES):
        connection.execute(
            "INSERT INTO image_reaction_state (image_id, reaction, is_active, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(image_id, reaction) DO UPDATE SET "
            "is_active = excluded.is_active, updated_at = excluded.updated_at",
            (image_id, reaction, int(reaction in active), refreshed_at),
        )
    connection.execute(
        "UPDATE model_image SET reaction_refreshed_at = ? WHERE image_id = ?",
        (refreshed_at, image_id),
    )


def _write_image_stats(connection, image_id: int, image: dict, refreshed_at: str) -> dict:
    counts = _image_stat_counts(image)
    connection.execute(
        "UPDATE model_image SET cry_count = ?, laugh_count = ?, like_count = ?, "
        "dislike_count = ?, heart_count = ?, comment_count = ?, stats_refreshed_at = ?, "
        "raw_json = ? WHERE image_id = ?",
        (
            counts["cry_count"],
            counts["laugh_count"],
            counts["like_count"],
            counts["dislike_count"],
            counts["heart_count"],
            counts["comment_count"],
            refreshed_at,
            _json(image),
            image_id,
        ),
    )
    reactions = _image_user_reactions(image)
    if reactions is not None:
        _write_image_reaction_state(connection, image_id, reactions, refreshed_at)
    return counts


def _refresh_image_stats(connection, client: CivitaiClient, image_id: int) -> dict | None:
    try:
        for image in client.fetch_images_by_ids([image_id]):
            if _safe_optional_int(image.get("id")) == image_id:
                return _write_image_stats(connection, image_id, image, utc_now())
    except CivitaiError:
        pass
    image = client.fetch_image_by_id(image_id)
    if not image:
        return None
    return _write_image_stats(connection, image_id, image, utc_now())


def _fetch_image_stats_for_row(config, image_id: int) -> tuple[int, dict | None]:
    image = CivitaiClient(config).fetch_image_by_id(image_id)
    return image_id, image


def _refresh_image_stats_for_rows(rows: list[dict]) -> None:
    stale_ids = [
        int(row["image_id"])
        for row in rows
        if row.get("image_id")
        and (
            _stats_are_stale(row.get("stats_refreshed_at"))
            or _stats_are_stale(row.get("reaction_refreshed_at"))
        )
    ][:IMAGE_STATS_REFRESH_MAX_ROWS]
    if not stale_ids:
        return

    config = get_config()
    fetched: dict[int, dict] = {}
    try:
        for image in CivitaiClient(config).fetch_images_by_ids(stale_ids):
            image_id = _safe_optional_int(image.get("id"))
            if image_id:
                fetched[image_id] = image
    except CivitaiError:
        fetched = {}

    if len(fetched) < len(stale_ids):
        missing_ids = [image_id for image_id in stale_ids if image_id not in fetched]
    else:
        missing_ids = []

    if not fetched and not missing_ids:
        return

    max_workers = min(IMAGE_STATS_REFRESH_WORKERS, len(stale_ids))
    if missing_ids and max_workers:
        max_workers = min(IMAGE_STATS_REFRESH_WORKERS, len(missing_ids))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_fetch_image_stats_for_row, config, image_id): image_id
                for image_id in missing_ids
            }
            for future in as_completed(futures):
                try:
                    image_id, image = future.result()
                except CivitaiError:
                    continue
                if isinstance(image, dict):
                    fetched[int(image_id)] = image
    if not fetched:
        return

    refreshed_at = utc_now()
    refreshed_counts: dict[int, dict] = {}
    with transaction() as connection:
        for image_id, image in fetched.items():
            refreshed_counts[image_id] = _write_image_stats(connection, image_id, image, refreshed_at)

    for row in rows:
        image_id = int(row.get("image_id") or 0)
        counts = refreshed_counts.get(image_id)
        if counts:
            row.update(counts)
            row["stats_refreshed_at"] = refreshed_at
            if _image_user_reactions(fetched.get(image_id, {})) is not None:
                row["reaction_refreshed_at"] = refreshed_at


def _active_reactions(connection, image_id: int) -> list[str]:
    return [
        row["reaction"]
        for row in connection.execute(
            "SELECT reaction FROM image_reaction_state WHERE image_id = ? AND is_active = 1 "
            "ORDER BY reaction",
            (image_id,),
        )
    ]


def _active_comment_reactions(connection, comment_id: int) -> list[str]:
    return [
        row["reaction"]
        for row in connection.execute(
            "SELECT reaction FROM comment_reaction_state WHERE comment_id = ? AND is_active = 1 "
            "ORDER BY reaction",
            (comment_id,),
        )
    ]


def _comment_reaction_counts(comment: dict, _local_reactions: list[str]) -> dict:
    counts = {reaction: 0 for reaction in COMMENT_REACTION_TYPES}
    for item in comment.get("reactions") or []:
        if not isinstance(item, dict):
            continue
        reaction = item.get("reaction")
        if reaction in counts:
            counts[reaction] += 1
    return counts


def _augment_comments(connection, comments: list[dict]) -> list[dict]:
    augmented = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        item = dict(comment)
        comment_id = _safe_optional_int(item.get("id"))
        local = _active_comment_reactions(connection, comment_id) if comment_id else []
        item["local_reactions"] = local
        item["reaction_counts"] = _comment_reaction_counts(item, local)
        item["reactionCount"] = max(
            _safe_int(item.get("reactionCount")),
            sum(item["reaction_counts"].values()),
        )
        augmented.append(item)
    return augmented


def _hidden_image_clause() -> str:
    return (
        "image_id NOT IN (SELECT image_id FROM hidden_image_preference) "
        "AND (creator_user_id IS NULL OR creator_user_id NOT IN "
        "(SELECT user_id FROM blocked_user_preference WHERE user_id IS NOT NULL)) "
        "AND (username IS NULL OR LOWER(username) NOT IN "
        "(SELECT LOWER(username) FROM blocked_user_preference "
        "WHERE username IS NOT NULL AND username != ''))"
    )


def sync_hidden_images(source: str = "manual") -> dict:
    config = get_config()
    if not config.api_key:
        return {
            "ok": False,
            "error": "API key is missing. Hidden image preferences cannot be synced.",
            "hidden_count": 0,
            "blocked_user_count": 0,
        }
    client = CivitaiClient(config)
    preferences = client.fetch_hidden_preferences()
    hidden_images = preferences.get("hiddenImages") or []
    if not isinstance(hidden_images, list):
        raise CivitaiError("CivitAI returned hidden image preferences in an unexpected format.")
    blocked_users = preferences.get("blockedUsers") or []
    if not isinstance(blocked_users, list):
        raise CivitaiError("CivitAI returned blocked user preferences in an unexpected format.")
    now = utc_now()
    ids: set[int] = set()
    rows = []
    for item in hidden_images:
        if isinstance(item, dict):
            image_id = _safe_optional_int(item.get("id"))
            raw = _json(item)
        else:
            image_id = _safe_optional_int(item)
            raw = _json({"id": image_id})
        if image_id:
            ids.add(image_id)
            rows.append((image_id, source, now, raw))
    blocked_rows = []
    blocked_user_keys = set()
    for item in blocked_users:
        if not isinstance(item, dict):
            continue
        user_id = _safe_optional_int(item.get("id"))
        username = _clean_text(item.get("username"))
        if not user_id and not username:
            continue
        key = (user_id, (username or "").casefold())
        if key in blocked_user_keys:
            continue
        blocked_user_keys.add(key)
        blocked_rows.append((user_id, username, source, now, _json(item)))
    with transaction() as connection:
        connection.execute("DELETE FROM hidden_image_preference")
        connection.execute("DELETE FROM blocked_user_preference")
        connection.executemany(
            "INSERT INTO hidden_image_preference (image_id, source, hidden_at, raw_json) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        connection.executemany(
            "INSERT INTO blocked_user_preference (user_id, username, source, blocked_at, raw_json) "
            "VALUES (?, ?, ?, ?, ?)",
            blocked_rows,
        )
        if source != "status":
            insert_sync_log(
                "info",
                f"Synced {len(ids)} hidden image preference{'' if len(ids) == 1 else 's'} "
                f"and {len(blocked_rows)} blocked user{'' if len(blocked_rows) == 1 else 's'} from CivitAI.",
                connection,
            )
    return {
        "ok": True,
        "error": "",
        "hidden_count": len(ids),
        "blocked_user_count": len(blocked_rows),
        "checked_at": now,
    }


def run_image_sync(
    source: str = "manual",
    pages_per_version: int = IMAGE_SYNC_DEFAULT_PAGES,
    with_meta: bool = False,
    model_id: int | None = None,
    model_version_id: int | None = None,
    max_versions: int = IMAGE_SYNC_DEFAULT_MAX_VERSIONS,
) -> dict:
    config = get_config()
    if not config.api_key:
        return _record_failed_sync("API key is missing. Add CIVITAI_API_KEY before syncing images.", source)
    if not config.username:
        return _record_failed_sync("Username is missing. Add CIVITAI_USERNAME before syncing images.", source)
    try:
        pages_per_version = int(pages_per_version)
    except (TypeError, ValueError):
        pages_per_version = IMAGE_SYNC_DEFAULT_PAGES
    pages_per_version = min(IMAGE_SYNC_MAX_PAGES, max(1, pages_per_version))
    model_id = _safe_optional_int(model_id)
    model_version_id = _safe_optional_int(model_version_id)
    try:
        max_versions = int(max_versions)
    except (TypeError, ValueError):
        max_versions = IMAGE_SYNC_DEFAULT_MAX_VERSIONS
    max_versions = min(IMAGE_SYNC_MAX_VERSIONS, max(1, max_versions))

    with create_connection() as connection:
        versions = _latest_snapshot_versions(
            connection,
            config.username,
            model_id=model_id,
            model_version_id=model_version_id,
            max_versions=max_versions,
        )
    if not versions:
        return _record_failed_sync("Take a model snapshot before syncing public images.", source)

    checked_at = utc_now()
    client = CivitaiClient(config)
    warnings: list[str] = []
    info: list[str] = []
    normalized_rows: list[dict] = []
    with transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO image_sync "
            "(checked_at, username, source, api_ok, version_count, image_count, new_image_count, "
            "warning_count, warnings_json, info_json, created_at) "
            "VALUES (?, ?, ?, 1, ?, 0, 0, 0, '[]', '[]', ?)",
            (checked_at, config.username, source, len(versions), checked_at),
        )
        sync_id = cursor.lastrowid

    for version in versions:
        version_id = _safe_optional_int(version.get("model_version_id"))
        if not version_id:
            continue
        try:
            images, fetched_pages = client.fetch_model_version_images(
                version_id,
                pages=pages_per_version,
                limit=IMAGE_PAGE_LIMIT,
                with_meta=with_meta,
            )
        except CivitaiError as exc:
            warnings.append(
                f"Images unavailable for {version.get('model_name')} / "
                f"{version.get('version_name') or version_id}: {exc}"
            )
            continue
        info.append(
            f"Fetched {len(images)} public images for {version.get('model_name')} / "
            f"{version.get('version_name') or version_id} across {fetched_pages} page"
            f"{'' if fetched_pages == 1 else 's'}."
        )
        for image in images:
            row = _normalize_image(image, version, sync_id, checked_at, config.base_url)
            if row:
                normalized_rows.append(row)

    with transaction() as connection:
        new_count = 0
        seen_image_ids = set()
        for row in normalized_rows:
            image_id = row["image_id"]
            if image_id in seen_image_ids:
                continue
            seen_image_ids.add(image_id)
            if _upsert_image(connection, row, checked_at):
                new_count += 1
        connection.execute(
            "UPDATE image_sync SET image_count = ?, new_image_count = ?, warning_count = ?, "
            "warnings_json = ?, info_json = ? WHERE id = ?",
            (
                len(seen_image_ids),
                new_count,
                len(warnings),
                json.dumps(warnings, ensure_ascii=True),
                json.dumps(info, ensure_ascii=True),
                sync_id,
            ),
        )
        for message in info:
            insert_sync_log("info", message, connection)
        for warning in warnings:
            insert_sync_log("warning", warning, connection)
        insert_sync_log(
            "info",
            f"Image sync {sync_id} saved: {len(seen_image_ids)} linked public images, "
            f"{new_count} new.",
            connection,
        )
    try:
        hidden_result = sync_hidden_images(source="image-sync")
        if hidden_result.get("ok"):
            info.append(
                f"Filtered {hidden_result['hidden_count']} CivitAI-hidden image"
                f"{'' if hidden_result['hidden_count'] == 1 else 's'} from gallery results."
            )
        else:
            warnings.append(hidden_result.get("error") or "Hidden image preferences could not be synced.")
    except CivitaiError as exc:
        warnings.append(f"Hidden image preferences could not be synced: {exc}")
    with transaction() as connection:
        connection.execute(
            "UPDATE image_sync SET warning_count = ?, warnings_json = ?, info_json = ? WHERE id = ?",
            (
                len(warnings),
                json.dumps(warnings, ensure_ascii=True),
                json.dumps(info, ensure_ascii=True),
                sync_id,
            ),
        )
        for message in info:
            if message.startswith("Filtered "):
                insert_sync_log("info", message, connection)
        for warning in warnings:
            if warning.startswith("Hidden image preferences"):
                insert_sync_log("warning", warning, connection)
    return {
        "ok": True,
        "error": "",
        "image_sync_id": sync_id,
        "checked_at": checked_at,
        "version_count": len(versions),
        "image_count": len(seen_image_ids),
        "new_image_count": new_count,
        "warnings": warnings,
        "info": info,
    }


def _record_failed_sync(error: str, source: str) -> dict:
    config = get_config()
    now = utc_now()
    with transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO image_sync "
            "(checked_at, username, source, api_ok, error, version_count, image_count, "
            "new_image_count, warning_count, warnings_json, info_json, created_at) "
            "VALUES (?, ?, ?, 0, ?, 0, 0, 0, 1, ?, '[]', ?)",
            (now, config.username, source, error, json.dumps([error]), now),
        )
        insert_sync_log("warning", error, connection)
    return {
        "ok": False,
        "error": error,
        "image_sync_id": cursor.lastrowid,
        "checked_at": now,
        "version_count": 0,
        "image_count": 0,
        "new_image_count": 0,
        "warnings": [error],
        "info": [],
    }


def latest_image_summary() -> dict:
    config = get_config()
    with create_connection() as connection:
        latest = connection.execute(
            "SELECT * FROM image_sync WHERE username = ? ORDER BY checked_at DESC, id DESC LIMIT 1",
            (config.username,),
        ).fetchone()
        totals = connection.execute(
            "SELECT COUNT(*) AS image_count, COUNT(DISTINCT model_id) AS model_count, "
            "COUNT(DISTINCT model_version_id) AS version_count, MAX(published_at) AS newest_image_at "
            f"FROM model_image WHERE {_hidden_image_clause()}"
        ).fetchone()
        hidden = connection.execute(
            "SELECT COUNT(*) AS hidden_count, MAX(hidden_at) AS hidden_checked_at "
            "FROM hidden_image_preference"
        ).fetchone()
        blocked = connection.execute(
            "SELECT COUNT(*) AS blocked_user_count, MAX(blocked_at) AS blocked_checked_at "
            "FROM blocked_user_preference"
        ).fetchone()
    latest_dict = dict(latest) if latest else None
    if latest_dict:
        latest_dict["warnings"] = json.loads(latest_dict.pop("warnings_json") or "[]")
        latest_dict["info"] = json.loads(latest_dict.pop("info_json") or "[]")
    return {
        "latest_sync": latest_dict,
        "totals": dict(totals) if totals else {
            "image_count": 0,
            "model_count": 0,
            "version_count": 0,
            "newest_image_at": None,
        },
        "hidden": dict(hidden) if hidden else {"hidden_count": 0, "hidden_checked_at": None},
        "blocked": dict(blocked) if blocked else {"blocked_user_count": 0, "blocked_checked_at": None},
    }


def list_model_images(filters=None) -> dict:
    filters = filters or {}
    config = get_config()
    clauses = []
    values = []
    clauses.append(_hidden_image_clause())
    model_id = _safe_optional_int(filters.get("model_id"))
    version_id = _safe_optional_int(filters.get("model_version_id"))
    if model_id:
        clauses.append("model_id = ?")
        values.append(model_id)
    if version_id:
        clauses.append("model_version_id = ?")
        values.append(version_id)
    username = _clean_text(filters.get("username"))
    if username:
        clauses.append("username LIKE ?")
        values.append(f"%{username}%")
    if _bool_filter(filters.get("hide_own")) and config.username:
        clauses.append("(username IS NULL OR LOWER(username) != LOWER(?))")
        values.append(config.username)
    search = _clean_text(filters.get("search"))
    if search:
        clauses.append("(model_name LIKE ? OR version_name LIKE ? OR username LIKE ? OR CAST(image_id AS TEXT) LIKE ?)")
        values.extend([f"%{search}%"] * 4)
    nsfw = _clean_text(filters.get("nsfw"))
    if nsfw in {"0", "1"}:
        clauses.append("nsfw = ?")
        values.append(int(nsfw))
    _append_rating_filter(clauses, values, filters)
    try:
        limit = min(IMAGE_LIST_MAX_LIMIT, max(1, int(filters.get("limit", IMAGE_LIST_LIMIT))))
    except (TypeError, ValueError):
        limit = IMAGE_LIST_LIMIT
    try:
        offset = max(0, int(filters.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    sort = _clean_text(filters.get("sort"), "newest")
    order_by = {
        "oldest": "COALESCE(published_at, first_seen_at) ASC, image_id ASC",
        "reactions": "(like_count + heart_count + laugh_count + cry_count) DESC, COALESCE(published_at, first_seen_at) DESC",
        "comments": "comment_count DESC, COALESCE(published_at, first_seen_at) DESC",
        "newest": "COALESCE(published_at, first_seen_at) DESC, image_id DESC",
    }.get(sort, "COALESCE(published_at, first_seen_at) DESC, image_id DESC")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with create_connection() as connection:
        total = connection.execute(f"SELECT COUNT(*) FROM model_image {where}", values).fetchone()[0]
        rows = dict_rows(
            connection.execute(
                f"SELECT id, image_id, post_id, model_id, model_name, model_version_id, version_name, "
                f"base_model, image_url, image_page_url, creator_user_id, width, height, nsfw_level, nsfw, image_type, "
                f"published_at, username, cry_count, laugh_count, like_count, dislike_count, heart_count, "
                f"comment_count, stats_refreshed_at, reaction_refreshed_at, first_seen_at, last_seen_at FROM model_image {where} "
                f"ORDER BY {order_by} LIMIT ? OFFSET ?",
                (*values, limit, offset),
            )
        )
        _refresh_image_stats_for_rows(rows)
        reactions = {
            row["image_id"]: []
            for row in rows
        }
        if reactions:
            placeholders = ", ".join("?" for _ in reactions)
            for row in connection.execute(
                f"SELECT image_id, reaction FROM image_reaction_state "
                f"WHERE is_active = 1 AND image_id IN ({placeholders})",
                tuple(reactions),
            ):
                reactions[row["image_id"]].append(row["reaction"])
            for row in rows:
                row["local_reactions"] = reactions.get(row["image_id"], [])
    return {
        "images": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(rows) < total,
    }


def list_image_models(filters=None) -> dict:
    filters = filters or {}
    config = get_config()
    clauses = []
    values = []
    clauses.append(_hidden_image_clause())
    if _bool_filter(filters.get("hide_own")) and config.username:
        clauses.append("(username IS NULL OR LOWER(username) != LOWER(?))")
        values.append(config.username)
    _append_rating_filter(clauses, values, filters)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with create_connection() as connection:
        models = dict_rows(
            connection.execute(
                "SELECT model_id, model_name, COUNT(*) AS image_count "
                f"FROM model_image {where} GROUP BY model_id, model_name ORDER BY model_name",
                values,
            )
        )
        versions = dict_rows(
            connection.execute(
                "SELECT model_id, model_version_id, version_name, COUNT(*) AS image_count "
                f"FROM model_image {where} GROUP BY model_id, model_version_id, version_name "
                "ORDER BY version_name"
                ,
                values,
            )
        )
        rating_levels = dict_rows(
            connection.execute(
                "SELECT COALESCE(nsfw_level, CASE WHEN nsfw = 1 THEN 'NSFW' ELSE 'PG' END) AS nsfw_level, "
                "COUNT(*) AS image_count FROM model_image "
                f"{where} GROUP BY COALESCE(nsfw_level, CASE WHEN nsfw = 1 THEN 'NSFW' ELSE 'PG' END) "
                "ORDER BY image_count DESC",
                values,
            )
        )
    return {"models": models, "versions": versions, "rating_levels": rating_levels}


def get_model_image_detail(image_id: int, refresh_stats: bool = True) -> dict:
    config = get_config()
    stats_error = ""
    with create_connection() as connection:
        if refresh_stats:
            try:
                _refresh_image_stats(connection, CivitaiClient(config), image_id)
                connection.commit()
            except CivitaiError as exc:
                stats_error = str(exc)
        row = connection.execute(
            "SELECT * FROM model_image WHERE image_id = ?", (image_id,)
        ).fetchone()
        if not row:
            raise ValueError("Stored image could not be found.")
        detail = dict(row)
        detail["local_reactions"] = _active_reactions(connection, image_id)
        detail["stats_error"] = stats_error
    try:
        client = CivitaiClient(config)
        comment_count = client.fetch_image_comment_count(image_id)
        comments = client.fetch_image_comments(image_id, limit=20)
        detail["comment_count"] = comment_count
        with create_connection() as connection:
            detail["comments"] = _augment_comments(connection, comments.get("comments") or [])
        detail["comments_next_cursor"] = comments.get("nextCursor")
        detail["comments_error"] = ""
        with transaction() as connection:
            connection.execute(
                "UPDATE model_image SET comment_count = ? WHERE image_id = ?",
                (comment_count, image_id),
            )
    except CivitaiError as exc:
        detail["comments"] = []
        detail["comments_next_cursor"] = None
        detail["comments_error"] = str(exc)
    detail["raw_json"] = json.loads(detail["raw_json"] or "{}")
    detail["model_version_ids"] = json.loads(detail.pop("model_version_ids_json") or "[]")
    detail["model_page_url"] = config.model_page_url(detail["model_id"])
    return detail


def _comment_html(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        raise ValueError("Comment cannot be empty.")
    if len(cleaned) > 8000:
        raise ValueError("Comment is too long.")
    return "<p>" + "<br>".join(escape(line) for line in cleaned.splitlines()) + "</p>"


def post_image_comment(image_id: int, content: str) -> dict:
    config = get_config()
    if not config.api_key:
        raise ValueError("API key is missing. Add a CivitAI API key before commenting.")
    image_id = _safe_optional_int(image_id)
    if not image_id:
        raise ValueError("Image ID is required.")
    with create_connection() as connection:
        row = connection.execute(
            "SELECT image_id FROM model_image WHERE image_id = ?", (image_id,)
        ).fetchone()
        if not row:
            raise ValueError("Stored image could not be found.")
    comment = CivitaiClient(config).post_image_comment(image_id, _comment_html(content))
    with transaction() as connection:
        connection.execute(
            "UPDATE model_image SET comment_count = COALESCE(comment_count, 0) + 1 "
            "WHERE image_id = ?",
            (image_id,),
        )
    return {"ok": True, "comment": comment, "image": get_model_image_detail(image_id)}


def post_comment_reply(image_id: int, comment_id: int, parent_thread_id: int, content: str) -> dict:
    config = get_config()
    if not config.api_key:
        raise ValueError("API key is missing. Add a CivitAI API key before replying.")
    image_id = _safe_optional_int(image_id)
    comment_id = _safe_optional_int(comment_id)
    parent_thread_id = _safe_optional_int(parent_thread_id)
    if not image_id or not comment_id or not parent_thread_id:
        raise ValueError("Image ID, comment ID, and parent thread ID are required.")
    reply = CivitaiClient(config).post_comment_reply(
        comment_id,
        parent_thread_id,
        _comment_html(content),
    )
    return {"ok": True, "reply": reply, "image": get_model_image_detail(image_id)}


def toggle_comment_reaction(image_id: int, comment_id: int, reaction: str) -> dict:
    config = get_config()
    if not config.api_key:
        raise ValueError("API key is missing. Add a CivitAI API key before reacting.")
    image_id = _safe_optional_int(image_id)
    comment_id = _safe_optional_int(comment_id)
    if not image_id or not comment_id:
        raise ValueError("Image ID and comment ID are required.")
    if reaction not in COMMENT_REACTION_TYPES:
        raise ValueError("Comment reaction must be Like, Laugh, Cry, or Heart.")
    client = CivitaiClient(config)
    client.post_trpc(
        "reaction.toggle",
        {"entityId": comment_id, "entityType": "comment", "reaction": reaction},
    )
    now = utc_now()
    with transaction() as connection:
        existing = connection.execute(
            "SELECT is_active FROM comment_reaction_state WHERE comment_id = ? AND reaction = ?",
            (comment_id, reaction),
        ).fetchone()
        next_active = 0 if existing and existing["is_active"] else 1
        connection.execute(
            "INSERT INTO comment_reaction_state (comment_id, reaction, is_active, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(comment_id, reaction) DO UPDATE SET "
            "is_active = excluded.is_active, updated_at = excluded.updated_at",
            (comment_id, reaction, next_active, now),
        )
        if next_active:
            _record_reaction_action(connection, "comment", comment_id, reaction, now)
        reaction_usage = get_reaction_usage(connection)
    return {
        "ok": True,
        "image": get_model_image_detail(image_id, refresh_stats=False),
        "comment_id": comment_id,
        "reaction": reaction,
        "is_active": bool(next_active),
        "reaction_usage": reaction_usage,
    }


def _decode_trpc_response(response) -> None:
    try:
        payload = response.json()
    except ValueError as exc:
        raise CivitaiError("CivitAI returned an invalid reaction response.") from exc
    if isinstance(payload, dict) and payload.get("error"):
        error = payload["error"]
        message = (
            ((error.get("json") or {}).get("message") if isinstance(error.get("json"), dict) else None)
            or error.get("message")
            or "CivitAI rejected the reaction request."
        )
        raise CivitaiError(message)
    if not isinstance(payload, dict):
        raise CivitaiError("CivitAI returned an unexpected reaction response.")


def toggle_image_reaction(image_id: int, reaction: str) -> dict:
    config = get_config()
    if not config.api_key:
        raise ValueError("API key is missing. Add a CivitAI API key before reacting.")
    image_id = _safe_optional_int(image_id)
    if not image_id:
        raise ValueError("Image ID is required.")
    if reaction not in REACTION_TYPES:
        raise ValueError("Reaction must be Like, Heart, Laugh, or Cry.")
    with create_connection() as connection:
        row = connection.execute(
            "SELECT image_id FROM model_image WHERE image_id = ?", (image_id,)
        ).fetchone()
        if not row:
            raise ValueError("Stored image could not be found.")

    client = CivitaiClient(config)
    url = f"{config.base_url}/api/trpc/reaction.toggle"
    payload = {"json": {"entityId": image_id, "entityType": "image", "reaction": reaction}}
    for attempt in range(3):
        try:
            response = client.session.post(
                url,
                json=payload,
                headers=client.get_auth_headers(),
                timeout=config.timeout_seconds,
            )
        except requests.Timeout as exc:
            raise CivitaiError("CivitAI reaction request timed out.") from exc
        except requests.RequestException as exc:
            raise CivitaiError("Could not connect to CivitAI for the reaction request.") from exc
        if response.status_code in (401, 403):
            raise CivitaiError(
                "CivitAI rejected the reaction. Your API key may need SocialWrite access."
            )
        if response.status_code == 429:
            raise CivitaiError("CivitAI rate limited the reaction request.")
        if response.status_code >= 500 and attempt < 2:
            time.sleep(0.5 * (attempt + 1))
            continue
        if not response.ok:
            raise CivitaiError(f"CivitAI reaction API returned HTTP {response.status_code}.")
        _decode_trpc_response(response)
        break
    else:
        raise CivitaiError("CivitAI reaction API is temporarily unavailable.")

    now = utc_now()
    count_column = REACTION_COUNT_COLUMNS[reaction]
    with transaction() as connection:
        existing = connection.execute(
            "SELECT is_active FROM image_reaction_state WHERE image_id = ? AND reaction = ?",
            (image_id, reaction),
        ).fetchone()
        next_active = 0 if existing and existing["is_active"] else 1
        connection.execute(
            "INSERT INTO image_reaction_state (image_id, reaction, is_active, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(image_id, reaction) DO UPDATE SET "
            "is_active = excluded.is_active, updated_at = excluded.updated_at",
            (image_id, reaction, next_active, now),
        )
        delta = 1 if next_active else -1
        connection.execute(
            f"UPDATE model_image SET {count_column} = MAX(0, COALESCE({count_column}, 0) + ?) "
            "WHERE image_id = ?",
            (delta, image_id),
        )
        if next_active:
            _record_reaction_action(connection, "image", image_id, reaction, now)
        reaction_usage = get_reaction_usage(connection)
    detail = get_model_image_detail(image_id, refresh_stats=False)
    return {
        "ok": True,
        "image": detail,
        "reaction": reaction,
        "is_active": bool(next_active),
        "reaction_usage": reaction_usage,
    }
