from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3

from .config import get_config


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at TEXT NOT NULL,
    username TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    model_type_filter TEXT,
    api_ok INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    raw_total_item INTEGER,
    note_type TEXT,
    note TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    model_count INTEGER DEFAULT 0,
    follower_count INTEGER NULL,
    total_download_count INTEGER DEFAULT 0,
    total_reaction_count INTEGER DEFAULT 0,
    total_collected_count INTEGER NULL,
    total_generation_count INTEGER NULL,
    total_comment_count INTEGER DEFAULT 0,
    FOREIGN KEY(snapshot_id) REFERENCES snapshot(id)
);
CREATE TABLE IF NOT EXISTS model_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    model_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    model_type TEXT,
    nsfw INTEGER DEFAULT 0,
    mode TEXT,
    page_url TEXT,
    latest_version_id INTEGER NULL,
    latest_version_name TEXT,
    base_model TEXT,
    published_at TEXT,
    cover_image_url TEXT,
    download_count INTEGER DEFAULT 0,
    reaction_count INTEGER DEFAULT 0,
    collected_count INTEGER NULL,
    generation_count INTEGER NULL,
    comment_count INTEGER DEFAULT 0,
    raw_json TEXT,
    FOREIGN KEY(snapshot_id) REFERENCES snapshot(id)
);
CREATE TABLE IF NOT EXISTS model_version_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    model_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    model_version_id INTEGER NOT NULL,
    version_name TEXT,
    base_model TEXT,
    published_at TEXT,
    download_count INTEGER DEFAULT 0,
    generation_count INTEGER NULL,
    generation_covered INTEGER NULL,
    raw_json TEXT,
    FOREIGN KEY(snapshot_id) REFERENCES snapshot(id)
);
CREATE TABLE IF NOT EXISTS sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS local_alert (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    username TEXT NOT NULL,
    snapshot_id INTEGER NULL,
    level TEXT NOT NULL DEFAULT 'info',
    alert_type TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    model_id INTEGER NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(snapshot_id) REFERENCES snapshot(id)
);
CREATE TABLE IF NOT EXISTS app_setting (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot_quality (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL UNIQUE,
    quality_status TEXT NOT NULL,
    rest_model_count INTEGER DEFAULT 0,
    api_page_count INTEGER DEFAULT 0,
    minor_discovery_enabled INTEGER DEFAULT 0,
    minor_discovery_status TEXT,
    minor_model_count INTEGER DEFAULT 0,
    collection_metric_status TEXT,
    collection_metric_count INTEGER DEFAULT 0,
    generation_metric_status TEXT,
    generation_metric_count INTEGER DEFAULT 0,
    creator_profile_status TEXT,
    follower_count_available INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,
    warnings_json TEXT,
    info_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(snapshot_id) REFERENCES snapshot(id)
);
CREATE TABLE IF NOT EXISTS buzz_check (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at TEXT NOT NULL,
    username TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    api_ok INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    tracked_account_types TEXT,
    quality_status TEXT NOT NULL DEFAULT 'good',
    warning_count INTEGER DEFAULT 0,
    warnings_json TEXT,
    info_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS buzz_account_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buzz_check_id INTEGER NOT NULL,
    account_type TEXT NOT NULL,
    balance INTEGER NULL,
    gained_recent INTEGER NULL,
    spent_recent INTEGER NULL,
    raw_json TEXT,
    FOREIGN KEY(buzz_check_id) REFERENCES buzz_check(id)
);
CREATE TABLE IF NOT EXISTS buzz_transaction (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_key TEXT NOT NULL,
    account_type TEXT NOT NULL,
    transaction_date TEXT,
    amount INTEGER NOT NULL DEFAULT 0,
    direction TEXT,
    transaction_type TEXT,
    event_category TEXT,
    title TEXT,
    description TEXT,
    entity_type TEXT,
    entity_id TEXT,
    model_id INTEGER NULL,
    model_name TEXT,
    model_url TEXT,
    image_id INTEGER NULL,
    image_url TEXT,
    post_id INTEGER NULL,
    user_id INTEGER NULL,
    username TEXT,
    match_confidence TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    latest_check_id INTEGER,
    raw_json TEXT,
    UNIQUE(transaction_key, account_type),
    FOREIGN KEY(latest_check_id) REFERENCES buzz_check(id)
);
CREATE TABLE IF NOT EXISTS image_sync (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at TEXT NOT NULL,
    username TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    api_ok INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    version_count INTEGER DEFAULT 0,
    image_count INTEGER DEFAULT 0,
    new_image_count INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,
    warnings_json TEXT,
    info_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_image (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER NOT NULL UNIQUE,
    post_id INTEGER NULL,
    model_id INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    model_version_id INTEGER NOT NULL,
    version_name TEXT,
    base_model TEXT,
    image_url TEXT,
    image_page_url TEXT,
    creator_user_id INTEGER NULL,
    width INTEGER NULL,
    height INTEGER NULL,
    nsfw_level TEXT,
    nsfw INTEGER DEFAULT 0,
    image_type TEXT,
    published_at TEXT,
    username TEXT,
    cry_count INTEGER DEFAULT 0,
    laugh_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    dislike_count INTEGER DEFAULT 0,
    heart_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    stats_refreshed_at TEXT,
    reaction_refreshed_at TEXT,
    model_version_ids_json TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    latest_sync_id INTEGER,
    raw_json TEXT,
    FOREIGN KEY(latest_sync_id) REFERENCES image_sync(id)
);
CREATE TABLE IF NOT EXISTS article_sync (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    checked_at TEXT NOT NULL,
    username TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'manual',
    api_ok INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    article_count INTEGER DEFAULT 0,
    new_article_count INTEGER DEFAULT 0,
    warning_count INTEGER DEFAULT 0,
    warnings_json TEXT,
    info_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_article (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id INTEGER NOT NULL UNIQUE,
    title TEXT NOT NULL,
    username TEXT,
    user_id INTEGER NULL,
    cover_image_url TEXT,
    article_url TEXT,
    nsfw_level INTEGER NULL,
    rating_label TEXT,
    status TEXT,
    availability TEXT,
    published_at TEXT,
    created_at_remote TEXT,
    updated_at TEXT,
    tag_names_json TEXT,
    view_count INTEGER DEFAULT 0,
    collected_count INTEGER DEFAULT 0,
    favorite_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    dislike_count INTEGER DEFAULT 0,
    heart_count INTEGER DEFAULT 0,
    laugh_count INTEGER DEFAULT 0,
    cry_count INTEGER DEFAULT 0,
    reaction_count INTEGER DEFAULT 0,
    tipped_amount_count INTEGER DEFAULT 0,
    stats_refreshed_at TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    latest_sync_id INTEGER,
    raw_json TEXT,
    FOREIGN KEY(latest_sync_id) REFERENCES article_sync(id)
);
CREATE TABLE IF NOT EXISTS article_metric_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    article_sync_id INTEGER NOT NULL,
    article_id INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    view_count INTEGER DEFAULT 0,
    collected_count INTEGER DEFAULT 0,
    favorite_count INTEGER DEFAULT 0,
    comment_count INTEGER DEFAULT 0,
    like_count INTEGER DEFAULT 0,
    dislike_count INTEGER DEFAULT 0,
    heart_count INTEGER DEFAULT 0,
    laugh_count INTEGER DEFAULT 0,
    cry_count INTEGER DEFAULT 0,
    reaction_count INTEGER DEFAULT 0,
    tipped_amount_count INTEGER DEFAULT 0,
    FOREIGN KEY(article_sync_id) REFERENCES article_sync(id)
);
CREATE TABLE IF NOT EXISTS image_reaction_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image_id INTEGER NOT NULL,
    reaction TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    UNIQUE(image_id, reaction)
);
CREATE TABLE IF NOT EXISTS comment_reaction_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    comment_id INTEGER NOT NULL,
    reaction TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    UNIQUE(comment_id, reaction)
);
CREATE TABLE IF NOT EXISTS reaction_action_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    reaction TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hidden_image_preference (
    image_id INTEGER PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'civitai',
    hidden_at TEXT NOT NULL,
    raw_json TEXT
);
CREATE TABLE IF NOT EXISTS blocked_user_preference (
    user_id INTEGER NULL,
    username TEXT NULL,
    source TEXT NOT NULL DEFAULT 'civitai',
    blocked_at TEXT NOT NULL,
    raw_json TEXT,
    UNIQUE(user_id, username)
);
CREATE INDEX IF NOT EXISTS idx_snapshot_checked_at ON snapshot(checked_at);
CREATE INDEX IF NOT EXISTS idx_model_snapshot_lookup
    ON model_snapshot(snapshot_id, model_id);
