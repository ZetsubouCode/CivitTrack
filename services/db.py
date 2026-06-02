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
        account_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(account_snapshot)")
        }
        if "total_collected_count" not in account_columns:
            connection.execute(
                "ALTER TABLE account_snapshot ADD COLUMN total_collected_count INTEGER NULL"
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
