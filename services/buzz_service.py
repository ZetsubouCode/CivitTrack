from copy import deepcopy
import hashlib
import json
from urllib.parse import urlparse

from .alert_service import insert_alert
from .buzz_client import BuzzClient, BuzzClientError
from .config import get_config
from .db import create_connection, dict_rows, insert_sync_log, transaction, utc_now
from .settings_service import get_alert_settings, get_app_setting, set_app_setting


ACCOUNT_TYPES = ("Blue", "Yellow", "Green")
DEFAULT_BUZZ_SETTINGS = {
    "buzz_tracking_enabled": False,
    "buzz_track_blue": True,
    "buzz_track_yellow": True,
    "buzz_track_green": False,
    "buzz_transaction_limit": 200,
}
SENSITIVE_FIELDS = {
    "email", "payment", "card", "customer", "stripe", "token", "secret", "apikey",
    "authorization",
}
UNAVAILABLE_MESSAGE = (
    "Buzz tracking is unavailable. Your API key may not have BuzzRead access, "
    "or CivitAI changed the endpoint."
)


def _bool_setting(key: str, default: bool, connection=None) -> bool:
    value = get_app_setting(key, str(default).lower(), connection)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _safe_optional_int(value) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, dict):
        value = value.get("value", value.get("amount"))
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value, default=None) -> str | None:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return default
    text = str(value).strip()
    return text or default


def _normalize_key(value: str) -> str:
    return "".join(char for char in str(value).lower() if char.isalnum())


def _deep_find(payload, *names):
    expected = {_normalize_key(name) for name in names}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if _normalize_key(key) in expected and value is not None:
                return value
        for value in payload.values():
            found = _deep_find(value, *names)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _deep_find(value, *names)
            if found is not None:
                return found
    return None


def _sanitized(payload):
    if isinstance(payload, dict):
        return {
            key: _sanitized(value)
            for key, value in payload.items()
            if not any(fragment in _normalize_key(key) for fragment in SENSITIVE_FIELDS)
        }
    if isinstance(payload, list):
        return [_sanitized(value) for value in payload[:500]]
    return payload


def _json(payload) -> str:
    return json.dumps(_sanitized(deepcopy(payload)), ensure_ascii=True, separators=(",", ":"))


def _http_url(value) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    return text if urlparse(text).scheme in {"http", "https"} else None


def get_buzz_settings(connection=None) -> dict:
    settings = {
        "enabled": _bool_setting("buzz_tracking_enabled", False, connection),
        "account_types": {
            "Blue": _bool_setting("buzz_track_blue", True, connection),
            "Yellow": _bool_setting("buzz_track_yellow", True, connection),
            "Green": _bool_setting("buzz_track_green", False, connection),
        },
    }
    try:
        limit = int(get_app_setting("buzz_transaction_limit", "200", connection))
    except (TypeError, ValueError):
        limit = 200
    settings["transaction_limit"] = min(500, max(20, limit))
    settings["experimental"] = True
    settings["selected_account_types"] = [
        name for name, enabled in settings["account_types"].items() if enabled
    ]
    return settings


def update_buzz_settings(payload) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Buzz settings request must be a JSON object.")
    enabled = payload.get("enabled", False)
    account_types = payload.get("account_types")
    if not isinstance(enabled, bool):
        raise ValueError("enabled must be true or false.")
    if not isinstance(account_types, dict):
        raise ValueError("account_types must be an object.")
    normalized_types = {}
    for name in ACCOUNT_TYPES:
        value = account_types.get(name)
        if not isinstance(value, bool):
            raise ValueError(f"{name} Buzz setting must be true or false.")
        normalized_types[name] = value
    try:
        limit = int(payload.get("transaction_limit", 200))
    except (TypeError, ValueError) as exc:
        raise ValueError("Transaction fetch limit must be an integer.") from exc
    if not 20 <= limit <= 500:
        raise ValueError("Transaction fetch limit must be between 20 and 500.")
    with transaction() as connection:
        set_app_setting("buzz_tracking_enabled", str(enabled).lower(), connection)
        for name, value in normalized_types.items():
            set_app_setting(f"buzz_track_{name.lower()}", str(value).lower(), connection)
        set_app_setting("buzz_transaction_limit", str(limit), connection)
    return get_buzz_settings()