CREATE INDEX IF NOT EXISTS idx_model_version_snapshot_lookup
    ON model_version_snapshot(snapshot_id, model_id, model_version_id);
CREATE INDEX IF NOT EXISTS idx_sync_log_created_at ON sync_log(created_at);
CREATE INDEX IF NOT EXISTS idx_local_alert_inbox
    ON local_alert(username, is_read, id);
CREATE INDEX IF NOT EXISTS idx_local_alert_snapshot
    ON local_alert(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_quality_snapshot
    ON snapshot_quality(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_buzz_check_checked_at ON buzz_check(checked_at);
CREATE INDEX IF NOT EXISTS idx_buzz_transaction_account_date
    ON buzz_transaction(account_type, transaction_date);
CREATE INDEX IF NOT EXISTS idx_buzz_transaction_category
    ON buzz_transaction(event_category);
CREATE INDEX IF NOT EXISTS idx_buzz_transaction_model
    ON buzz_transaction(model_id);
CREATE INDEX IF NOT EXISTS idx_buzz_transaction_image
    ON buzz_transaction(image_id);
CREATE INDEX IF NOT EXISTS idx_buzz_transaction_latest_check
    ON buzz_transaction(latest_check_id);
CREATE INDEX IF NOT EXISTS idx_image_sync_checked_at ON image_sync(checked_at);
CREATE INDEX IF NOT EXISTS idx_model_image_published
    ON model_image(published_at);
CREATE INDEX IF NOT EXISTS idx_model_image_model
    ON model_image(model_id);
CREATE INDEX IF NOT EXISTS idx_model_image_version
    ON model_image(model_version_id);
CREATE INDEX IF NOT EXISTS idx_model_image_username
    ON model_image(username);
CREATE INDEX IF NOT EXISTS idx_article_sync_checked_at ON article_sync(checked_at);
CREATE INDEX IF NOT EXISTS idx_model_article_published
    ON model_article(published_at);
CREATE INDEX IF NOT EXISTS idx_model_article_rating
    ON model_article(rating_label);
CREATE INDEX IF NOT EXISTS idx_article_metric_snapshot_article
    ON article_metric_snapshot(article_id, checked_at);
CREATE INDEX IF NOT EXISTS idx_image_reaction_state_image
    ON image_reaction_state(image_id);
CREATE INDEX IF NOT EXISTS idx_comment_reaction_state_comment
    ON comment_reaction_state(comment_id);
CREATE INDEX IF NOT EXISTS idx_reaction_action_log_created
    ON reaction_action_log(created_at);
CREATE INDEX IF NOT EXISTS idx_hidden_image_preference_hidden_at
    ON hidden_image_preference(hidden_at);
CREATE INDEX IF NOT EXISTS idx_blocked_user_preference_user_id
    ON blocked_user_preference(user_id);
CREATE INDEX IF NOT EXISTS idx_blocked_user_preference_username
    ON blocked_user_preference(username);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def create_connection() -> sqlite3.Connection:
    config = get_config()
    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(config.db_path, factory=ClosingConnection)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with create_connection() as connection:
        connection.executescript(SCHEMA)
        model_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(model_snapshot)")
        }
        if "cover_image_url" not in model_columns:
            connection.execute("ALTER TABLE model_snapshot ADD COLUMN cover_image_url TEXT")
        if "collected_count" not in model_columns:
            connection.execute("ALTER TABLE model_snapshot ADD COLUMN collected_count INTEGER NULL")
        if "generation_count" not in model_columns:
            connection.execute("ALTER TABLE model_snapshot ADD COLUMN generation_count INTEGER NULL")
        account_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(account_snapshot)")
        }
        if "total_collected_count" not in account_columns:
            connection.execute(
                "ALTER TABLE account_snapshot ADD COLUMN total_collected_count INTEGER NULL"
            )
        if "total_generation_count" not in account_columns:
            connection.execute(
                "ALTER TABLE account_snapshot ADD COLUMN total_generation_count INTEGER NULL"
            )
        version_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(model_version_snapshot)")
        }
        if "generation_count" not in version_columns:
            connection.execute(
                "ALTER TABLE model_version_snapshot ADD COLUMN generation_count INTEGER NULL"
            )
        if "generation_covered" not in version_columns:
            connection.execute(
                "ALTER TABLE model_version_snapshot ADD COLUMN generation_covered INTEGER NULL"
            )
        quality_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(snapshot_quality)")
        }
        if "generation_metric_status" not in quality_columns:
            connection.execute(
                "ALTER TABLE snapshot_quality ADD COLUMN generation_metric_status TEXT"
            )
        if "generation_metric_count" not in quality_columns:
            connection.execute(
                "ALTER TABLE snapshot_quality ADD COLUMN generation_metric_count INTEGER DEFAULT 0"
            )
        snapshot_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(snapshot)")
        }
        if "note" not in snapshot_columns:
            connection.execute("ALTER TABLE snapshot ADD COLUMN note TEXT")
        if "note_type" not in snapshot_columns:
            connection.execute("ALTER TABLE snapshot ADD COLUMN note_type TEXT")
        buzz_check_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(buzz_check)")
        }
        for name, definition in (
            ("source", "TEXT NOT NULL DEFAULT 'manual'"),
            ("quality_status", "TEXT NOT NULL DEFAULT 'good'"),
            ("warning_count", "INTEGER DEFAULT 0"),
            ("warnings_json", "TEXT"),
            ("info_json", "TEXT"),
        ):
            if name not in buzz_check_columns:
                connection.execute(f"ALTER TABLE buzz_check ADD COLUMN {name} {definition}")
        model_image_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(model_image)")
        }
        if "creator_user_id" not in model_image_columns:
            connection.execute("ALTER TABLE model_image ADD COLUMN creator_user_id INTEGER NULL")
        if "stats_refreshed_at" not in model_image_columns:
            connection.execute("ALTER TABLE model_image ADD COLUMN stats_refreshed_at TEXT")
        if "reaction_refreshed_at" not in model_image_columns:
            connection.execute("ALTER TABLE model_image ADD COLUMN reaction_refreshed_at TEXT")


def dict_rows(cursor: sqlite3.Cursor) -> list[dict]:
    return [dict(row) for row in cursor.fetchall()]


@contextmanager
def transaction():
    connection = create_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def insert_sync_log(level: str, message: str, connection=None) -> None:
    owns_connection = connection is None
    connection = connection or create_connection()
    connection.execute(
        "INSERT INTO sync_log (created_at, level, message) VALUES (?, ?, ?)",
        (utc_now(), level.lower(), message),
    )
    if owns_connection:
        connection.commit()
        connection.close()


def list_sync_logs(limit: int = 80) -> list[dict]:
    with create_connection() as connection:
        return dict_rows(
            connection.execute(
                "SELECT created_at, level, message FROM sync_log "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        )
