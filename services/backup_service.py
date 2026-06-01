from contextlib import closing
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .config import get_config
from .db import init_db, insert_sync_log


REQUIRED_TABLES = {
    "snapshot",
    "account_snapshot",
    "model_snapshot",
    "model_version_snapshot",
    "sync_log",
}
MAX_RESTORE_BYTES = 256 * 1024 * 1024


def _copy_database(source_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source_path)) as source, closing(
        sqlite3.connect(target_path)
    ) as target:
        source.backup(target)


def create_download_backup() -> tuple[Path, str]:
    config = get_config()
    if not config.db_path.exists():
        raise ValueError("Database file could not be found.")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    handle, temp_name = tempfile.mkstemp(prefix="civittrack-backup-", suffix=".sqlite")
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        _copy_database(config.db_path, temp_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path, f"civittrack-backup-{timestamp}.sqlite"


def _validate_restore_candidate(path: Path) -> None:
    if path.stat().st_size > MAX_RESTORE_BYTES:
        raise ValueError("Backup file is larger than the 256 MB restore limit.")
    try:
        with closing(sqlite3.connect(path)) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise ValueError("Backup file failed SQLite integrity validation.")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
    except sqlite3.DatabaseError as exc:
        raise ValueError("Uploaded file is not a valid SQLite database.") from exc
    missing_tables = REQUIRED_TABLES - tables
    if missing_tables:
        raise ValueError("Uploaded database is not a CivitTrack backup.")


def restore_database(upload) -> dict:
    config = get_config()
    if not upload or not upload.filename:
        raise ValueError("Choose a CivitTrack SQLite backup file first.")
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in {".sqlite", ".sqlite3", ".db"}:
        raise ValueError("Backup file must use .sqlite, .sqlite3, or .db.")

    config.db_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix="civittrack-restore-", suffix=".sqlite", dir=config.db_path.parent
    )
    os.close(handle)
    temp_path = Path(temp_name)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    safety_path = config.db_path.parent / "backups" / f"civittrack-before-restore-{timestamp}.sqlite"
    try:
        upload.save(temp_path)
        _validate_restore_candidate(temp_path)
        if config.db_path.exists():
            _copy_database(config.db_path, safety_path)
        os.replace(temp_path, config.db_path)
        try:
            init_db()
            insert_sync_log("info", f"Database restored from {Path(upload.filename).name}.")
        except Exception:
            if safety_path.exists():
                shutil.copy2(safety_path, config.db_path)
                init_db()
            raise
    finally:
        temp_path.unlink(missing_ok=True)
    return {
        "ok": True,
        "safety_backup": str(safety_path) if safety_path.exists() else None,
    }
