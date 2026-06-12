from dataclasses import dataclass
import hashlib
import mimetypes
from pathlib import Path
import time
from urllib.parse import urlparse

import requests

from .config import BASE_DIR, get_config
from .db import create_connection


CACHE_DIR = BASE_DIR / "storage" / "image-cache"
CACHE_MAX_BYTES = 512 * 1024 * 1024
CACHE_MAX_FILE_BYTES = 8 * 1024 * 1024
CACHE_CHUNK_BYTES = 64 * 1024
CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
THUMBNAIL_WIDTH = 450


class ImageCacheError(RuntimeError):
    pass


@dataclass(frozen=True)
class CachedImage:
    path: Path
    mimetype: str


def _http_url(value) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme in {"http", "https"} and parsed.netloc else None


def _thumbnail_url(url: str) -> str:
    if "/original=true/" in url:
        return url.replace("/original=true/", f"/width={THUMBNAIL_WIDTH}/")
    return url


def _cache_key(image_id: int, url: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]
    return f"{int(image_id)}-{digest}"


def _extension_for(content_type: str, url: str) -> str:
    content_type = content_type.split(";", 1)[0].strip().lower()
    if content_type == "image/jpeg":
        return ".jpg"
    if content_type == "image/png":
        return ".png"
    if content_type == "image/webp":
        return ".webp"
    if content_type == "image/gif":
        return ".gif"
    guessed = mimetypes.guess_extension(content_type)
    if guessed:
        return guessed
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else ".img"


def _mimetype_for(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _lookup_image_url(image_id: int) -> str:
    with create_connection() as connection:
        row = connection.execute(
            "SELECT image_url FROM model_image WHERE image_id = ?", (image_id,)
        ).fetchone()
    url = _http_url(row["image_url"] if row else None)
    if not url:
        raise ImageCacheError("Stored image URL is unavailable.")
    return _thumbnail_url(url)


def _existing_cached_file(key: str) -> Path | None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    matches = [path for path in CACHE_DIR.glob(f"{key}.*") if path.is_file()]
    if not matches:
        return None
    path = max(matches, key=lambda item: item.stat().st_mtime)
    now = time.time()
    try:
        path.touch()
    except OSError:
        pass
    return path


def _cache_size() -> int:
    if not CACHE_DIR.exists():
        return 0
    return sum(path.stat().st_size for path in CACHE_DIR.iterdir() if path.is_file() and not path.name.endswith(".tmp"))


def cleanup_image_cache(max_bytes: int = CACHE_MAX_BYTES) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        path for path in CACHE_DIR.iterdir()
        if path.is_file() and not path.name.endswith(".tmp")
    ]
    total = sum(path.stat().st_size for path in files)
    removed = 0
    for path in sorted(files, key=lambda item: item.stat().st_mtime):
        if total <= max_bytes:
            break
        try:
            size = path.stat().st_size
            path.unlink()
        except OSError:
            continue
        total -= size
        removed += 1
    return {"cache_bytes": total, "removed_files": removed, "max_bytes": max_bytes}


def image_cache_status() -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files = [
        path for path in CACHE_DIR.iterdir()
        if path.is_file() and not path.name.endswith(".tmp")
    ]
    return {
        "cache_dir": str(CACHE_DIR),
        "cache_bytes": sum(path.stat().st_size for path in files),
        "cache_file_count": len(files),
        "max_bytes": CACHE_MAX_BYTES,
        "max_file_bytes": CACHE_MAX_FILE_BYTES,
    }


def clear_image_cache() -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    removed = 0
    bytes_removed = 0
    for path in CACHE_DIR.iterdir():
        if not path.is_file():
            continue
        try:
            size = path.stat().st_size
            path.unlink()
        except OSError:
            continue
        removed += 1
        bytes_removed += size
    return {
        "ok": True,
        "removed_files": removed,
        "bytes_removed": bytes_removed,
        **image_cache_status(),
    }


def get_cached_image(image_id: int) -> CachedImage:
    image_id = int(image_id)
    url = _lookup_image_url(image_id)
    key = _cache_key(image_id, url)
    existing = _existing_cached_file(key)
    if existing:
        return CachedImage(existing, _mimetype_for(existing))

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    config = get_config()
    headers = {
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "User-Agent": "CivitTrack/1.0",
    }
    try:
        response = requests.get(
            url,
            headers=headers,
            timeout=config.timeout_seconds,
            stream=True,
        )
    except requests.RequestException as exc:
        raise ImageCacheError("Could not fetch the remote image thumbnail.") from exc
    if not response.ok:
        raise ImageCacheError(f"Remote image returned HTTP {response.status_code}.")

    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        raise ImageCacheError("Remote URL did not return an image.")
    content_length = response.headers.get("Content-Length")
    try:
        if content_length and int(content_length) > CACHE_MAX_FILE_BYTES:
            raise ImageCacheError("Remote image thumbnail is larger than the local cache limit.")
    except ValueError:
        pass

    extension = _extension_for(content_type, url)
    final_path = CACHE_DIR / f"{key}{extension}"
    temp_path = CACHE_DIR / f"{key}{extension}.tmp"
    total = 0
    try:
        with temp_path.open("wb") as handle:
            for chunk in response.iter_content(CACHE_CHUNK_BYTES):
                if not chunk:
                    continue
                total += len(chunk)
                if total > CACHE_MAX_FILE_BYTES:
                    raise ImageCacheError("Remote image thumbnail is larger than the local cache limit.")
                handle.write(chunk)
        temp_path.replace(final_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    cleanup_image_cache()
    return CachedImage(final_path, content_type)
