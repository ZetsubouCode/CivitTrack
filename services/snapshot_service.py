from copy import deepcopy
import json

from .civitai_client import CivitaiClient, CivitaiError
from .config import get_config
from .db import insert_sync_log, transaction, utc_now


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def deep_get(obj: dict, path: str, default=None):
    value = obj
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def _first_stat(stats: dict, *names: str, default=0):
    for name in names:
        if name in stats and stats[name] is not None:
            return stats[name]
    return default


def _reaction_count(stats: dict) -> int:
    if "reactionCount" in stats and stats["reactionCount"] is not None:
        return safe_int(stats["reactionCount"])
    # Use one field per reaction family so aliases are not double-counted.
    return sum(
        safe_int(_first_stat(stats, *aliases))
        for aliases in (
            ("thumbsUpCount", "thumbs_up_count", "likeCount"),
            ("thumbsDownCount", "thumbs_down_count", "dislikeCount"),
            ("heartCount",),
            ("laughCount",),
            ("cryCount",),
        )
    )


def _latest_version(versions: list[dict]) -> dict:
    if not versions:
        return {}
    dated = [version for version in versions if version.get("createdAt")]
    return max(dated, key=lambda version: str(version["createdAt"])) if dated else versions[0]


def _trim_model_json(model: dict) -> str:
    trimmed = deepcopy(model)
    for version in trimmed.get("modelVersions") or []:
        version.pop("images", None)
        version.pop("files", None)
    return json.dumps(trimmed, ensure_ascii=True, separators=(",", ":"))


def _trim_version_json(version: dict) -> str:
    trimmed = deepcopy(version)
    trimmed.pop("images", None)
    trimmed.pop("files", None)
    return json.dumps(trimmed, ensure_ascii=True, separators=(",", ":"))


def _normalize_model(item: dict, snapshot_id: int) -> tuple[dict, list[dict]]:
    stats = item.get("stats") or {}
    versions = [value for value in item.get("modelVersions") or [] if isinstance(value, dict)]
    latest = _latest_version(versions)
    model_id = safe_int(item.get("id"))
    model_name = str(item.get("name") or f"Model {model_id}")
    row = {
        "snapshot_id": snapshot_id,
        "model_id": model_id,
        "model_name": model_name,
        "model_type": item.get("type"),
        "nsfw": int(bool(item.get("nsfw"))),
        "mode": item.get("mode"),
        "page_url": f"https://civitai.com/models/{model_id}",
        "latest_version_id": safe_int(latest.get("id")) or None,
        "latest_version_name": latest.get("name"),
        "base_model": latest.get("baseModel"),
        "published_at": item.get("publishedAt") or item.get("createdAt"),
        "download_count": safe_int(_first_stat(stats, "downloadCount", "download_count")),
        "reaction_count": _reaction_count(stats),
        "favorite_count": safe_int(_first_stat(stats, "favoriteCount", "favorite_count")),
        "comment_count": safe_int(_first_stat(stats, "commentCount", "comment_count")),
        "rating_count": safe_int(_first_stat(stats, "ratingCount", "rating_count")),
        "rating": safe_float(_first_stat(stats, "rating")),
        "thumbs_up_count": safe_int(
            _first_stat(stats, "thumbsUpCount", "thumbs_up_count", "likeCount")
        ),
        "thumbs_down_count": safe_int(
            _first_stat(stats, "thumbsDownCount", "thumbs_down_count", "dislikeCount")
        ),
        "raw_json": _trim_model_json(item),
    }
    version_rows = []
    for version in versions:
        version_id = safe_int(version.get("id"))
        if not version_id:
            continue
        version_stats = version.get("stats") or {}
        version_rows.append(
            {
                "snapshot_id": snapshot_id,
                "model_id": model_id,
                "model_name": model_name,
                "model_version_id": version_id,
                "version_name": version.get("name"),
                "base_model": version.get("baseModel"),
                "published_at": version.get("publishedAt") or version.get("createdAt"),
                "download_count": safe_int(
                    _first_stat(version_stats, "downloadCount", "download_count")
                ),
                "rating_count": safe_int(
                    _first_stat(version_stats, "ratingCount", "rating_count")
                ),
                "rating": safe_float(_first_stat(version_stats, "rating")),
                "raw_json": _trim_version_json(version),
            }
        )
    return row, version_rows


