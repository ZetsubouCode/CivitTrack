from dataclasses import dataclass
from pathlib import Path
import os
import json
import re
from urllib.parse import urlparse

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

ENV_FIELDS = (
    {"name": "CIVITAI_API_KEY", "default": "", "secret": True},
    {"name": "CIVITAI_USERNAME", "default": ""},
    {"name": "CIVITAI_BASE_URL", "default": "https://civitai.com"},
    {"name": "CIVITAI_ANALYTICS_DB", "default": "storage/civittrack.sqlite"},
    {"name": "CIVITAI_TIMEOUT_SECONDS", "default": "20"},
    {"name": "CIVITAI_MODEL_TYPES", "default": "LORA"},
    {"name": "CIVITAI_INCLUDE_NSFW", "default": "true"},
    {"name": "CIVITAI_INCLUDE_MINOR", "default": "true"},
    {"name": "CIVITAI_MAX_PAGES", "default": "100"},
    {"name": "APP_HOST", "default": "127.0.0.1", "restart_required": True},
    {"name": "APP_PORT", "default": "8787", "restart_required": True},
    {"name": "SECRET_KEY", "default": "dev-only-change-me", "secret": True},
)
ENV_FIELD_MAP = {field["name"]: field for field in ENV_FIELDS}
ENV_ASSIGNMENT = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z_][A-Za-z0-9_]*)(\s*=).*$")
UNQUOTED_ENV_VALUE = re.compile(r"^[A-Za-z0-9_./:@,+-]*$")


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


def _normalize_setting(name: str, value) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string.")
    if "\n" in value or "\r" in value:
        raise ValueError(f"{name} must be a single-line value.")

    if name in {"CIVITAI_API_KEY", "CIVITAI_USERNAME", "CIVITAI_BASE_URL",
                "CIVITAI_ANALYTICS_DB", "APP_HOST"}:
        value = value.strip()
    if name == "CIVITAI_BASE_URL":
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("CIVITAI_BASE_URL must be an HTTP or HTTPS URL.")
        return value.rstrip("/")
    if name == "CIVITAI_ANALYTICS_DB":
        if not value:
            raise ValueError("CIVITAI_ANALYTICS_DB cannot be empty.")
        return value
    if name == "CIVITAI_TIMEOUT_SECONDS":
        return str(_positive_int(name, value))
    if name == "CIVITAI_MODEL_TYPES":
        model_types = [item.strip() for item in value.split(",") if item.strip()]
        if not model_types:
            raise ValueError("CIVITAI_MODEL_TYPES must include at least one model type.")
        return ",".join(model_types)
    if name in {"CIVITAI_INCLUDE_NSFW", "CIVITAI_INCLUDE_MINOR"}:
        normalized = value.strip().lower()
        if normalized not in {"true", "false"}:
            raise ValueError(f"{name} must be true or false.")
        return normalized
    if name == "CIVITAI_MAX_PAGES":
        return str(_positive_int(name, value))
    if name == "APP_HOST":
        if not value:
            raise ValueError("APP_HOST cannot be empty.")
        return value
    if name == "APP_PORT":
        port = _positive_int(name, value)
        if port > 65535:
            raise ValueError("APP_PORT must be between 1 and 65535.")
        return str(port)
    return value


def _positive_int(name: str, value: str) -> int:
    try:
        parsed = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be at least 1.")
    return parsed


def _serialize_env_value(value: str) -> str:
    return value if UNQUOTED_ENV_VALUE.fullmatch(value) else json.dumps(value)


def _write_env_values(updates: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen = set()
    rendered = []
    for line in lines:
        match = ENV_ASSIGNMENT.match(line)
        name = match.group(2) if match else None
        if name in updates:
            rendered.append(f"{name}={_serialize_env_value(updates[name])}")
            seen.add(name)
        else:
            rendered.append(line)
    for field in ENV_FIELDS:
        name = field["name"]
        if name in updates and name not in seen:
            rendered.append(f"{name}={_serialize_env_value(updates[name])}")
    temp_path = ENV_PATH.with_name(f"{ENV_PATH.name}.tmp")
    temp_path.write_text("\n".join(rendered) + "\n", encoding="utf-8")
    temp_path.replace(ENV_PATH)


def list_env_settings() -> dict:
    fields = {}
    for field in ENV_FIELDS:
        name = field["name"]
        value = os.getenv(name, field["default"])
        fields[name] = {
            "value": "" if field.get("secret") else value,
            "configured": bool(value),
        }
    return {"fields": fields}


def update_env_settings(values, clear_secrets=None) -> dict:
    if not isinstance(values, dict):
        raise ValueError("Settings values must be an object.")
    clear_secrets = [] if clear_secrets is None else clear_secrets
    if not isinstance(clear_secrets, list) or any(not isinstance(name, str) for name in clear_secrets):
        raise ValueError("clear_secrets must be a list of field names.")
    unknown = (set(values) | set(clear_secrets)) - set(ENV_FIELD_MAP)
    if unknown:
        raise ValueError(f"Unknown setting: {sorted(unknown)[0]}.")
    invalid_clears = [name for name in clear_secrets if not ENV_FIELD_MAP[name].get("secret")]
    if invalid_clears:
        raise ValueError(f"{invalid_clears[0]} is not a secret setting.")

    updates = {}
    changed = []
    for name, value in values.items():
        field = ENV_FIELD_MAP[name]
        if field.get("secret") and value == "" and name not in clear_secrets:
            continue
        normalized = _normalize_setting(name, "" if name in clear_secrets else value)
        updates[name] = normalized
        if os.getenv(name, field["default"]) != normalized:
            changed.append(name)
    if updates:
        _write_env_values(updates)
        os.environ.update(updates)
    restart_required = any(ENV_FIELD_MAP[name].get("restart_required") for name in changed)
    return {
        "changed": changed,
        "restart_required": restart_required,
        "settings": list_env_settings(),
    }


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
