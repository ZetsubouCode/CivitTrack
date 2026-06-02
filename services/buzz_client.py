import json
import time

import requests

from .civitai_client import CivitaiClient, CivitaiError
from .config import Config, get_config


class BuzzClientError(RuntimeError):
    pass


class BuzzClient:
    def __init__(self, config: Config | None = None):
        self.config = config or get_config()
        self.client = CivitaiClient(self.config)

    def call_trpc(
        self, procedure: str, input_json: dict | None, input_meta: dict | None = None
    ) -> dict | list:
        url = f"{self.config.base_url}/api/trpc/{procedure}"
        payload = {"json": input_json or {}}
        if input_meta:
            payload["meta"] = {"values": input_meta, "v": 1}
        params = {
            "input": json.dumps(payload, separators=(",", ":"))
        }
        for attempt in range(3):
            try:
                response = self.client.session.get(
                    url,
                    params=params,
                    headers=self.client.get_auth_headers(),
                    timeout=self.config.timeout_seconds,
                )
            except requests.Timeout as exc:
                raise BuzzClientError("The CivitAI Buzz request timed out. Try again later.") from exc
            except requests.RequestException as exc:
                raise BuzzClientError("Could not connect to the CivitAI Buzz API. Try again later.") from exc

            if response.status_code in (401, 403):
                raise BuzzClientError(
                    "Buzz tracking is unavailable. Your API key may not have BuzzRead access, "
                    "or CivitAI changed the endpoint."
                )
            if response.status_code == 404:
                raise BuzzClientError(
                    "Buzz endpoint was not found. CivitAI may have changed the API."
                )
            if response.status_code == 429:
                raise BuzzClientError("CivitAI rate limited the Buzz request.")
            if response.status_code >= 500 and attempt < 2:
                time.sleep(0.5 * (attempt + 1))
                continue
            if not response.ok:
                raise BuzzClientError(
                    f"CivitAI Buzz API returned HTTP {response.status_code}."
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise BuzzClientError(
                    "CivitAI returned an unexpected Buzz response."
                ) from exc
            if not isinstance(payload, dict):
                raise BuzzClientError("CivitAI returned an unexpected Buzz response.")
            if payload.get("error"):
                raise BuzzClientError(
                    "Buzz tracking is unavailable. API key may not have BuzzRead access, "
                    "or CivitAI changed the endpoint."
                )
            result = payload.get("result")
            data = result.get("data") if isinstance(result, dict) else None
            if not isinstance(data, dict) or "json" not in data:
                raise BuzzClientError("CivitAI returned an unexpected Buzz response.")
            decoded = data["json"]
            if not isinstance(decoded, (dict, list)):
                raise BuzzClientError("CivitAI returned an unexpected Buzz response.")
            return decoded
        raise BuzzClientError("The CivitAI Buzz API is temporarily unavailable.")

    def fetch_buzz_accounts(self) -> dict | list:
        return self.call_trpc("buzz.getBuzzAccount", {})

    def fetch_buzz_transactions(self, account_type: str, limit: int = 200) -> dict | list:
        remaining = min(500, max(1, limit))
        transactions = []
        cursor = None
        visited_cursors = set()
        while remaining > 0:
            query = {
                # The router replaces this with the authenticated user's id, but its
                # input schema still requires the field.
                "accountId": 0,
                "accountType": account_type.lower(),
                "limit": min(200, remaining),
                "descending": True,
            }
            meta = None
            if cursor:
                query["cursor"] = cursor
                meta = {"cursor": ["Date"]}
            page = self.call_trpc("buzz.getAccountTransactions", query, meta)
            if not isinstance(page, dict):
                raise BuzzClientError("CivitAI returned an unexpected Buzz response.")
            page_transactions = page.get("transactions")
            if not isinstance(page_transactions, list):
                raise BuzzClientError("CivitAI returned an unexpected Buzz response.")
            transactions.extend(page_transactions[:remaining])
            remaining -= len(page_transactions)
            next_cursor = page.get("cursor")
            if not page_transactions or not next_cursor or remaining <= 0:
                cursor = next_cursor
                break
            cursor_key = str(next_cursor)
            if cursor_key in visited_cursors:
                raise BuzzClientError("CivitAI repeated a Buzz transaction cursor unexpectedly.")
            visited_cursors.add(cursor_key)
            cursor = next_cursor
        return {"cursor": cursor, "transactions": transactions}

    def fetch_buzz_report(self, account_type: str, window: str = "day") -> dict | list:
        return self.call_trpc(
            "buzz.getTransactionsReport",
            {"accountType": account_type.lower(), "window": window},
        )

    def fetch_image_preview(self, image_id: int) -> dict | None:
        try:
            payload = self.client.get_json(
                f"{self.config.base_url}/api/v1/images",
                params={"imageId": image_id, "limit": 1, "browsingLevel": 31},
            )
        except CivitaiError:
            return None
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                item_id = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            if item_id != image_id:
                continue
            return {
                "image_url": item.get("url") if isinstance(item.get("url"), str) else None,
                "post_id": item.get("postId"),
            }
        return None
