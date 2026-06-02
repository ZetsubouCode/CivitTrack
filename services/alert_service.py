from datetime import datetime
import json

from .config import get_config
from .db import create_connection, dict_rows, utc_now
from .settings_service import get_alert_settings


def insert_alert(
    level: str,
    alert_type: str,
    title: str,
    message: str,
    *,
    username: str | None = None,
    snapshot_id: int | None = None,
    model_id: int | None = None,
    respect_preferences: bool = False,
    connection=None,
) -> bool:
    owns_connection = connection is None
    connection = connection or create_connection()
    if respect_preferences and not get_alert_settings(connection)["enabled"].get(alert_type, True):
        if owns_connection:
            connection.close()
        return False
    connection.execute(
        "INSERT INTO local_alert "
        "(created_at, username, snapshot_id, level, alert_type, title, message, model_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            utc_now(),
            username if username is not None else get_config().username,
            snapshot_id,
            level.lower(),
            alert_type,
            title,
            message,
            model_id,
        ),
    )
    if owns_connection:
        connection.commit()
        connection.close()
    return True


def _model_rows(connection, snapshot_id: int) -> dict[int, dict]:
    return {
        row["model_id"]: dict(row)
        for row in connection.execute(
            "SELECT model_id, model_name, download_count, collected_count, raw_json "
            "FROM model_snapshot WHERE snapshot_id = ?",
            (snapshot_id,),
        )
    }


def _version_rows(connection, snapshot_id: int) -> dict[int, dict]:
    return {
        row["model_version_id"]: dict(row)
        for row in connection.execute(
            "SELECT model_id, model_name, model_version_id, version_name "
            "FROM model_version_snapshot WHERE snapshot_id = ?",
            (snapshot_id,),
        )
    }


def _supports_generation(row: dict) -> bool | None:
    try:
        value = json.loads(row.get("raw_json") or "{}").get("supportsGeneration")
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, bool) else None


def _largest_crossed_milestone(old_value: int, new_value: int, milestones: list[int]) -> int | None:
    crossed = [value for value in milestones if old_value < value <= new_value]
    return crossed[-1] if crossed else None


def _minutes_between(start: str, end: str) -> float:
    return max(0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() / 60)


def _create_model_change_alerts(
    connection,
    username: str,
    snapshot_id: int,
    current_snapshot: dict,
    previous_snapshots: list[dict],
    settings: dict,
) -> int:
    previous_snapshot = previous_snapshots[0]
    current_models = _model_rows(connection, snapshot_id)
    previous_models = _model_rows(connection, previous_snapshot["id"])
    older_models = (
        _model_rows(connection, previous_snapshots[1]["id"])
        if len(previous_snapshots) > 1
        else {}
    )
    created = 0

    for model_id in sorted(current_models.keys() - previous_models.keys()):
        model = current_models[model_id]
        if not settings["enabled"]["new_model"]:
            continue
        insert_alert(
            "info",
            "new_model",
            "New model detected",
            f"{model['model_name']} appeared with {model['download_count']:,} downloads.",
            username=username,
            snapshot_id=snapshot_id,
            model_id=model_id,
            connection=connection,
        )
        created += 1

    for model_id in sorted(previous_models.keys() - current_models.keys()):
        model = previous_models[model_id]
        if not settings["enabled"]["missing_model"]:
            continue
        insert_alert(
            "warning",
            "missing_model",
            "Model missing from API response",
            f"{model['model_name']} was present in the previous snapshot but is no longer returned.",
            username=username,
            snapshot_id=snapshot_id,
            model_id=model_id,
            connection=connection,
        )
        created += 1

    current_minutes = _minutes_between(previous_snapshot["checked_at"], current_snapshot["checked_at"])
    older_minutes = (
        _minutes_between(previous_snapshots[1]["checked_at"], previous_snapshot["checked_at"])
        if len(previous_snapshots) > 1
        else 0
    )
    for model_id in sorted(current_models.keys() & previous_models.keys()):
        current = current_models[model_id]
        previous = previous_models[model_id]
        milestone = _largest_crossed_milestone(
            previous["download_count"], current["download_count"], settings["download_milestones"]
        )
        if milestone and settings["enabled"]["download_milestone"]:
            insert_alert(
                "success",
                "download_milestone",
                "Download milestone reached",
                f"{current['model_name']} crossed {milestone:,} downloads.",
                username=username,
                snapshot_id=snapshot_id,
                model_id=model_id,
                connection=connection,
            )
            created += 1

        previous_support = _supports_generation(previous)
        current_support = _supports_generation(current)
        if (
            settings["enabled"]["generation_support_changed"]
            and
            previous_support is not None
            and current_support is not None
            and previous_support != current_support
        ):
            state = "enabled" if current_support else "disabled"
            insert_alert(
                "info" if current_support else "warning",
                "generation_support_changed",
                "Generation support changed",
                f"On-site generation was {state} for {current['model_name']}.",
                username=username,
                snapshot_id=snapshot_id,
                model_id=model_id,
                connection=connection,
            )
            created += 1

        download_delta = current["download_count"] - previous["download_count"]
        if download_delta >= settings["minimum_download_gain_alert"]:
            insert_alert(
                "success",
                "download_growth",
                "Download growth detected",
                f"{current['model_name']} gained {download_delta:,} downloads since the previous snapshot.",
                username=username,
                snapshot_id=snapshot_id,
                model_id=model_id,
                connection=connection,
            )
            created += 1
        if (
            current["collected_count"] is not None
            and previous["collected_count"] is not None
            and current["collected_count"] - previous["collected_count"]
            >= settings["minimum_collection_gain_alert"]
        ):
            collection_delta = current["collected_count"] - previous["collected_count"]
            insert_alert(
                "success",
                "collection_growth",
                "Collection growth detected",
                f"{current['model_name']} was added to {collection_delta:,} collections since the previous snapshot.",
                username=username,
                snapshot_id=snapshot_id,
                model_id=model_id,
                connection=connection,
            )
            created += 1

        older = older_models.get(model_id)
        if not older or not current_minutes or not older_minutes:
            continue
        current_delta = download_delta
        previous_delta = previous["download_count"] - older["download_count"]
        current_rate = current_delta / current_minutes
        previous_rate = previous_delta / older_minutes
        if (
            settings["enabled"]["download_velocity_spike"]
            and current_delta >= settings["velocity_minimum_current_delta"]
            and previous_delta >= settings["velocity_minimum_previous_delta"]
            and previous_rate > 0
            and current_rate >= previous_rate * settings["velocity_spike_multiplier"]
        ):
            insert_alert(
                "success",
                "download_velocity_spike",
                "Download velocity increased",
                f"{current['model_name']} download velocity is {current_rate / previous_rate:.1f}x "
                "the preceding snapshot interval.",
                username=username,
                snapshot_id=snapshot_id,
                model_id=model_id,
                connection=connection,
            )
            created += 1
    return created


