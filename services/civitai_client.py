import json
import time
from urllib.parse import urlencode, urljoin

import requests

from .config import Config, get_config


class CivitaiError(RuntimeError):
    pass


GENERATION_BATCH_SIZE = 20
GENERATION_BATCH_DELAY_SECONDS = 0.15


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

    @staticmethod
    def _trpc_result(payload: dict, fallback_error: str) -> dict | list | None:
        if payload.get("error"):
            error = payload["error"]
            message = (
                ((error.get("json") or {}).get("message") if isinstance(error.get("json"), dict) else None)
                or error.get("message")
                or fallback_error
            )
            raise CivitaiError(message)
        return ((payload.get("result") or {}).get("data") or {}).get("json")

    def post_trpc(self, procedure: str, data: dict) -> dict | list | None:
        url = f"{self.config.base_url}/api/trpc/{procedure}"
        for attempt in range(3):
            try:
                response = self.session.post(
                    url,
                    json={"json": data},
                    headers=self.get_auth_headers(),
                    timeout=self.config.timeout_seconds,
                )
            except requests.Timeout as exc:
                raise CivitaiError("CivitAI request timed out. Try again later.") from exc
            except requests.RequestException as exc:
                raise CivitaiError("Could not connect to CivitAI. Try again later.") from exc
            if response.status_code in (401, 403):
                raise CivitaiError("API key invalid, missing, or not allowed for this CivitAI action.")
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
            return self._trpc_result(payload, "CivitAI rejected the request.")
        raise CivitaiError("CivitAI is temporarily unavailable. Try again later.")

    def get_trpc_batch(self, procedure: str, inputs: list[dict]) -> list[dict | list | None]:
        if not inputs:
            return []
        procedures = ",".join(procedure for _ in inputs)
        payload = {
            str(index): {"json": item}
            for index, item in enumerate(inputs)
        }
        url = (
            f"{self.config.base_url}/api/trpc/{procedures}?"
            f"batch=1&{urlencode({'input': json.dumps(payload, separators=(',', ':'))})}"
        )
        last_error = "CivitAI rejected the batched tRPC request."
        for attempt in range(4):
            try:
                response = self.session.get(
                    url,
                    headers=self.get_auth_headers(),
                    timeout=self.config.timeout_seconds,
                )
            except requests.Timeout as exc:
                last_error = "CivitAI tRPC request timed out."
                if attempt >= 3:
                    raise CivitaiError(last_error) from exc
                time.sleep(0.6 * (2 ** attempt))
                continue
            except requests.RequestException as exc:
                last_error = "Could not connect to CivitAI tRPC."
                if attempt >= 3:
                    raise CivitaiError(last_error) from exc
                time.sleep(0.6 * (2 ** attempt))
                continue

            if response.status_code in (401, 403):
                raise CivitaiError("API key invalid, missing, or not allowed for CivitAI tRPC.")
            if response.status_code == 429:
                last_error = "CivitAI rate limited the batched tRPC request."
                if attempt >= 3:
                    raise CivitaiError(last_error)
                time.sleep(1.2 * (2 ** attempt))
                continue
            if response.status_code >= 500 and attempt < 3:
                last_error = f"CivitAI tRPC returned HTTP {response.status_code}."
                time.sleep(0.8 * (2 ** attempt))
                continue
            if not response.ok:
                raise CivitaiError(f"CivitAI tRPC returned HTTP {response.status_code}.")
            try:
                payload = response.json()
            except ValueError as exc:
                raise CivitaiError("CivitAI returned invalid tRPC JSON.") from exc
            if not isinstance(payload, list):
                raise CivitaiError("CivitAI returned an unexpected batched tRPC response.")
            if len(payload) != len(inputs):
                raise CivitaiError("CivitAI returned an incomplete batched tRPC response.")
            decoded = []
            for item in payload:
                if not isinstance(item, dict):
                    decoded.append(None)
                    continue
                try:
                    decoded.append(
                        self._trpc_result(item, "CivitAI rejected a batched tRPC item.")
                    )
                except CivitaiError:
                    decoded.append(None)
            return decoded
        raise CivitaiError(last_error)

    @staticmethod
    def _safe_optional_int(value) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_optional_bool(value) -> bool | None:
        return value if isinstance(value, bool) else None

    def _enrich_generation_counts(
        self,
        items: list[dict],
        info: list[str],
        warnings: list[str],
        metadata: dict,
    ) -> None:
        model_ids = []
        seen = set()
        for item in items:
            model_id = item.get("id")
            if isinstance(model_id, int) and model_id not in seen:
                model_ids.append(model_id)
                seen.add(model_id)

        metadata["generation_metric_status"] = "skipped" if not model_ids else "unavailable"
        metadata["generation_metric_count"] = 0
        metadata["generation_model_count"] = len(model_ids)
        if not model_ids:
            return

        details_by_id: dict[int, dict] = {}
        failed_batches = 0
        for start in range(0, len(model_ids), GENERATION_BATCH_SIZE):
            batch_ids = model_ids[start:start + GENERATION_BATCH_SIZE]
            try:
                results = self.get_trpc_batch(
                    "model.getById",
                    [{"id": model_id} for model_id in batch_ids],
                )
            except CivitaiError:
                failed_batches += 1
                continue
            for model_id, result in zip(batch_ids, results):
                if isinstance(result, dict):
                    details_by_id[model_id] = result
            if start + GENERATION_BATCH_SIZE < len(model_ids):
                time.sleep(GENERATION_BATCH_DELAY_SECONDS)

        for item in items:
            detail = details_by_id.get(item.get("id"))
            if not isinstance(detail, dict):
                continue
            rank = detail.get("rank") if isinstance(detail.get("rank"), dict) else {}
            generation_count = self._safe_optional_int(rank.get("generationCountAllTime"))
            item["_generation_count"] = generation_count
            can_generate = self._safe_optional_bool(detail.get("canGenerate"))
            if can_generate is not None:
                item["_generation_available"] = can_generate
            elif generation_count is not None:
                item["_generation_available"] = True

            version_details = {}
            for version in detail.get("modelVersions") or []:
                if not isinstance(version, dict) or not isinstance(version.get("id"), int):
                    continue
                version_rank = version.get("rank") if isinstance(version.get("rank"), dict) else {}
                version_coverage = (
                    version.get("generationCoverage")
                    if isinstance(version.get("generationCoverage"), dict)
                    else {}
                )
                version_details[version["id"]] = {
                    "generation_count": self._safe_optional_int(
                        version_rank.get("generationCountAllTime")
                    ),
                    "generation_covered": self._safe_optional_bool(version_coverage.get("covered")),
                }
            for version in item.get("modelVersions") or []:
                if not isinstance(version, dict):
                    continue
                detail_version = version_details.get(version.get("id"))
                if not detail_version:
                    continue
                version["_generation_count"] = detail_version["generation_count"]
                if detail_version["generation_covered"] is not None:
                    version["_generation_covered"] = detail_version["generation_covered"]

        loaded = sum(
            1 for item in items
            if self._safe_optional_int(item.get("_generation_count")) is not None
        )
        metadata["generation_metric_count"] = loaded
        if loaded == len(model_ids):
            metadata["generation_metric_status"] = "success"
        elif loaded:
            metadata["generation_metric_status"] = "partial"
        else:
            metadata["generation_metric_status"] = "unavailable"
        if failed_batches or loaded < len(model_ids):
            warnings.append(
                "Generation metrics were partially unavailable from CivitAI's site API. "
                "Saved unknown generation counts as N/A."
            )
        info.append(
            f"Loaded generation metrics for {loaded} of {len(model_ids)} models "
            f"using {max(1, (len(model_ids) + GENERATION_BATCH_SIZE - 1) // GENERATION_BATCH_SIZE)} batched tRPC request"
            f"{'' if len(model_ids) <= GENERATION_BATCH_SIZE else 's'}."
        )

    def _fetch_rest_models(
        self, username: str, model_types: list[str]
    ) -> tuple[list[dict], list[str], int]:
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
        api_page_count = 0

        for page_number in range(1, self.config.max_pages + 1):
            payload = self.get_json(url, params=params)
            api_page_count += 1
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
        return items, info, api_page_count

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
    ) -> tuple[list[dict], list[str], list[str], dict]:
        items, info, api_page_count = self._fetch_rest_models(username, model_types)
        warnings: list[str] = []
        metadata = {
            "rest_model_count": len(items),
            "api_page_count": api_page_count,
            "creator_models_available": False,
            "creator_model_count": 0,
            "minor_discovery_enabled": self.config.include_minor,
            "minor_discovery_status": "skipped" if not self.config.include_minor else "unavailable",
            "minor_model_count": 0,
            "collection_metric_status": "unavailable",
            "collection_metric_count": 0,
        }
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
            self._enrich_generation_counts(items, info, warnings, metadata)
            return items, info, warnings, metadata

        metadata["creator_models_available"] = True
        metadata["creator_model_count"] = len(creator_models)

        if not self.config.include_minor:
            enriched = self._enrich_collection_counts(items, creator_models)
            metadata["collection_metric_count"] = enriched
            metadata["collection_metric_status"] = "success" if enriched == len(items) else "partial"
            info.append(f"Loaded collection metrics for {enriched} creator models.")
            self._enrich_generation_counts(items, info, warnings, metadata)
            return items, info, warnings, metadata

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
        metadata["minor_model_count"] = len(missing_ids) - len(failed_ids)
        metadata["minor_discovery_status"] = "partial" if failed_ids else "success"
        metadata["collection_metric_count"] = enriched
        metadata["collection_metric_status"] = "success" if enriched == len(items) else "partial"
        info.append(f"Loaded collection metrics for {enriched} creator models.")
        info.append(
            f"Minor-model discovery found {len(missing_ids)} additional creator models."
        )
        if failed_ids:
            warnings.append(
                f"Could not load {len(failed_ids)} additional minor models. "
                "Saved the models that were available."
            )
        self._enrich_generation_counts(items, info, warnings, metadata)
        return items, info, warnings, metadata

    def fetch_creator(self, username: str) -> dict | None:
        payload = self.get_json(
            f"{self.config.base_url}/api/v1/creators",
            params={"query": username, "limit": 100},
        )
        for creator in payload.get("items") or []:
            if str(creator.get("username", "")).casefold() == username.casefold():
                return creator
        return None

    def fetch_creators_by_ids(self, user_ids: list[int]) -> dict[int, dict]:
        ids = []
        seen = set()
        for user_id in user_ids:
            parsed = self._safe_optional_int(user_id)
            if parsed is None or parsed <= 0 or parsed in seen:
                continue
            ids.append(parsed)
            seen.add(parsed)
        results: dict[int, dict] = {}
        for start in range(0, len(ids), GENERATION_BATCH_SIZE):
            batch_ids = ids[start:start + GENERATION_BATCH_SIZE]
            batch = self.get_trpc_batch(
                "user.getCreator",
                [{"id": user_id} for user_id in batch_ids],
            )
            for user_id, result in zip(batch_ids, batch):
                if isinstance(result, dict):
                    result_id = self._safe_optional_int(result.get("id")) or user_id
                    results[result_id] = result
            if start + GENERATION_BATCH_SIZE < len(ids):
                time.sleep(GENERATION_BATCH_DELAY_SECONDS)
        return results

    def fetch_following_user_ids(self) -> list[int]:
        payload = self.get_json(f"{self.config.base_url}/api/trpc/user.getFollowingUsers")
        result = self._trpc_result(payload, "CivitAI rejected the following-users request.")
        if not isinstance(result, list):
            raise CivitaiError("CivitAI returned an unexpected following-users response.")
        return [
            parsed for parsed in (self._safe_optional_int(item) for item in result)
            if parsed is not None and parsed > 0
        ]

    def toggle_follow_user(self, user_id: int) -> dict:
        result = self.post_trpc("user.toggleFollow", {"targetUserId": int(user_id)})
        return result if isinstance(result, dict) else {}

    def set_blocked_user(self, user_id: int, blocked: bool) -> dict:
        result = self.post_trpc(
            "hiddenPreferences.toggleHidden",
            {"kind": "blockedUser", "data": [{"id": int(user_id)}], "hidden": bool(blocked)},
        )
        return result if isinstance(result, dict) else {}

    def fetch_user_profile(self, username: str) -> dict | None:
        result = self.get_trpc_batch("userProfile.get", [{"username": username}])[0]
        return result if isinstance(result, dict) else None

    def fetch_creator_articles(self, username: str) -> tuple[list[dict], list[str]]:
        url = f"{self.config.base_url}/api/trpc/article.getInfinite"
        items: list[dict] = []
        info: list[str] = []
        cursor = None
        visited_cursors: set[str] = set()
        for page_number in range(1, self.config.max_pages + 1):
            query = {
                "username": username,
                "period": "AllTime",
                "sort": "Newest",
                "limit": 100,
            }
            if cursor is not None:
                query["cursor"] = cursor
            payload = self.get_json(
                f"{url}?{urlencode({'input': json.dumps({'json': query}, separators=(',', ':'))})}"
            )
            result = self._trpc_result(payload, "CivitAI rejected the article request.")
            result = result if isinstance(result, dict) else {}
            page_items = result.get("items") or []
            if not isinstance(page_items, list):
                raise CivitaiError("CivitAI returned an unexpected article list.")
            items.extend(item for item in page_items if isinstance(item, dict))
            info.append(f"Fetched article page {page_number}: {len(page_items)} articles.")
            cursor = result.get("nextCursor")
            if not cursor or not page_items:
                break
            cursor_key = json.dumps(cursor, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            if cursor_key in visited_cursors:
                raise CivitaiError("CivitAI article pagination repeated unexpectedly.")
            visited_cursors.add(cursor_key)
        else:
            info.append(f"Stopped article sync at configured page limit ({self.config.max_pages}).")
        return items, info

    def fetch_model_version_images(
        self,
        model_version_id: int,
        pages: int = 1,
        limit: int = 100,
        with_meta: bool = False,
    ) -> tuple[list[dict], int]:
        url = f"{self.config.base_url}/api/v1/images"
        params = {
            "modelVersionId": model_version_id,
            "limit": min(200, max(1, limit)),
            "browsingLevel": 31,
            "withMeta": str(bool(with_meta)).lower(),
        }
        items: list[dict] = []
        visited: set[str] = set()
        fetched_pages = 0
        for _ in range(min(self.config.max_pages, max(1, pages))):
            payload = self.get_json(url, params=params)
            fetched_pages += 1
            page_items = payload.get("items") or []
            if not isinstance(page_items, list):
                raise CivitaiError("CivitAI returned an unexpected images list.")
            items.extend(item for item in page_items if isinstance(item, dict))
            next_page = (payload.get("metadata") or {}).get("nextPage")
            if not next_page or not page_items:
                break
            next_url = urljoin(f"{self.config.base_url}/", str(next_page))
            if next_url in visited:
                raise CivitaiError("CivitAI image pagination repeated a page unexpectedly.")
            visited.add(next_url)
            url = next_url
            params = None
        return items, fetched_pages

    def fetch_image_by_id(self, image_id: int) -> dict | None:
        payload = self.get_json(
            f"{self.config.base_url}/api/v1/images",
            params={"imageId": int(image_id), "limit": 1, "browsingLevel": 31},
        )
        items = payload.get("items") or []
        if not isinstance(items, list):
            raise CivitaiError("CivitAI returned an unexpected image detail response.")
        for item in items:
            if isinstance(item, dict) and int(item.get("id") or 0) == int(image_id):
                return item
        return None

    def fetch_images_by_ids(self, image_ids: list[int]) -> list[dict]:
        ids = [int(image_id) for image_id in image_ids if int(image_id or 0) > 0]
        if not ids:
            return []
        query = {
            "ids": ids[:200],
            "limit": min(200, len(ids)),
            "browsingLevel": 31,
            "include": [],
        }
        url = (
            f"{self.config.base_url}/api/trpc/image.getInfinite?"
            f"{urlencode({'input': json.dumps({'json': query}, separators=(',', ':'))})}"
        )
        payload = self.get_json(url)
        result = self._trpc_result(payload, "CivitAI rejected the image stats request.")
        items = (result or {}).get("items") if isinstance(result, dict) else []
        if not isinstance(items, list):
            raise CivitaiError("CivitAI returned an unexpected image stats response.")
        return [item for item in items if isinstance(item, dict)]

    def fetch_hidden_preferences(self) -> dict:
        payload = self.get_json(f"{self.config.base_url}/api/trpc/hiddenPreferences.getHidden")
        result = ((payload.get("result") or {}).get("data") or {}).get("json")
        if not isinstance(result, dict):
            raise CivitaiError("CivitAI returned an unexpected hidden preferences response.")
        return result

    def fetch_image_comments(self, image_id: int, limit: int = 20) -> dict:
        query = {
            "entityId": int(image_id),
            "entityType": "image",
            "limit": min(100, max(1, int(limit))),
            "sort": "Newest",
            "hidden": False,
        }
        url = (
            f"{self.config.base_url}/api/trpc/commentv2.getInfinite?"
            f"{urlencode({'input': json.dumps({'json': query}, separators=(',', ':'))})}"
        )
        payload = self.get_json(url)
        result = self._trpc_result(payload, "CivitAI rejected the comments request.")
        return result if isinstance(result, dict) else {"comments": [], "nextCursor": None}

    def fetch_comment_by_id(self, comment_id: int) -> dict | None:
        result = self.get_trpc_batch("commentv2.getSingle", [{"id": int(comment_id)}])[0]
        return result if isinstance(result, dict) else None

    def fetch_legacy_comment_by_id(self, comment_id: int) -> dict | None:
        result = self.get_trpc_batch("comment.getById", [{"id": int(comment_id)}])[0]
        return result if isinstance(result, dict) else None

    def fetch_comment_reply_count(self, comment_id: int) -> int:
        result = self.get_trpc_batch(
            "commentv2.getCount",
            [{"entityId": int(comment_id), "entityType": "comment"}],
        )[0]
        try:
            return int(result or 0)
        except (TypeError, ValueError):
            return 0

    def fetch_legacy_comment_reply_count(self, comment_id: int) -> int:
        result = self.get_trpc_batch("comment.getCommentsCount", [{"id": int(comment_id)}])[0]
        try:
            return int(result or 0)
        except (TypeError, ValueError):
            return 0

    def fetch_comment_replies(
        self,
        comment_id: int,
        limit: int = 100,
        max_pages: int | None = None,
    ) -> list[dict]:
        max_pages = max_pages or self.config.max_pages
        url = f"{self.config.base_url}/api/trpc/commentv2.getInfinite"
        cursor = None
        items: list[dict] = []
        visited_cursors: set[str] = set()
        for _ in range(max(1, max_pages)):
            query = {
                "entityId": int(comment_id),
                "entityType": "comment",
                "limit": min(100, max(1, int(limit))),
                "sort": "Oldest",
                "hidden": False,
            }
            if cursor is not None:
                query["cursor"] = cursor
            payload = self.get_json(
                f"{url}?{urlencode({'input': json.dumps({'json': query}, separators=(',', ':'))})}"
            )
            result = self._trpc_result(payload, "CivitAI rejected the comment replies request.")
            if not isinstance(result, dict):
                break
            page_items = result.get("comments") or []
            if not isinstance(page_items, list):
                raise CivitaiError("CivitAI returned an unexpected comment replies response.")
            items.extend(item for item in page_items if isinstance(item, dict))
            cursor = result.get("nextCursor")
            if not cursor or not page_items:
                break
            cursor_key = json.dumps(cursor, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            if cursor_key in visited_cursors:
                raise CivitaiError("CivitAI comment reply pagination repeated unexpectedly.")
            visited_cursors.add(cursor_key)
        return items

    def fetch_legacy_comment_replies(self, comment_id: int) -> list[dict]:
        result = self.get_trpc_batch("comment.getCommentsById", [{"id": int(comment_id)}])[0]
        if result is None:
            return []
        if not isinstance(result, list):
            raise CivitaiError("CivitAI returned an unexpected legacy comment replies response.")
        return [item for item in result if isinstance(item, dict)]

    def fetch_legacy_comments_by_user(
        self,
        user_id: int,
        limit: int = 100,
        max_pages: int | None = None,
    ) -> list[dict]:
        max_pages = max_pages or self.config.max_pages
        cursor = None
        items: list[dict] = []
        visited_cursors: set[str] = set()
        for _ in range(max(1, max_pages)):
            query = {"userId": int(user_id), "limit": min(200, max(1, int(limit)))}
            if cursor is not None:
                query["cursor"] = cursor
            result = self.get_trpc_batch("comment.getAll", [query])[0]
            if not isinstance(result, dict):
                break
            page_items = result.get("comments") or []
            if not isinstance(page_items, list):
                raise CivitaiError("CivitAI returned an unexpected user comment response.")
            items.extend(item for item in page_items if isinstance(item, dict))
            cursor = result.get("nextCursor")
            if not cursor or not page_items:
                break
            cursor_key = str(cursor)
            if cursor_key in visited_cursors:
                raise CivitaiError("CivitAI user comment pagination repeated unexpectedly.")
            visited_cursors.add(cursor_key)
        return items

    def fetch_image_comment_count(self, image_id: int) -> int:
        query = {"entityId": int(image_id), "entityType": "image", "hidden": False}
        url = (
            f"{self.config.base_url}/api/trpc/commentv2.getCount?"
            f"{urlencode({'input': json.dumps({'json': query}, separators=(',', ':'))})}"
        )
        payload = self.get_json(url)
        result = self._trpc_result(payload, "CivitAI rejected the comment count request.")
        try:
            return int(result or 0)
        except (TypeError, ValueError):
            return 0

    def post_image_comment(self, image_id: int, content: str) -> dict:
        result = self.post_trpc(
            "commentv2.upsert",
            {
                "entityId": int(image_id),
                "entityType": "image",
                "content": content,
                "hidden": False,
            },
        )
        return result if isinstance(result, dict) else {}

    def post_comment_reply(self, comment_id: int, parent_thread_id: int, content: str) -> dict:
        result = self.post_trpc(
            "commentv2.upsert",
            {
                "entityId": int(comment_id),
                "entityType": "comment",
                "parentThreadId": int(parent_thread_id),
                "content": content,
                "hidden": False,
            },
        )
        return result if isinstance(result, dict) else {}
