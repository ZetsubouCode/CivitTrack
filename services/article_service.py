import json
from copy import deepcopy
from urllib.parse import urlparse

from .civitai_client import CivitaiClient, CivitaiError
from .config import get_config
from .db import create_connection, dict_rows, insert_sync_log, transaction, utc_now


ARTICLE_LIST_LIMIT = 100
ARTICLE_LIST_MAX_LIMIT = 500
RATING_FILTERS = {"pg", "pg13", "r", "x", "xxx"}
RATING_LABELS = {"pg": "PG", "pg13": "PG-13", "r": "R", "x": "X", "xxx": "XXX"}
STAT_COLUMNS = (
    "view_count",
    "collected_count",
    "favorite_count",
    "comment_count",
    "like_count",
    "dislike_count",
    "heart_count",
    "laugh_count",
    "cry_count",
    "reaction_count",
    "tipped_amount_count",
)


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


def _json(payload) -> str:
    return json.dumps(deepcopy(payload), ensure_ascii=True, separators=(",", ":"))


def article_rating_label(nsfw_level) -> str:
    level = _safe_int(nsfw_level, 0)
    if level >= 16:
        return "XXX"
    if level >= 8:
        return "X"
    if level >= 4:
        return "R"
    if level >= 2:
        return "PG-13"
    return "PG"


def _cover_image_url(article: dict) -> str | None:
    for key in ("coverImageUrl", "coverUrl", "imageUrl"):
        url = _http_url(article.get(key))
        if url:
            return url
    cover = article.get("cover") if isinstance(article.get("cover"), dict) else {}
    for key in ("url", "previewUrl"):
        url = _http_url(cover.get(key))
        if url:
            return url
    return None


def _normalize_article(article: dict, sync_id: int, checked_at: str, base_url: str) -> dict | None:
    article_id = _safe_optional_int(article.get("id"))
    if not article_id:
        return None
    stats = article.get("stats") if isinstance(article.get("stats"), dict) else {}
    user = article.get("user") if isinstance(article.get("user"), dict) else {}
    tags = [
        tag.get("name")
        for tag in article.get("tags") or []
        if isinstance(tag, dict) and _clean_text(tag.get("name"))
    ]
    like_count = _safe_int(stats.get("likeCount"))
    dislike_count = _safe_int(stats.get("dislikeCount"))
    heart_count = _safe_int(stats.get("heartCount"))
    laugh_count = _safe_int(stats.get("laughCount"))
    cry_count = _safe_int(stats.get("cryCount"))
    reaction_count = _safe_int(
        stats.get("reactionCount"),
        like_count + dislike_count + heart_count + laugh_count + cry_count,
    )
    return {
        "article_id": article_id,
        "title": _clean_text(article.get("title"), f"Article {article_id}"),
        "username": _clean_text(user.get("username")),
        "user_id": _safe_optional_int(article.get("userId") or user.get("id")),
        "cover_image_url": _cover_image_url(article),
        "article_url": f"{base_url.rstrip('/')}/articles/{article_id}",
        "nsfw_level": _safe_optional_int(article.get("nsfwLevel")),
        "rating_label": article_rating_label(article.get("nsfwLevel")),
        "status": _clean_text(article.get("status")),
        "availability": _clean_text(article.get("availability")),
        "published_at": _clean_text(article.get("publishedAt")),
        "created_at_remote": _clean_text(article.get("createdAt")),
        "updated_at": _clean_text(article.get("updatedAt")),
        "tag_names_json": json.dumps(tags, ensure_ascii=True),
        "view_count": _safe_int(stats.get("viewCount")),
        "collected_count": _safe_int(stats.get("collectedCount")),
        "favorite_count": _safe_int(stats.get("favoriteCount")),
        "comment_count": _safe_int(stats.get("commentCount")),
        "like_count": like_count,
        "dislike_count": dislike_count,
        "heart_count": heart_count,
        "laugh_count": laugh_count,
        "cry_count": cry_count,
        "reaction_count": reaction_count,
        "tipped_amount_count": _safe_int(stats.get("tippedAmountCount")),
        "stats_refreshed_at": checked_at,
        "last_seen_at": checked_at,
        "latest_sync_id": sync_id,
        "raw_json": _json(article),
    }


