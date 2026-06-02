from copy import deepcopy
import json
from urllib.parse import urlparse

from .alert_service import generate_snapshot_alerts, insert_alert
from .civitai_client import CivitaiClient, CivitaiError
from .config import build_model_page_url, get_config
from .db import insert_sync_log, transaction, utc_now


NOTE_TYPES = {
    "normal_check",
    "uploaded_new_model",
    "published_new_version",
    "changed_preview_images",
    "updated_model_description",
    "changed_tags_keywords",
    "shared_promoted_model",
    "other_manual_note",
}


def safe_int(value, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def safe_optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def clean_note(value) -> str | None:
    note = str(value or "").strip()
    if len(note) > 500:
        raise ValueError("Snapshot note must be 500 characters or fewer.")
    return note or None


def clean_note_type(value) -> str:
    note_type = str(value or "normal_check").strip()
    if note_type not in NOTE_TYPES:
        raise ValueError("Snapshot note type is not recognized.")
    return note_type


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
            ("heartCount",),
            ("laughCount",),
            ("cryCount",),
        )
    )


def _published_at(item: dict) -> str | None:
    return item.get("publishedAt") or item.get("createdAt")


def _latest_version(versions: list[dict]) -> dict:
    if not versions:
        return {}
    dated = [version for version in versions if _published_at(version)]
    return max(dated, key=lambda version: str(_published_at(version))) if dated else versions[0]


def _cover_image_url(latest: dict, versions: list[dict]) -> str | None:
    ordered_versions = [latest, *(version for version in versions if version is not latest)]
    for version in ordered_versions:
        for image in version.get("images") or []:
            url = image.get("url") if isinstance(image, dict) else None
            if isinstance(url, str) and urlparse(url).scheme in {"http", "https"}:
                return url
    return None


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


def _normalize_model(item: dict, snapshot_id: int, base_url: str) -> tuple[dict, list[dict]]:
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
        "page_url": build_model_page_url(base_url, model_id),
        "latest_version_id": safe_int(latest.get("id")) or None,
        "latest_version_name": latest.get("name"),
        "base_model": latest.get("baseModel"),
        "published_at": _published_at(item) or _published_at(latest),
        "cover_image_url": _cover_image_url(latest, versions),
        "download_count": safe_int(_first_stat(stats, "downloadCount", "download_count")),
        "reaction_count": _reaction_count(stats),
        "collected_count": safe_optional_int(
            _first_stat(stats, "collectedCount", "collected_count", default=None)
        ),
        "comment_count": safe_int(_first_stat(stats, "commentCount", "comment_count")),
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
                "published_at": _published_at(version),
                "download_count": safe_int(
                    _first_stat(version_stats, "downloadCount", "download_count")
                ),
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


def _quality_status(models: list[dict], metadata: dict, warnings: list[str]) -> str:
    if not models:
        return "warning"
    extra_statuses = {
        metadata.get("collection_metric_status"),
        metadata.get("creator_profile_status"),
    }
    if metadata.get("minor_discovery_enabled"):
        extra_statuses.add(metadata.get("minor_discovery_status"))
    if warnings or extra_statuses & {"partial", "failed", "unavailable"}:
        return "partial"
    return "good"


def _insert_snapshot_quality(
    connection,
    snapshot_id: int,
    quality_status: str,
    metadata: dict,
    warnings: list[str],
    info: list[str],
) -> None:
    _insert_dict(
        connection,
        "snapshot_quality",
        {
            "snapshot_id": snapshot_id,
            "quality_status": quality_status,
            "rest_model_count": safe_int(metadata.get("rest_model_count")),
            "api_page_count": safe_int(metadata.get("api_page_count")),
            "minor_discovery_enabled": int(bool(metadata.get("minor_discovery_enabled"))),
            "minor_discovery_status": metadata.get("minor_discovery_status"),
            "minor_model_count": safe_int(metadata.get("minor_model_count")),
            "collection_metric_status": metadata.get("collection_metric_status"),
            "collection_metric_count": safe_int(metadata.get("collection_metric_count")),
            "creator_profile_status": metadata.get("creator_profile_status"),
            "follower_count_available": int(bool(metadata.get("follower_count_available"))),
            "warning_count": len(warnings),
            "warnings_json": json.dumps(warnings, ensure_ascii=True),
            "info_json": json.dumps(info, ensure_ascii=True),
            "created_at": utc_now(),
        },
    )


def _record_failed_snapshot(error: str, source: str) -> None:
    config = get_config()
    now = utc_now()
    with transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO snapshot "
            "(checked_at, username, source, model_type_filter, api_ok, error, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?, ?)",
            (now, config.username, source, config.model_type_filter, error, now),
        )
        _insert_snapshot_quality(
            connection,
            cursor.lastrowid,
            "failed",
            {
                "minor_discovery_enabled": config.include_minor,
                "minor_discovery_status": "failed",
                "collection_metric_status": "failed",
                "creator_profile_status": "failed",
            },
            [error],
            [],
        )
        insert_sync_log("error", error, connection)
        insert_alert(
            "error",
            "snapshot_failed",
            "Snapshot failed",
            error,
            username=config.username,
            respect_preferences=True,
            connection=connection,
        )