def _insert_dict(connection, table: str, row: dict) -> None:
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    connection.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(row.values())
    )


def _record_failed_snapshot(error: str, source: str) -> None:
    config = get_config()
    now = utc_now()
    with transaction() as connection:
        connection.execute(
            "INSERT INTO snapshot "
            "(checked_at, username, source, model_type_filter, api_ok, error, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (now, config.username, source, config.model_type_filter, error, now),
        )
        insert_sync_log("error", error, connection)


def take_snapshot(source: str = "manual") -> dict:
    config = get_config()
    if not config.api_key:
        error = "API key is missing. Add CIVITAI_API_KEY to .env, restart the app, then try again."
        insert_sync_log("error", error)
        return {"ok": False, "error": error, "warnings": [], "info": []}
    if not config.username:
        error = "Username is missing. Add CIVITAI_USERNAME to .env, restart the app, then try again."
        insert_sync_log("error", error)
        return {"ok": False, "error": error, "warnings": [], "info": []}

    client = CivitaiClient(config)
    warnings: list[str] = []
    try:
        models, info = client.fetch_models(config.username, config.model_types)
    except CivitaiError as exc:
        error = str(exc)
        _record_failed_snapshot(error, source)
        return {"ok": False, "error": error, "warnings": [], "info": []}

    creator = None
    try:
        creator = client.fetch_creator(config.username)
    except CivitaiError:
        warnings.append("Creator profile stats were unavailable. Model snapshot was still saved.")
    follower_count = None
    if creator:
        follower_value = creator.get("followerCount", creator.get("follower_count"))
        follower_count = safe_int(follower_value) if follower_value is not None else None
    if not models:
        warnings.append("No models returned. Check the username or model type filter.")

    checked_at = utc_now()
    with transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO snapshot "
            "(checked_at, username, source, model_type_filter, api_ok, raw_total_item, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?, ?)",
            (
                checked_at,
                config.username,
                source,
                config.model_type_filter,
                len(models),
                checked_at,
            ),
        )
        snapshot_id = cursor.lastrowid
        normalized_models = []
        version_rows = []
        for item in models:
            model_row, rows = _normalize_model(item, snapshot_id)
            if model_row["model_id"]:
                normalized_models.append(model_row)
                version_rows.extend(rows)
        summary = {
            "model_count": len(normalized_models),
            "follower_count": follower_count,
            "total_download_count": sum(row["download_count"] for row in normalized_models),
            "total_reaction_count": sum(row["reaction_count"] for row in normalized_models),
            "total_favorite_count": sum(row["favorite_count"] for row in normalized_models),
            "total_comment_count": sum(row["comment_count"] for row in normalized_models),
            "total_rating_count": sum(row["rating_count"] for row in normalized_models),
            "total_thumbs_up_count": sum(row["thumbs_up_count"] for row in normalized_models),
            "total_thumbs_down_count": sum(row["thumbs_down_count"] for row in normalized_models),
        }
        _insert_dict(
            connection,
            "account_snapshot",
            {"snapshot_id": snapshot_id, "username": config.username, **summary},
        )
        for row in normalized_models:
            _insert_dict(connection, "model_snapshot", row)
        for row in version_rows:
            _insert_dict(connection, "model_version_snapshot", row)
        for message in info:
            insert_sync_log("info", message, connection)
        for warning in warnings:
            insert_sync_log("warning", warning, connection)
        insert_sync_log(
            "info",
            f"Snapshot {snapshot_id} saved: {len(normalized_models)} models and "
            f"{len(version_rows)} versions.",
            connection,
        )
    return {
        "ok": True,
        "error": "",
        "warnings": warnings,
        "info": info,
        "snapshot_id": snapshot_id,
        "checked_at": checked_at,
        "summary": summary,
    }
