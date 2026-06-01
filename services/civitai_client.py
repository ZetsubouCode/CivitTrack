import time
from urllib.parse import urljoin

import requests

from .config import Config, get_config


class CivitaiError(RuntimeError):
    pass


class CivitaiClient:
    def __init__(self, config: Config | None = None):
        self.config = config or get_config()
        self.session = requests.Session()

    def get_auth_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "CivitTrack/1.0",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def get_json(self, url: str, params: dict | None = None) -> dict:
        for attempt in range(3):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    headers=self.get_auth_headers(),
                    timeout=self.config.timeout_seconds,
                )
            except requests.Timeout as exc:
                raise CivitaiError("CivitAI request timed out. Try again later.") from exc
            except requests.RequestException as exc:
                raise CivitaiError("Could not connect to CivitAI. Try again later.") from exc

            if response.status_code in (401, 403):
                raise CivitaiError("API key invalid, missing, or not allowed.")
            if response.status_code == 429:
                raise CivitaiError("Rate limited. Try again later.")
            if response.status_code >= 500 and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            if not response.ok:
                raise CivitaiError(f"CivitAI API returned HTTP {response.status_code}.")
            try:
                payload = response.json()
            except ValueError as exc:
                raise CivitaiError("CivitAI returned invalid JSON.") from exc
            if not isinstance(payload, dict):
                raise CivitaiError("CivitAI returned an unexpected response format.")
            return payload
        raise CivitaiError("CivitAI is temporarily unavailable. Try again later.")

    def fetch_models(self, username: str, model_types: list[str]) -> tuple[list[dict], list[str]]:
        url = f"{self.config.base_url}/api/v1/models"
        params = {
            "username": username,
            "types": ",".join(model_types),
            "limit": 100,
            "page": 1,
        }
        items: list[dict] = []
        info: list[str] = []
        visited: set[str] = set()

        for page_number in range(1, self.config.max_pages + 1):
            payload = self.get_json(url, params=params)
            page_items = payload.get("items") or []
            if not isinstance(page_items, list):
                raise CivitaiError("CivitAI returned an unexpected models list.")
            info.append(f"Fetched page {page_number}: {len(page_items)} models.")
            if not page_items:
                break
            items.extend(item for item in page_items if isinstance(item, dict))
            next_page = (payload.get("metadata") or {}).get("nextPage")
            if not next_page:
                break
            next_url = urljoin(f"{self.config.base_url}/", str(next_page))
            if next_url in visited:
                raise CivitaiError("CivitAI pagination repeated a page unexpectedly.")
            visited.add(next_url)
            url = next_url
            params = None
        else:
            info.append(f"Stopped at configured page limit ({self.config.max_pages}).")
        return items, info

    def fetch_creator(self, username: str) -> dict | None:
        payload = self.get_json(
            f"{self.config.base_url}/api/v1/creators",
            params={"query": username, "limit": 100},
        )
        for creator in payload.get("items") or []:
            if str(creator.get("username", "")).casefold() == username.casefold():
                return creator
        return None