def _upsert_article(connection, row: dict, checked_at: str) -> bool:
    existing = connection.execute(
        "SELECT id FROM model_article WHERE article_id = ?", (row["article_id"],)
    ).fetchone()
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    assignments = ", ".join(
        f"{column} = excluded.{column}"
        for column in row
        if column not in {"article_id"}
    )
    connection.execute(
        f"INSERT INTO model_article ({columns}, first_seen_at) "
        f"VALUES ({placeholders}, ?) "
        "ON CONFLICT(article_id) DO UPDATE SET "
        f"{assignments}",
        (*row.values(), checked_at),
    )
    return existing is None


def _insert_metric_snapshot(connection, row: dict, sync_id: int, checked_at: str) -> None:
    values = {column: row[column] for column in STAT_COLUMNS}
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    connection.execute(
        f"INSERT INTO article_metric_snapshot "
        f"(article_sync_id, article_id, checked_at, {columns}) "
        f"VALUES (?, ?, ?, {placeholders})",
        (sync_id, row["article_id"], checked_at, *values.values()),
    )


def _record_failed_sync(error: str, source: str) -> dict:
    config = get_config()
    now = utc_now()
    with transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO article_sync "
            "(checked_at, username, source, api_ok, error, article_count, new_article_count, "
            "warning_count, warnings_json, info_json, created_at) "
            "VALUES (?, ?, ?, 0, ?, 0, 0, 1, ?, '[]', ?)",
            (now, config.username, source, error, json.dumps([error]), now),
        )
        insert_sync_log("warning", error, connection)
    return {
        "ok": False,
        "error": error,
        "article_sync_id": cursor.lastrowid,
        "checked_at": now,
        "article_count": 0,
        "new_article_count": 0,
        "warnings": [error],
        "info": [],
    }


def run_article_sync(source: str = "manual") -> dict:
    config = get_config()
    if not config.api_key:
        return _record_failed_sync("API key is missing. Add CIVITAI_API_KEY before syncing articles.", source)
    if not config.username:
        return _record_failed_sync("Username is missing. Add CIVITAI_USERNAME before syncing articles.", source)
    client = CivitaiClient(config)
    try:
        articles, info = client.fetch_creator_articles(config.username)
    except CivitaiError as exc:
        return _record_failed_sync(str(exc), source)

    checked_at = utc_now()
    warnings = []
    rows = [
        row
        for row in (
            _normalize_article(article, 0, checked_at, config.base_url)
            for article in articles
        )
        if row
    ]
    if len(rows) != len(articles):
        warnings.append("Some CivitAI article records were missing article IDs and were skipped.")

    with transaction() as connection:
        cursor = connection.execute(
            "INSERT INTO article_sync "
            "(checked_at, username, source, api_ok, article_count, new_article_count, "
            "warning_count, warnings_json, info_json, created_at) VALUES (?, ?, ?, 1, 0, 0, ?, ?, ?, ?)",
            (
                checked_at,
                config.username,
                source,
                len(warnings),
                json.dumps(warnings, ensure_ascii=True),
                json.dumps(info, ensure_ascii=True),
                checked_at,
            ),
        )
        sync_id = cursor.lastrowid
        new_count = 0
        for row in rows:
            row["latest_sync_id"] = sync_id
            if _upsert_article(connection, row, checked_at):
                new_count += 1
            _insert_metric_snapshot(connection, row, sync_id, checked_at)
        connection.execute(
            "UPDATE article_sync SET article_count = ?, new_article_count = ? WHERE id = ?",
            (len(rows), new_count, sync_id),
        )
        for message in info:
            insert_sync_log("info", message, connection)
        for warning in warnings:
            insert_sync_log("warning", warning, connection)
        insert_sync_log(
            "info",
            f"Article sync {sync_id} saved: {len(rows)} creator articles and {new_count} new articles.",
            connection,
        )
    return {
        "ok": True,
        "error": "",
        "article_sync_id": sync_id,
        "checked_at": checked_at,
        "article_count": len(rows),
        "new_article_count": new_count,
        "warnings": warnings,
        "info": info,
    }