def take_snapshot(
    source: str = "manual", note: str | None = None, note_type: str | None = None
) -> dict:
    config = get_config()
    note = clean_note(note)
    note_type = clean_note_type(note_type)
    if not config.api_key:
        error = "API key is missing. Add CIVITAI_API_KEY to .env, restart the app, then try again."
        insert_sync_log("error", error)
        insert_alert("error", "snapshot_failed", "Snapshot failed", error, respect_preferences=True)
        return {"ok": False, "error": error, "warnings": [], "info": []}
    if not config.username:
        error = "Username is missing. Add CIVITAI_USERNAME to .env, restart the app, then try again."
        insert_sync_log("error", error)
        insert_alert("error", "snapshot_failed", "Snapshot failed", error, respect_preferences=True)
        return {"ok": False, "error": error, "warnings": [], "info": []}

    client = CivitaiClient(config)
    warnings: list[str] = []
    try:
        models, info, fetch_warnings, metadata = client.fetch_models(
            config.username, config.model_types
        )
        warnings.extend(fetch_warnings)
    except CivitaiError as exc:
        error = str(exc)
        _record_failed_snapshot(error, source)
        return {"ok": False, "error": error, "warnings": [], "info": []}

    creator = None
    try:
        creator = client.fetch_creator(config.username)
    except CivitaiError:
        warnings.append("Creator profile stats were unavailable. Model snapshot was still saved.")
        metadata["creator_profile_status"] = "failed"
    else:
        metadata["creator_profile_status"] = "success" if creator else "unavailable"
    follower_count = None
    if creator:
        follower_value = creator.get("followerCount", creator.get("follower_count"))
        follower_count = safe_int(follower_value) if follower_value is not None else None
    metadata["follower_count_available"] = follower_count is not None
    if not models:
        warnings.append("No models returned. Check the username or model type filter.")

    checked_at = utc_now()
    with transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO snapshot "
            "(checked_at, username, source, model_type_filter, api_ok, raw_total_item, note_type, note, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)",
            (
                checked_at,
                config.username,
                source,
                config.model_type_filter,
                len(models),
                note_type,
                note,
                checked_at,
            ),
        )
        snapshot_id = cursor.lastrowid
        normalized_models = []
        version_rows = []
        for item in models:
            model_row, rows = _normalize_model(item, snapshot_id, config.base_url)
            if model_row["model_id"]:
                normalized_models.append(model_row)
                version_rows.extend(rows)
        summary = {
            "model_count": len(normalized_models),
            "follower_count": follower_count,
            "total_download_count": sum(row["download_count"] for row in normalized_models),
            "total_reaction_count": sum(row["reaction_count"] for row in normalized_models),
            "total_collected_count": (
                sum(row["collected_count"] for row in normalized_models)
                if all(row["collected_count"] is not None for row in normalized_models)
                else None
            ),
            "total_comment_count": sum(row["comment_count"] for row in normalized_models),
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
        quality_status = _quality_status(normalized_models, metadata, warnings)
        _insert_snapshot_quality(
            connection, snapshot_id, quality_status, metadata, warnings, info
        )
        for message in info:
            insert_sync_log("info", message, connection)
        for warning in warnings:
            insert_sync_log("warning", warning, connection)
        alert_count = generate_snapshot_alerts(
            connection, snapshot_id, config.username, warnings
        )
        insert_sync_log(
            "info",
            f"Snapshot {snapshot_id} saved: {len(normalized_models)} models and "
            f"{len(version_rows)} versions. Generated {alert_count} local alerts.",
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
        "alert_count": alert_count,
        "quality_status": quality_status,
    }


def delete_snapshot(snapshot_id: int) -> dict:
    config = get_config()
    with transaction() as connection:
        snapshot = connection.execute(
            "SELECT id FROM snapshot WHERE id = ? AND username = ? AND api_ok = 1",
            (snapshot_id, config.username),
        ).fetchone()
        if not snapshot:
            raise ValueError("Snapshot could not be found.")
        deleted_alerts = connection.execute(
            "DELETE FROM local_alert WHERE snapshot_id = ?", (snapshot_id,)
        ).rowcount
        connection.execute("DELETE FROM snapshot_quality WHERE snapshot_id = ?", (snapshot_id,))
        deleted_versions = connection.execute(
            "DELETE FROM model_version_snapshot WHERE snapshot_id = ?", (snapshot_id,)
        ).rowcount
        deleted_models = connection.execute(
            "DELETE FROM model_snapshot WHERE snapshot_id = ?", (snapshot_id,)
        ).rowcount
        connection.execute("DELETE FROM account_snapshot WHERE snapshot_id = ?", (snapshot_id,))
        connection.execute("DELETE FROM snapshot WHERE id = ?", (snapshot_id,))
        insert_sync_log(
            "info",
            f"Snapshot {snapshot_id} deleted: {deleted_models} models and "
            f"{deleted_versions} versions and {deleted_alerts} local alerts removed.",
            connection,
        )
    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "deleted_models": deleted_models,
        "deleted_versions": deleted_versions,
        "deleted_alerts": deleted_alerts,
    }