def _records(payload, *container_names) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for name in container_names:
        value = payload.get(name)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = _records(value, *container_names)
            if nested:
                return nested
    return []


def _has_records_shape(payload, *container_names) -> bool:
    if isinstance(payload, list):
        return True
    if not isinstance(payload, dict):
        return False
    for name in container_names:
        if name not in payload:
            continue
        value = payload[name]
        if isinstance(value, list) or _has_records_shape(value, *container_names):
            return True
    return False


def _normalize_account_type(value) -> str | None:
    text = _clean_text(value)
    if not text:
        return None
    return next((name for name in ACCOUNT_TYPES if name.casefold() == text.casefold()), None)


def _normalize_accounts(payload) -> dict[str, dict]:
    accounts = {}
    records = _records(payload, "accounts", "items", "balances", "data")
    for record in records:
        account_type = _normalize_account_type(
            _deep_find(record, "accountType", "buzzType", "type", "color", "name")
        )
        if account_type:
            accounts[account_type] = {
                "balance": _safe_optional_int(_deep_find(record, "balance", "amount", "value")),
                "raw_json": _json(record),
            }
    def collect_named_balances(value):
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            account_type = _normalize_account_type(key)
            if account_type and account_type not in accounts:
                accounts[account_type] = {
                    "balance": _safe_optional_int(
                        item.get("balance", item.get("amount", item.get("value")))
                        if isinstance(item, dict) else item
                    ),
                    "raw_json": _json({key: item}),
                }
            collect_named_balances(item)
    collect_named_balances(payload)
    return accounts


def _event_category(transaction_type: str, description: str, entity_type: str, amount: int) -> str:
    text = f"{transaction_type} {description}".casefold()
    entity = entity_type.casefold()
    is_model = "model" in entity or "model" in text
    is_image = "image" in entity or "image" in text
    if any(word in text for word in ("collection", "collected", "collect")):
        if is_model:
            return "model_collection"
        if is_image:
            return "image_collection"
    if any(word in text for word in ("reaction", "reacted", "like", "liked")):
        if is_model:
            return "model_reaction"
        if is_image:
            return "image_reaction"
    if "tip" in text:
        if any(word in text for word in ("sent", "send", "given", "outgoing")) or amount < 0:
            return "tip_sent"
        return "tip_received"
    if amount < 0 and any(word in text for word in ("generation", "generate", "imagegen")):
        return "generation_spend"
    if amount < 0 and "train" in text:
        return "training_spend"
    if amount > 0 and any(word in text for word in ("reward", "daily", "claim", "bonus")):
        return "reward"
    if amount > 0:
        return "other_gain"
    if amount < 0:
        return "other_spend"
    return "unknown"


def _latest_model(connection, model_id: int | None) -> dict | None:
    if not model_id:
        return None
    row = connection.execute(
        "SELECT m.model_name, m.page_url, m.cover_image_url, m.latest_version_name "
        "FROM model_snapshot m JOIN snapshot s ON s.id = m.snapshot_id "
        "WHERE m.model_id = ? AND s.api_ok = 1 "
        "ORDER BY s.checked_at DESC, s.id DESC LIMIT 1",
        (model_id,),
    ).fetchone()
    return dict(row) if row else None


