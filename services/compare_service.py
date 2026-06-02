from datetime import datetime, timezone

from .config import get_config
from .db import create_connection, dict_rows


ACCOUNT_METRICS = (
    "total_download_count",
    "total_reaction_count",
    "total_collected_count",
    "total_comment_count",
)
MODEL_METRICS = (
    "download_count",
    "reaction_count",
    "collected_count",
    "comment_count",
)


def list_snapshots(username: str | None = None) -> list[dict]:
    username = username or get_config().username
    with create_connection() as connection:
        return dict_rows(
            connection.execute(
                "SELECT s.id, s.checked_at, s.source, s.model_type_filter, s.raw_total_item, "
                "s.note_type, s.note, q.quality_status, q.warning_count, "
                "a.model_count, a.follower_count, a.total_download_count, "
                "a.total_reaction_count, a.total_collected_count, a.total_comment_count "
                "FROM snapshot s JOIN account_snapshot a ON a.snapshot_id = s.id "
                "LEFT JOIN snapshot_quality q ON q.snapshot_id = s.id "
                "WHERE s.username = ? AND s.api_ok = 1 ORDER BY s.checked_at DESC, s.id DESC",
                (username,),
            )
        )


def get_latest_breakdown(username: str | None = None) -> dict:
    config = get_config()
    username = username or config.username
    snapshots = list_snapshots(username)
    if not snapshots:
        return {"snapshot": None, "totals": None, "models": []}
    snapshot = snapshots[0]
    with create_connection() as connection:
        models = dict_rows(
            connection.execute(
                "SELECT model_id, model_name, model_type, page_url, base_model, "
                "latest_version_name, published_at, download_count, reaction_count, collected_count, "
                "comment_count FROM model_snapshot "
                "WHERE snapshot_id = ? "
                "ORDER BY download_count DESC, reaction_count DESC, model_name ASC",
                (snapshot["id"],),
            )
        )
    for model in models:
        model["page_url"] = config.model_page_url(model["model_id"])
    return {"snapshot": snapshot, "totals": snapshot, "models": models}


def _load_snapshot(connection, snapshot_id: int) -> dict | None:
    row = connection.execute(
        "SELECT s.id, s.checked_at, s.username, s.source, s.note_type, s.note, a.* FROM snapshot s "
        "JOIN account_snapshot a ON a.snapshot_id = s.id WHERE s.id = ? AND s.api_ok = 1",
        (snapshot_id,),
    ).fetchone()
    return dict(row) if row else None


def _delta(old, new):
    return (new or 0) - (old or 0)


def _optional_delta(old, new):
    return new - old if old is not None and new is not None else None