def latest_article_summary() -> dict:
    config = get_config()
    with create_connection() as connection:
        latest = connection.execute(
            "SELECT * FROM article_sync WHERE username = ? ORDER BY checked_at DESC, id DESC LIMIT 1",
            (config.username,),
        ).fetchone()
        totals = connection.execute(
            "SELECT COUNT(*) AS article_count, MAX(published_at) AS newest_article_at, "
            "COALESCE(SUM(view_count), 0) AS total_view_count, "
            "COALESCE(SUM(collected_count), 0) AS total_collected_count, "
            "COALESCE(SUM(reaction_count), 0) AS total_reaction_count, "
            "COALESCE(SUM(comment_count), 0) AS total_comment_count, "
            "COALESCE(SUM(tipped_amount_count), 0) AS total_tipped_amount_count "
            "FROM model_article WHERE username IS NULL OR LOWER(username) = LOWER(?)",
            (config.username,),
        ).fetchone()
        rating_rows = dict_rows(
            connection.execute(
                "SELECT rating_label, COUNT(*) AS article_count FROM model_article "
                "WHERE username IS NULL OR LOWER(username) = LOWER(?) "
                "GROUP BY rating_label ORDER BY article_count DESC",
                (config.username,),
            )
        )
    latest_dict = dict(latest) if latest else None
    if latest_dict:
        latest_dict["warnings"] = json.loads(latest_dict.pop("warnings_json") or "[]")
        latest_dict["info"] = json.loads(latest_dict.pop("info_json") or "[]")
    return {
        "latest_sync": latest_dict,
        "totals": dict(totals) if totals else {},
        "ratings": rating_rows,
    }


def _article_delta_select(column: str) -> str:
    return (
        f"(a.{column} - (SELECT p.{column} FROM article_metric_snapshot p "
        "WHERE p.article_id = a.article_id AND p.checked_at < a.stats_refreshed_at "
        f"ORDER BY p.checked_at DESC, p.id DESC LIMIT 1)) AS {column}_delta"
    )


def list_articles(filters=None) -> dict:
    filters = filters or {}
    config = get_config()
    clauses = ["(a.username IS NULL OR LOWER(a.username) = LOWER(?))"]
    values = [config.username]
    ratings = _selected_rating_filters(filters)
    if ratings:
        labels = [RATING_LABELS[rating] for rating in ratings]
        placeholders = ", ".join("?" for _ in labels)
        clauses.append(f"a.rating_label IN ({placeholders})")
        values.extend(labels)
    search = _clean_text(filters.get("search"))
    if search:
        clauses.append(
            "(a.title LIKE ? OR a.tag_names_json LIKE ? OR CAST(a.article_id AS TEXT) LIKE ?)"
        )
        values.extend([f"%{search}%"] * 3)
    try:
        limit = min(ARTICLE_LIST_MAX_LIMIT, max(1, int(filters.get("limit", ARTICLE_LIST_LIMIT))))
    except (TypeError, ValueError):
        limit = ARTICLE_LIST_LIMIT
    try:
        offset = max(0, int(filters.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    sort = _clean_text(filters.get("sort"), "published_desc")
    order_by = {
        "published_asc": "COALESCE(a.published_at, a.created_at_remote, a.first_seen_at) ASC, a.article_id ASC",
        "views": "a.view_count DESC, COALESCE(a.published_at, a.first_seen_at) DESC",
        "collections": "a.collected_count DESC, COALESCE(a.published_at, a.first_seen_at) DESC",
        "reactions": "a.reaction_count DESC, COALESCE(a.published_at, a.first_seen_at) DESC",
        "tips": "a.tipped_amount_count DESC, COALESCE(a.published_at, a.first_seen_at) DESC",
        "comments": "a.comment_count DESC, COALESCE(a.published_at, a.first_seen_at) DESC",
        "published_desc": "COALESCE(a.published_at, a.created_at_remote, a.first_seen_at) DESC, a.article_id DESC",
    }.get(sort, "COALESCE(a.published_at, a.created_at_remote, a.first_seen_at) DESC, a.article_id DESC")
    where = f"WHERE {' AND '.join(clauses)}"
    delta_columns = ", ".join(_article_delta_select(column) for column in STAT_COLUMNS)
    with create_connection() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) FROM model_article a {where}", values
        ).fetchone()[0]
        rows = dict_rows(
            connection.execute(
                "SELECT a.id, a.article_id, a.title, a.username, a.user_id, a.cover_image_url, "
                "a.article_url, a.nsfw_level, a.rating_label, a.status, a.availability, "
                "a.published_at, a.created_at_remote, a.updated_at, a.tag_names_json, "
                "a.view_count, a.collected_count, a.favorite_count, a.comment_count, "
                "a.like_count, a.dislike_count, a.heart_count, a.laugh_count, a.cry_count, "
                "a.reaction_count, a.tipped_amount_count, a.stats_refreshed_at, "
                f"a.first_seen_at, a.last_seen_at, {delta_columns} "
                f"FROM model_article a {where} ORDER BY {order_by} LIMIT ? OFFSET ?",
                (*values, limit, offset),
            )
        )
    for row in rows:
        row["tags"] = json.loads(row.pop("tag_names_json") or "[]")
    return {
        "articles": rows,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(rows) < total,
    }