def _transaction_key(record: dict, account_type: str, normalized: dict) -> str:
    api_id = _clean_text(
        record.get("transactionId")
        or record.get("id")
        or record.get("key")
        or _deep_find(record, "transactionId")
    )
    if api_id:
        return f"api:{api_id}"
    basis = {
        "account_type": account_type,
        "transaction_date": normalized["transaction_date"],
        "amount": normalized["amount"],
        "transaction_type": normalized["transaction_type"],
        "description": normalized["description"],
        "entity_type": normalized["entity_type"],
        "entity_id": normalized["entity_id"],
        "raw": _sanitized(record),
    }
    digest = hashlib.sha256(
        json.dumps(basis, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def _normalize_transaction(connection, record: dict, account_type: str) -> dict:
    amount = _safe_optional_int(_deep_find(record, "amount", "delta", "value")) or 0
    transaction_type = _clean_text(
        _deep_find(record, "transactionType", "activityType", "reason", "type"), "unknown"
    )
    description = _clean_text(
        _deep_find(record, "description", "message", "summary"), ""
    )
    entity_type = _clean_text(_deep_find(record, "entityType", "subjectType"), "")
    entity_id = _clean_text(_deep_find(record, "entityId", "subjectId"))
    model_id = _safe_optional_int(_deep_find(record, "modelId"))
    image_id = _safe_optional_int(_deep_find(record, "imageId"))
    if entity_id and entity_type.casefold() == "model":
        model_id = model_id or _safe_optional_int(entity_id)
    if entity_id and entity_type.casefold() == "image":
        image_id = image_id or _safe_optional_int(entity_id)
    model = _latest_model(connection, model_id)
    model_url = get_config().model_page_url(model_id) if model_id else None
    image_url = _http_url(_deep_find(record, "imageUrl", "previewUrl"))
    if not image_url and (image_id or entity_type.casefold() == "image"):
        image_url = _http_url(_deep_find(record, "url"))
    category = _event_category(transaction_type, description, entity_type, amount)
    direct_match = bool(model_id or image_id)
    normalized = {
        "account_type": account_type,
        "transaction_date": _clean_text(
            _deep_find(record, "transactionDate", "createdAt", "date", "timestamp")
        ),
        "amount": amount,
        "direction": "gained" if amount > 0 else "spent" if amount < 0 else "neutral",
        "transaction_type": transaction_type,
        "event_category": category,
        "title": _clean_text(_deep_find(record, "title"), category.replace("_", " ").title()),
        "description": description,
        "entity_type": entity_type or None,
        "entity_id": entity_id,
        "model_id": model_id,
        "model_name": (model or {}).get("model_name"),
        "model_url": model_url,
        "image_id": image_id,
        "image_url": image_url,
        "post_id": _safe_optional_int(_deep_find(record, "postId")),
        "user_id": _safe_optional_int(_deep_find(record, "userId")),
        "username": _clean_text(_deep_find(record, "username", "userName", "recipient", "sender")),
        "match_confidence": "direct" if direct_match else "unknown",
        "raw_json": _json(record),
    }
    normalized["transaction_key"] = _transaction_key(record, account_type, normalized)
    return normalized


def _resolve_image_preview(client: BuzzClient, image_id: int | None, cache=None) -> dict | None:
    if not image_id:
        return None
    cache = cache if cache is not None else {}
    if image_id in cache:
        return cache[image_id]
    fetch = getattr(client, "fetch_image_preview", None)
    preview = fetch(image_id) if callable(fetch) else None
    if not isinstance(preview, dict):
        cache[image_id] = None
        return None
    resolved = {
        "image_url": _http_url(preview.get("image_url")),
        "post_id": _safe_optional_int(preview.get("post_id")),
    }
    cache[image_id] = resolved if resolved["image_url"] or resolved["post_id"] else None
    return cache[image_id]


def _enrich_image_preview(row: dict, client: BuzzClient, cache=None) -> None:
    if not row["image_id"] or (row["image_url"] and row["post_id"]):
        return
    preview = _resolve_image_preview(client, row["image_id"], cache)
    if not preview:
        return
    row["image_url"] = row["image_url"] or preview["image_url"]
    row["post_id"] = row["post_id"] or preview["post_id"]


def _upsert_transaction(connection, row: dict, buzz_check_id: int, checked_at: str) -> bool:
    existing = connection.execute(
        "SELECT id FROM buzz_transaction WHERE transaction_key = ? AND account_type = ?",
        (row["transaction_key"], row["account_type"]),
    ).fetchone()
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    assignments = ", ".join(
        f"{column} = excluded.{column}"
        for column in row
        if column not in {"transaction_key", "account_type"}
    )
    connection.execute(
        f"INSERT INTO buzz_transaction ({columns}, first_seen_at, last_seen_at, latest_check_id) "
        f"VALUES ({placeholders}, ?, ?, ?) "
        "ON CONFLICT(transaction_key, account_type) DO UPDATE SET "
        f"{assignments}, last_seen_at = excluded.last_seen_at, latest_check_id = excluded.latest_check_id",
        (*row.values(), checked_at, checked_at, buzz_check_id),
    )
    return existing is None


def _record_failed_check(error: str, source: str, selected: list[str]) -> dict:
    config = get_config()
    now = utc_now()
    with transaction() as connection:
        previous = connection.execute(
            "SELECT api_ok FROM buzz_check WHERE username = ? ORDER BY id DESC LIMIT 1",
            (config.username,),
        ).fetchone()
        cursor = connection.execute(
            "INSERT INTO buzz_check "
            "(checked_at, username, source, api_ok, error, tracked_account_types, quality_status, "
            "warning_count, warnings_json, info_json, created_at) "
            "VALUES (?, ?, ?, 0, ?, ?, 'unavailable', 1, ?, '[]', ?)",
            (now, config.username, source, error, json.dumps(selected), json.dumps([error]), now),
        )
        insert_sync_log("warning", error, connection)
        if previous and previous["api_ok"]:
            insert_alert(
                "warning", "buzz_unavailable", "Buzz tracking unavailable", UNAVAILABLE_MESSAGE,
                username=config.username, respect_preferences=True, connection=connection,
            )
    return {
        "ok": False, "error": error, "buzz_check_id": cursor.lastrowid, "checked_at": now,
        "account_summaries": [], "new_transaction_count": 0, "warnings": [error], "info": [],
        "quality_status": "unavailable",
    }


def _create_transaction_alerts(connection, rows: list[dict], had_success: bool) -> int:
    if not had_success:
        return 0
    settings = get_alert_settings(connection)
    created = 0
    for row in rows:
        amount = row["amount"]
        if row["event_category"] == "tip_received" and settings["enabled"]["buzz_tip"]:
            username = f" from {row['username']}" if row["username"] else ""
            insert_alert(
                "success", "buzz_tip", "Buzz tip received",
                f"Received {amount:+,} {row['account_type']} Buzz{username}.",
                connection=connection,
            )
            created += 1
        elif amount >= settings["buzz_large_gain_threshold"] and settings["enabled"]["buzz_large_gain"]:
            insert_alert(
                "success", "buzz_large_gain", "Large Buzz gain detected",
                f"Received {amount:+,} {row['account_type']} Buzz: {row['description'] or row['title']}.",
                connection=connection,
            )
            created += 1
        elif amount <= -settings["buzz_large_spend_threshold"] and settings["enabled"]["buzz_large_spend"]:
            insert_alert(
                "warning", "buzz_large_spend", "Large Buzz spend detected",
                f"Spent {abs(amount):,} {row['account_type']} Buzz: {row['description'] or row['title']}.",
                connection=connection,
            )
            created += 1
    return created


def run_buzz_check(source: str = "manual") -> dict:
    config = get_config()
    settings = get_buzz_settings()
    selected = settings["selected_account_types"]
    if not settings["enabled"]:
        return {"ok": False, "error": "Buzz tracking is disabled. Enable it in Settings first."}
    if not selected:
        return {"ok": False, "error": "Select at least one Buzz account type in Settings."}
    if not config.api_key:
        return _record_failed_check(UNAVAILABLE_MESSAGE, source, selected)
    client = BuzzClient(config)
    try:
        accounts_payload = client.fetch_buzz_accounts()
    except BuzzClientError as exc:
        return _record_failed_check(str(exc), source, selected)

    accounts = _normalize_accounts(accounts_payload)
    checked_at = utc_now()
    warnings = []
    info = []
    fetched_transactions = {}
    for account_type in selected:
        try:
            payload = client.fetch_buzz_transactions(account_type, settings["transaction_limit"])
        except BuzzClientError as exc:
            warnings.append(f"{account_type} Buzz transactions were unavailable: {exc}")
            fetched_transactions[account_type] = []
            continue
        fetched_transactions[account_type] = _records(
            payload, "transactions", "items", "results", "data"
        )
        if not _has_records_shape(payload, "transactions", "items", "results", "data"):
            warnings.append(
                f"{account_type} Buzz transactions used an unexpected CivitAI response format."
            )
        info.append(
            f"Fetched {len(fetched_transactions[account_type])} recent {account_type} Buzz transactions."
        )
    if not accounts:
        warnings.append("CivitAI returned no recognizable Buzz account balances.")
    quality_status = "partial" if warnings else "good"
    new_rows = []
    account_summaries = []
    with transaction() as connection:
        had_success = bool(connection.execute(
            "SELECT 1 FROM buzz_check WHERE username = ? AND api_ok = 1 LIMIT 1",
            (config.username,),
        ).fetchone())
        cursor = connection.execute(
            "INSERT INTO buzz_check "
            "(checked_at, username, source, api_ok, tracked_account_types, quality_status, "
            "warning_count, warnings_json, info_json, created_at) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
            (
                checked_at, config.username, source, json.dumps(selected), quality_status,
                len(warnings), json.dumps(warnings), json.dumps(info), checked_at,
            ),
        )
        buzz_check_id = cursor.lastrowid
        image_preview_cache = {}
        for account_type in selected:
            normalized_rows = [
                _normalize_transaction(connection, record, account_type)
                for record in fetched_transactions[account_type]
            ]
            for row in normalized_rows:
                _enrich_image_preview(row, client, image_preview_cache)
            gained = sum(row["amount"] for row in normalized_rows if row["amount"] > 0)
            spent = sum(abs(row["amount"]) for row in normalized_rows if row["amount"] < 0)
            account = accounts.get(account_type, {})
            connection.execute(
                "INSERT INTO buzz_account_snapshot "
                "(buzz_check_id, account_type, balance, gained_recent, spent_recent, raw_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    buzz_check_id, account_type, account.get("balance"), gained, spent,
                    account.get("raw_json"),
                ),
            )
            account_summaries.append({
                "account_type": account_type, "balance": account.get("balance"),
                "gained_recent": gained, "spent_recent": spent,
            })
            for row in normalized_rows:
                if _upsert_transaction(connection, row, buzz_check_id, checked_at):
                    new_rows.append(row)
        alert_count = _create_transaction_alerts(connection, new_rows, had_success)
        for message in info:
            insert_sync_log("info", message, connection)
        for warning in warnings:
            insert_sync_log("warning", warning, connection)
        insert_sync_log(
            "info",
            f"Buzz check {buzz_check_id} saved: {len(new_rows)} new transactions and "
            f"{alert_count} local alerts.",
            connection,
        )
    return {
        "ok": True, "error": "", "buzz_check_id": buzz_check_id, "checked_at": checked_at,
        "account_summaries": account_summaries, "new_transaction_count": len(new_rows),
        "warnings": warnings, "info": info, "quality_status": quality_status,
        "alert_count": alert_count,
    }


def list_buzz_checks(limit: int = 50, username: str | None = None) -> list[dict]:
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    limit = min(250, max(1, limit))
    username = username if username is not None else get_config().username
    with create_connection() as connection:
        rows = dict_rows(connection.execute(
            "SELECT * FROM buzz_check WHERE username = ? "
            "ORDER BY checked_at DESC, id DESC LIMIT ?", (username, limit)
        ))
    for row in rows:
        row["tracked_account_types"] = json.loads(row["tracked_account_types"] or "[]")
        row["warnings"] = json.loads(row.pop("warnings_json") or "[]")
        row["info"] = json.loads(row.pop("info_json") or "[]")
    return rows


def latest_buzz_summary() -> dict:
    settings = get_buzz_settings()
    checks = list_buzz_checks(1)
    latest = checks[0] if checks else None
    balances = []
    new_transaction_count = 0
    if latest:
        with create_connection() as connection:
            balances = dict_rows(connection.execute(
                "SELECT account_type, balance, gained_recent, spent_recent "
                "FROM buzz_account_snapshot WHERE buzz_check_id = ? ORDER BY id",
                (latest["id"],),
            ))
            new_transaction_count = connection.execute(
                "SELECT COUNT(*) FROM buzz_transaction WHERE first_seen_at = ?",
                (latest["checked_at"],),
            ).fetchone()[0]
    return {
        "enabled": settings["enabled"],
        "selected_account_types": settings["selected_account_types"],
        "latest_check": latest,
        "latest_balances": balances,
        "new_transaction_count": new_transaction_count,
        "endpoint_available": None if not latest else bool(latest["api_ok"]),
        "warning": (
            latest["error"] if latest and not latest["api_ok"]
            else " ".join(latest["warnings"]) if latest and latest["warnings"]
            else None
        ),
    }


def list_buzz_transactions(filters=None) -> list[dict]:
    filters = filters or {}
    clauses = []
    values = []
    for name in ("account_type", "direction", "event_category"):
        value = _clean_text(filters.get(name))
        if value:
            clauses.append(f"{name} = ?")
            values.append(value)
    search = _clean_text(filters.get("search"))
    if search:
        clauses.append(
            "(description LIKE ? OR model_name LIKE ? OR CAST(image_id AS TEXT) LIKE ? OR username LIKE ?)"
        )
        values.extend([f"%{search}%"] * 4)
    try:
        limit = min(500, max(1, int(filters.get("limit", 200))))
    except (TypeError, ValueError):
        limit = 200
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with create_connection() as connection:
        rows = dict_rows(connection.execute(
            f"SELECT * FROM buzz_transaction {where} "
            "ORDER BY COALESCE(transaction_date, last_seen_at) DESC, id DESC LIMIT ?",
            (*values, limit),
        ))
    config = get_config()
    for row in rows:
        row["image_page_url"] = config.image_page_url(row["image_id"]) if row["image_id"] else None
    return rows


def get_buzz_transaction_detail(transaction_id: int) -> dict:
    with create_connection() as connection:
        row = connection.execute(
            "SELECT * FROM buzz_transaction WHERE id = ?", (transaction_id,)
        ).fetchone()
        if not row:
            raise ValueError("Buzz transaction could not be found.")
        detail = dict(row)
        detail["raw_json"] = json.loads(detail["raw_json"] or "{}")
        detail["related_model"] = _latest_model(connection, detail["model_id"])
    if detail["image_id"] and not detail["image_url"]:
        preview = _resolve_image_preview(BuzzClient(get_config()), detail["image_id"])
        if preview:
            detail["image_url"] = preview["image_url"]
            detail["post_id"] = detail["post_id"] or preview["post_id"]
            with transaction() as connection:
                connection.execute(
                    "UPDATE buzz_transaction SET image_url = ?, post_id = ? WHERE id = ?",
                    (detail["image_url"], detail["post_id"], transaction_id),
                )
    detail["image_page_url"] = (
        get_config().image_page_url(detail["image_id"]) if detail["image_id"] else None
    )
    return detail