def compare_snapshots(from_id: int, to_id: int) -> dict:
    config = get_config()
    with create_connection() as connection:
        old_account = _load_snapshot(connection, from_id)
        new_account = _load_snapshot(connection, to_id)
        if not old_account or not new_account:
            raise ValueError("One or both snapshots could not be found.")
        if old_account["username"] != new_account["username"]:
            raise ValueError("Snapshots must belong to the same username.")
        old_models = {
            row["model_id"]: dict(row)
            for row in connection.execute(
                "SELECT * FROM model_snapshot WHERE snapshot_id = ?", (from_id,)
            )
        }
        new_models = {
            row["model_id"]: dict(row)
            for row in connection.execute(
                "SELECT * FROM model_snapshot WHERE snapshot_id = ?", (to_id,)
            )
        }
        models = []
        missing_models = []
        for model_id in sorted(old_models.keys() | new_models.keys()):
            old = old_models.get(model_id)
            new = new_models.get(model_id)
            current = new or old
            status = "normal" if old and new else "new_in_current" if new else "missing_in_current"
            row = {
                "model_id": model_id,
                "model_name": current["model_name"],
                "model_type": current["model_type"],
                "page_url": config.model_page_url(model_id),
                "base_model": current["base_model"],
                "latest_version_name": current["latest_version_name"],
                "published_at": current["published_at"],
                "status": status,
            }
            for metric in MODEL_METRICS:
                row[f"old_{metric}"] = old[metric] if old else (
                    None if metric == "collected_count" else 0
                )
                row[f"new_{metric}"] = new[metric] if new else None
                if metric == "collected_count":
                    row[f"{metric}_delta"] = (
                        _optional_delta(old[metric] if old else None, new[metric]) if new else None
                    )
                else:
                    row[f"{metric}_delta"] = (
                        _delta(old[metric] if old else 0, new[metric] if new else 0) if new else 0
                    )
            (missing_models if status == "missing_in_current" else models).append(row)

        models.sort(
            key=lambda row: (
                row["download_count_delta"],
                row["reaction_count_delta"],
                row["collected_count_delta"] or 0,
                row["comment_count_delta"],
            ),
            reverse=True,
        )
        old_versions = {
            (row["model_id"], row["model_version_id"]): dict(row)
            for row in connection.execute(
                "SELECT * FROM model_version_snapshot WHERE snapshot_id = ?", (from_id,)
            )
        }
        new_versions = {
            (row["model_id"], row["model_version_id"]): dict(row)
            for row in connection.execute(
                "SELECT * FROM model_version_snapshot WHERE snapshot_id = ?", (to_id,)
            )
        }
        versions = []
        model_download_deltas = {
            row["model_id"]: row["download_count_delta"] for row in models
        }
        for version_key in sorted(old_versions.keys() | new_versions.keys()):
            old = old_versions.get(version_key)
            new = new_versions.get(version_key)
            current = new or old
            model_download_delta = model_download_deltas.get(current["model_id"])
            version_download_delta = (
                _delta(old["download_count"] if old else 0, new["download_count"] if new else 0)
                if new
                else 0
            )
            status = "normal" if old and new else "new_in_current" if new else "missing_in_current"
            versions.append(
                {
                    "model_id": current["model_id"],
                    "model_name": current["model_name"],
                    "model_version_id": current["model_version_id"],
                    "version_name": current["version_name"],
                    "base_model": current["base_model"],
                    "old_download_count": old["download_count"] if old else 0,
                    "new_download_count": new["download_count"] if new else None,
                    "download_count_delta": version_download_delta,
                    "model_download_delta": model_download_delta,
                    "version_contribution_percent": (
                        round(version_download_delta / model_download_delta * 100, 1)
                        if model_download_delta and model_download_delta > 0
                        else None
                    ),
                    "status": status,
                }
            )
        versions.sort(key=lambda row: row["download_count_delta"], reverse=True)

    start = datetime.fromisoformat(old_account["checked_at"])
    end = datetime.fromisoformat(new_account["checked_at"])
    summary = {
        "from_checked_at": old_account["checked_at"],
        "to_checked_at": new_account["checked_at"],
        "minutes_between": round((end - start).total_seconds() / 60, 1),
        "model_count_delta": _delta(old_account["model_count"], new_account["model_count"]),
        "total_follower_delta": (
            _delta(old_account["follower_count"], new_account["follower_count"])
            if old_account["follower_count"] is not None
            and new_account["follower_count"] is not None
            else None
        ),
    }
    for metric in ACCOUNT_METRICS:
        summary[f"{metric}_delta"] = (
            _optional_delta(old_account[metric], new_account[metric])
            if metric == "total_collected_count"
            else _delta(old_account[metric], new_account[metric])
        )
    return {
        "from_id": from_id,
        "to_id": to_id,
        "from_totals": old_account,
        "to_totals": new_account,
        "summary": summary,
        "from_context": {
            "checked_at": old_account["checked_at"],
            "source": old_account["source"],
            "note_type": old_account["note_type"],
            "note": old_account["note"],
        },
        "to_context": {
            "checked_at": new_account["checked_at"],
            "source": new_account["source"],
            "note_type": new_account["note_type"],
            "note": new_account["note"],
        },
        "models": models,
        "missing_models": missing_models,
        "versions": versions,
    }


def compare_latest_previous(username: str | None = None) -> dict:
    snapshots = list_snapshots(username)
    if len(snapshots) < 2:
        raise ValueError("Need at least 2 snapshots before comparing.")
    return compare_snapshots(snapshots[1]["id"], snapshots[0]["id"])


def _nearest_snapshot_id(dt: str, username: str) -> int:
    try:
        parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Datetime must be a valid ISO date and time.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    normalized = parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")
    with create_connection() as connection:
        row = connection.execute(
            "SELECT id FROM snapshot WHERE username = ? AND api_ok = 1 AND checked_at <= ? "
            "ORDER BY checked_at DESC, id DESC LIMIT 1",
            (username, normalized),
        ).fetchone()
    if not row:
        raise ValueError("No snapshot exists at or before the selected datetime.")
    return row["id"]


def compare_by_datetime(from_dt: str, to_dt: str, username: str | None = None) -> dict:
    username = username or get_config().username
    return compare_snapshots(
        _nearest_snapshot_id(from_dt, username), _nearest_snapshot_id(to_dt, username)
    )


def get_model_history(model_id: int) -> dict:
    config = get_config()
    with create_connection() as connection:
        rows = dict_rows(
            connection.execute(
                "SELECT s.checked_at, m.model_id, m.model_name, m.page_url, "
                "m.latest_version_name, m.cover_image_url, m.download_count, m.reaction_count, "
                "m.collected_count, m.comment_count FROM model_snapshot m "
                "JOIN snapshot s ON s.id = m.snapshot_id WHERE m.model_id = ? "
                "ORDER BY s.checked_at ASC, s.id ASC",
                (model_id,),
            )
        )
    if not rows:
        raise ValueError("Model history could not be found.")
    for row in rows:
        row["page_url"] = config.model_page_url(model_id)
    return {"model": rows[-1], "history": rows}
