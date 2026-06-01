from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def build_model_page_url(base_url: str, model_id: int) -> str:
    return f"{base_url.rstrip('/')}/models/{model_id}"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Config:
    api_key: str
    username: str
    base_url: str
    db_path: Path
    timeout_seconds: int
    model_types: list[str]
    include_nsfw: bool
    include_minor: bool
    max_pages: int
    app_host: str
    app_port: int
    secret_key: str

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key)

    @property
    def model_type_filter(self) -> str:
        return ",".join(self.model_types)

    def model_page_url(self, model_id: int) -> str:
        return build_model_page_url(self.base_url, model_id)


def get_config() -> Config:
    db_value = os.getenv("CIVITAI_ANALYTICS_DB", "storage/civittrack.sqlite")
    db_path = Path(db_value)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    model_types = [
        value.strip()
        for value in os.getenv("CIVITAI_MODEL_TYPES", "LORA").split(",")
        if value.strip()
    ]
    return Config(
        api_key=os.getenv("CIVITAI_API_KEY", "").strip(),
        username=os.getenv("CIVITAI_USERNAME", "").strip(),
        base_url=os.getenv("CIVITAI_BASE_URL", "https://civitai.com").rstrip("/"),
        db_path=db_path,
        timeout_seconds=max(1, _int_env("CIVITAI_TIMEOUT_SECONDS", 20)),
        model_types=model_types or ["LORA"],
        include_nsfw=_bool_env("CIVITAI_INCLUDE_NSFW", True),
        include_minor=_bool_env("CIVITAI_INCLUDE_MINOR", True),
        max_pages=max(1, _int_env("CIVITAI_MAX_PAGES", 100)),
        app_host=os.getenv("APP_HOST", "127.0.0.1"),
        app_port=_int_env("APP_PORT", 8787),
        secret_key=os.getenv("SECRET_KEY", "dev-only-change-me"),
    )
