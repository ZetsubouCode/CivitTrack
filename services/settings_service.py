import json

from .db import create_connection, utc_now


ALERT_SETTING_KEY = "alert_preferences"
DEFAULT_ALERT_SETTINGS = {
    "enabled": {
        "new_model": True,
        "missing_model": True,
        "new_version": True,
        "download_milestone": True,
        "generation_support_changed": True,
        "download_velocity_spike": True,
        "snapshot_warning": True,
        "snapshot_failed": True,
    },
    "download_milestones": [
        100, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000
    ],
    "minimum_download_gain_alert": 10,
    "minimum_collection_gain_alert": 5,
    "velocity_spike_multiplier": 2.0,
    "velocity_minimum_current_delta": 10,
    "velocity_minimum_previous_delta": 5,
}


def get_app_setting(key: str, default=None, connection=None):
    owns_connection = connection is None
    connection = connection or create_connection()
    try:
        row = connection.execute("SELECT value FROM app_setting WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default
    finally:
        if owns_connection:
            connection.close()


def set_app_setting(key: str, value: str, connection=None) -> None:
    owns_connection = connection is None
    connection = connection or create_connection()
    try:
        connection.execute(
            "INSERT INTO app_setting (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, utc_now()),
        )
        if owns_connection:
            connection.commit()
    finally:
        if owns_connection:
            connection.close()


def _positive_int(name: str, value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be at least 1.")
    return parsed


def _positive_float(name: str, value) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number.") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than 0.")
    return parsed


def get_alert_settings(connection=None) -> dict:
    settings = json.loads(json.dumps(DEFAULT_ALERT_SETTINGS))
    raw = get_app_setting(ALERT_SETTING_KEY, connection=connection)
    if not raw:
        return settings
    try:
        stored = json.loads(raw)
    except (TypeError, ValueError):
        return settings
    if not isinstance(stored, dict):
        return settings
    if isinstance(stored.get("enabled"), dict):
        for key in settings["enabled"]:
            if isinstance(stored["enabled"].get(key), bool):
                settings["enabled"][key] = stored["enabled"][key]
    for key in (
        "download_milestones",
        "minimum_download_gain_alert",
        "minimum_collection_gain_alert",
        "velocity_spike_multiplier",
        "velocity_minimum_current_delta",
        "velocity_minimum_previous_delta",
    ):
        if key in stored:
            settings[key] = stored[key]
    return settings


def update_alert_settings(payload, connection=None) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Alert settings request must be a JSON object.")
    enabled = payload.get("enabled")
    if not isinstance(enabled, dict):
        raise ValueError("enabled must be an object.")
    unknown = set(enabled) - set(DEFAULT_ALERT_SETTINGS["enabled"])
    if unknown:
        raise ValueError(f"Unknown alert type: {sorted(unknown)[0]}.")
    normalized_enabled = {}
    for key in DEFAULT_ALERT_SETTINGS["enabled"]:
        value = enabled.get(key, DEFAULT_ALERT_SETTINGS["enabled"][key])
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false.")
        normalized_enabled[key] = value

    milestones = payload.get("download_milestones", DEFAULT_ALERT_SETTINGS["download_milestones"])
    if isinstance(milestones, str):
        milestones = [item.strip() for item in milestones.split(",") if item.strip()]
    if not isinstance(milestones, list):
        raise ValueError("download_milestones must be a list or comma-separated string.")
    normalized = {
        "enabled": normalized_enabled,
        "download_milestones": sorted(set(_positive_int("download_milestones", item) for item in milestones)),
        "minimum_download_gain_alert": _positive_int(
            "minimum_download_gain_alert",
            payload.get("minimum_download_gain_alert", DEFAULT_ALERT_SETTINGS["minimum_download_gain_alert"]),
        ),
        "minimum_collection_gain_alert": _positive_int(
            "minimum_collection_gain_alert",
            payload.get("minimum_collection_gain_alert", DEFAULT_ALERT_SETTINGS["minimum_collection_gain_alert"]),
        ),
        "velocity_spike_multiplier": _positive_float(
            "velocity_spike_multiplier",
            payload.get("velocity_spike_multiplier", DEFAULT_ALERT_SETTINGS["velocity_spike_multiplier"]),
        ),
        "velocity_minimum_current_delta": _positive_int(
            "velocity_minimum_current_delta",
            payload.get("velocity_minimum_current_delta", DEFAULT_ALERT_SETTINGS["velocity_minimum_current_delta"]),
        ),
        "velocity_minimum_previous_delta": _positive_int(
            "velocity_minimum_previous_delta",
            payload.get("velocity_minimum_previous_delta", DEFAULT_ALERT_SETTINGS["velocity_minimum_previous_delta"]),
        ),
    }
    if not normalized["download_milestones"]:
        raise ValueError("download_milestones must include at least one threshold.")
    set_app_setting(ALERT_SETTING_KEY, json.dumps(normalized, separators=(",", ":")), connection)
    return normalized
