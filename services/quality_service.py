import json

from .config import get_config
from .db import create_connection


def get_snapshot_quality(snapshot_id: int, username: str | None = None) -> dict:
    username = username if username is not None else get_config().username
    with create_connection() as connection:
        snapshot = connection.execute(
            "SELECT id, checked_at, source, note_type, note FROM snapshot "
            "WHERE id = ? AND username = ? AND api_ok = 1",
            (snapshot_id, username),
        ).fetchone()
        if not snapshot:
            raise ValueError("Snapshot could not be found.")
        quality = connection.execute(
            "SELECT quality_status, rest_model_count, api_page_count, minor_discovery_enabled, "
            "minor_discovery_status, minor_model_count, collection_metric_status, "
            "collection_metric_count, generation_metric_status, generation_metric_count, "
            "creator_profile_status, follower_count_available, "
            "warning_count, warnings_json, info_json FROM snapshot_quality WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    result = {"snapshot": dict(snapshot), "quality": dict(quality) if quality else None}
    if result["quality"]:
        result["quality"]["warnings"] = json.loads(result["quality"].pop("warnings_json") or "[]")
        result["quality"]["info"] = json.loads(result["quality"].pop("info_json") or "[]")
    return result