def _create_version_alerts(
    connection, username: str, snapshot_id: int, previous_snapshot_id: int, settings: dict
) -> int:
    if not settings["enabled"]["new_version"]:
        return 0
    current_versions = _version_rows(connection, snapshot_id)
    previous_versions = _version_rows(connection, previous_snapshot_id)
    previous_model_ids = set(_model_rows(connection, previous_snapshot_id))
    created = 0
    for version_id in sorted(current_versions.keys() - previous_versions.keys()):
        version = current_versions[version_id]
        if version["model_id"] not in previous_model_ids:
            continue
        name = version["version_name"] or f"Version {version_id}"
        insert_alert(
            "info",
            "new_version",
            "New model version detected",
            f"{version['model_name']} added version {name}.",
            username=username,
            snapshot_id=snapshot_id,
            model_id=version["model_id"],
            connection=connection,
        )
        created += 1
    return created


def generate_snapshot_alerts(
    connection, snapshot_id: int, username: str, warnings: list[str]
) -> int:
    settings = get_alert_settings(connection)
    current_snapshot = dict(
        connection.execute(
            "SELECT id, checked_at FROM snapshot WHERE id = ?", (snapshot_id,)
        ).fetchone()
    )
    previous_snapshots = [
        dict(row)
        for row in connection.execute(
            "SELECT id, checked_at FROM snapshot "
            "WHERE username = ? AND api_ok = 1 AND id <> ? "
            "ORDER BY checked_at DESC, id DESC LIMIT 2",
            (username, snapshot_id),
        )
    ]
    created = 0
    if previous_snapshots:
        created += _create_model_change_alerts(
            connection, username, snapshot_id, current_snapshot, previous_snapshots, settings
        )
        created += _create_version_alerts(
            connection, username, snapshot_id, previous_snapshots[0]["id"], settings
        )
    for warning in warnings if settings["enabled"]["snapshot_warning"] else []:
        insert_alert(
            "warning",
            "snapshot_warning",
            "Snapshot completed with warning",
            warning,
            username=username,
            snapshot_id=snapshot_id,
            connection=connection,
        )
        created += 1
    return created


def list_alerts(username: str | None = None, limit: int = 100) -> dict:
    username = username if username is not None else get_config().username
    limit = min(max(1, limit), 250)
    config = get_config()
    with create_connection() as connection:
        alerts = dict_rows(
            connection.execute(
                "SELECT id, created_at, snapshot_id, level, alert_type, title, message, "
                "model_id, is_read FROM local_alert WHERE username = ? "
                "ORDER BY id DESC LIMIT ?",
                (username, limit),
            )
        )
        unread_count = connection.execute(
            "SELECT COUNT(*) FROM local_alert WHERE username = ? AND is_read = 0",
            (username,),
        ).fetchone()[0]
    for alert in alerts:
        alert["page_url"] = config.model_page_url(alert["model_id"]) if alert["model_id"] else None
    return {"alerts": alerts, "unread_count": unread_count}


def mark_alert_read(alert_id: int, username: str | None = None) -> dict:
    username = username if username is not None else get_config().username
    with create_connection() as connection:
        cursor = connection.execute(
            "UPDATE local_alert SET is_read = 1 WHERE id = ? AND username = ?",
            (alert_id, username),
        )
        if not cursor.rowcount:
            raise ValueError("Alert could not be found.")
        connection.commit()
    return {"ok": True, "alert_id": alert_id}


def mark_all_alerts_read(username: str | None = None) -> dict:
    username = username if username is not None else get_config().username
    with create_connection() as connection:
        cursor = connection.execute(
            "UPDATE local_alert SET is_read = 1 WHERE username = ? AND is_read = 0",
            (username,),
        )
        connection.commit()
    return {"ok": True, "updated": cursor.rowcount}
