import json
import time
from urllib.parse import urlencode, urljoin

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

    def _fetch_rest_models(self, username: str, model_types: list[str]) -> tuple[list[dict], list[str]]:
        url = f"{self.config.base_url}/api/v1/models"
        params = {
            "username": username,
            "types": ",".join(model_types),
            "limit": 100,
            "page": 1,
            "nsfw": str(self.config.include_nsfw).lower(),
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

    def _fetch_creator_models(self, username: str, model_types: list[str]) -> list[dict]:
        url = f"{self.config.base_url}/api/trpc/model.getAll"
        cursor = None
        items: list[dict] = []
        visited_cursors: set[str] = set()
        for _ in range(self.config.max_pages):
            query = {
                "username": username,
                "types": model_types,
                "browsingLevel": 31,
                "limit": 100,
            }
            if cursor is not None:
                query["cursor"] = cursor
            payload = self.get_json(
                f"{url}?{urlencode({'input': json.dumps({'json': query}, separators=(',', ':'))})}"
            )
            result = ((payload.get("result") or {}).get("data") or {}).get("json") or {}
            page_items = result.get("items") or []
            if not isinstance(page_items, list):
                raise CivitaiError("CivitAI returned an unexpected creator models list.")
            items.extend(item for item in page_items if isinstance(item, dict))
            cursor = result.get("nextCursor")
            if not cursor or not page_items:
                break
            cursor_key = str(cursor)
            if cursor_key in visited_cursors:
                raise CivitaiError("CivitAI creator model pagination repeated unexpectedly.")
            visited_cursors.add(cursor_key)
        return items

    @staticmethod
    def _enrich_collection_counts(items: list[dict], creator_models: list[dict]) -> int:
        collection_counts = {
            item["id"]: (item.get("rank") or {}).get("collectedCount")
            for item in creator_models
            if isinstance(item.get("id"), int)
            and (item.get("rank") or {}).get("collectedCount") is not None
        }
        enriched = 0
        for item in items:
            count = collection_counts.get(item.get("id"))
            if count is None:
                continue
            stats = item.get("stats")
            if not isinstance(stats, dict):
                stats = {}
                item["stats"] = stats
            stats["collectedCount"] = count
            enriched += 1
        return enriched

    def fetch_models(
        self, username: str, model_types: list[str]
    ) -> tuple[list[dict], list[str], list[str]]:
        items, info = self._fetch_rest_models(username, model_types)
        warnings: list[str] = []
        try:
            creator_models = self._fetch_creator_models(username, model_types)
        except CivitaiError:
            warnings.append(
                "Collection metrics were unavailable from CivitAI's site API."
            )
            if self.config.include_minor:
                warnings.append(
                    "Minor-model discovery was unavailable. Saved the standard CivitAI REST catalog only."
                )
            return items, info, warnings

        if not self.config.include_minor:
            enriched = self._enrich_collection_counts(items, creator_models)
            info.append(f"Loaded collection metrics for {enriched} creator models.")
            return items, info, warnings

        known_ids = {item.get("id") for item in items}
        creator_model_ids = {
            item["id"] for item in creator_models if isinstance(item.get("id"), int)
        }
        missing_ids = sorted(creator_model_ids - known_ids)
        failed_ids = []
        for model_id in missing_ids:
            try:
                items.append(self.get_json(f"{self.config.base_url}/api/v1/models/{model_id}"))
            except CivitaiError:
                failed_ids.append(model_id)
        enriched = self._enrich_collection_counts(items, creator_models)
        info.append(f"Loaded collection metrics for {enriched} creator models.")
        info.append(
            f"Minor-model discovery found {len(missing_ids)} additional creator models."
        )
        if failed_ids:
            warnings.append(
                f"Could not load {len(failed_ids)} additional minor models. "
                "Saved the models that were available."
            )
        return items, info, warnings

    def fetch_creator(self, username: str) -> dict | None:
        payload = self.get_json(
            f"{self.config.base_url}/api/v1/creators",
            params={"query": username, "limit": 100},
        )
        for creator in payload.get("items") or []:
            if str(creator.get("username", "")).casefold() == username.casefold():
                return creator
        return None
