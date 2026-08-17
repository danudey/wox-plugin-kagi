"""Minimal Kagi HTTP client built on the standard library only.

Two groups of endpoints are used:

* `kagisuggest.com` autocomplete, which is free and needs no credentials.
* The `kagi.com/api` endpoints, which need an API key and consume paid credits.
  Everything in that second group is opt in, see `settings.py`.
"""

from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

USER_AGENT = "Wox-Plugin-Kagi/1.0 (+https://github.com/danudey/wox-plugin-kagi)"

AUTOSUGGEST_URL = "https://kagisuggest.com/api/autosuggest"
API_BASE = "https://kagi.com/api"


class KagiError(Exception):
    """Any failure while talking to Kagi, already formatted for display."""


@dataclass
class SearchItem:
    """One search style result returned by the Search or Enrichment APIs."""

    title: str
    url: str
    snippet: str = ""
    published: str = ""


@dataclass
class Answer:
    """A generated answer, from FastGPT or from the Universal Summarizer."""

    output: str
    references: List[SearchItem] = field(default_factory=list)


class _TTLCache:
    """Tiny time based cache, enough to stop repeated keystrokes hitting Kagi."""

    def __init__(self, ttl_seconds: float = 120.0, max_entries: int = 128) -> None:
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._entries: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._entries.get(key)
        if entry is None:
            return None

        expires_at, value = entry
        if expires_at < time.monotonic():
            self._entries.pop(key, None)
            return None

        return value

    def set(self, key: str, value: Any) -> None:
        if len(self._entries) >= self._max_entries:
            oldest = min(self._entries, key=lambda item: self._entries[item][0])
            self._entries.pop(oldest, None)

        self._entries[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        self._entries.clear()


def _read_json(url: str, headers: Dict[str, str], timeout: float, data: Optional[bytes] = None) -> Any:
    """Blocking JSON fetch. Always called through `asyncio.to_thread`."""

    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        detail = _http_error_detail(error)
        raise KagiError(f"Kagi returned HTTP {error.code}{detail}") from error
    except urllib.error.URLError as error:
        raise KagiError(f"Could not reach Kagi: {error.reason}") from error
    except TimeoutError as error:
        raise KagiError("Kagi did not answer in time") from error

    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise KagiError("Kagi returned a response that could not be parsed") from error


def _http_error_detail(error: urllib.error.HTTPError) -> str:
    """Pull the human readable message out of a Kagi API error body, if there is one."""

    try:
        payload = json.loads(error.read().decode("utf-8", errors="replace"))
    except Exception:
        return ""

    errors = payload.get("error") or payload.get("errors") or []
    if isinstance(errors, dict):
        errors = [errors]

    messages = [str(item.get("msg") or item.get("message") or "") for item in errors if isinstance(item, dict)]
    messages = [message for message in messages if message]
    if not messages:
        return ""

    return f": {messages[0]}"


def _coerce_items(payload: Any) -> List[SearchItem]:
    """Normalise the several shapes Kagi uses for lists of search results."""

    if isinstance(payload, dict):
        for key in ("results", "data", "items"):
            if key in payload:
                return _coerce_items(payload[key])
        return []

    if not isinstance(payload, list):
        return []

    items: List[SearchItem] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue

        # `t` is the object type in the v0 APIs. Type 1 is the "related searches"
        # bucket rather than a result, so it is skipped.
        if entry.get("t") == 1:
            continue

        url = str(entry.get("url") or "")
        title = str(entry.get("title") or "")
        if not url or not title:
            continue

        items.append(
            SearchItem(
                title=title,
                url=url,
                snippet=str(entry.get("snippet") or entry.get("description") or ""),
                published=str(entry.get("published") or ""),
            )
        )

    return items


class KagiClient:
    """Async wrapper over the Kagi endpoints used by the plugin."""

    def __init__(self, api_key: str = "", timeout: float = 6.0) -> None:
        self.api_key = api_key.strip()
        self.timeout = timeout
        self._suggest_cache = _TTLCache(ttl_seconds=300.0)
        self._api_cache = _TTLCache(ttl_seconds=900.0)

    def configure(self, api_key: str, timeout: float) -> None:
        """Apply new settings, dropping cached API answers if the key changed."""

        api_key = api_key.strip()
        if api_key != self.api_key:
            self._api_cache.clear()

        self.api_key = api_key
        self.timeout = timeout

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def _auth_headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise KagiError("No Kagi API key configured")

        return {"Authorization": f"Bot {self.api_key}"}

    async def autosuggest(self, term: str, limit: int) -> List[str]:
        """Fetch Kagi autocomplete suggestions. Free, no API key needed."""

        term = term.strip()
        if not term or limit <= 0:
            return []

        cached = self._suggest_cache.get(term)
        if cached is None:
            url = f"{AUTOSUGGEST_URL}?{urllib.parse.urlencode({'q': term})}"
            payload = await asyncio.to_thread(_read_json, url, {}, self.timeout)

            # OpenSearch suggestion format: ["term", ["suggestion", ...], ...]
            cached = []
            if isinstance(payload, list) and len(payload) > 1 and isinstance(payload[1], list):
                cached = [str(item) for item in payload[1] if str(item).strip()]

            self._suggest_cache.set(term, cached)

        return [suggestion for suggestion in cached if suggestion.lower() != term.lower()][:limit]

    async def search(self, term: str, limit: int) -> List[SearchItem]:
        """Run a paid Search API query."""

        return await self._cached_items("search", term, limit, self._search_uncached)

    async def _search_uncached(self, term: str, limit: int) -> List[SearchItem]:
        body = json.dumps({"q": term, "limit": limit}).encode("utf-8")
        headers = {**self._auth_headers(), "Content-Type": "application/json"}

        try:
            payload = await asyncio.to_thread(_read_json, f"{API_BASE}/v1/search", headers, self.timeout, body)
        except KagiError:
            # v1 is the current Search API. Older keys and accounts are still served
            # by the v0 endpoint, so fall back rather than failing outright.
            query = urllib.parse.urlencode({"q": term, "limit": limit})
            payload = await asyncio.to_thread(_read_json, f"{API_BASE}/v0/search?{query}", self._auth_headers(), self.timeout)

        return _coerce_items(payload.get("data") if isinstance(payload, dict) else payload)[:limit]

    async def enrich(self, index: str, term: str, limit: int) -> List[SearchItem]:
        """Query the Enrichment API. `index` is "web" for small web or "news"."""

        async def fetch(query: str, count: int) -> List[SearchItem]:
            encoded = urllib.parse.urlencode({"q": query})
            payload = await asyncio.to_thread(_read_json, f"{API_BASE}/v0/enrich/{index}?{encoded}", self._auth_headers(), self.timeout)
            return _coerce_items(payload.get("data") if isinstance(payload, dict) else payload)[:count]

        return await self._cached_items(f"enrich:{index}", term, limit, fetch)

    async def fastgpt(self, question: str) -> Answer:
        """Ask FastGPT. Each uncached call costs credits."""

        cache_key = f"fastgpt:{question}"
        cached = self._api_cache.get(cache_key)
        if cached is not None:
            return cached

        body = json.dumps({"query": question}).encode("utf-8")
        headers = {**self._auth_headers(), "Content-Type": "application/json"}
        payload = await asyncio.to_thread(_read_json, f"{API_BASE}/v0/fastgpt", headers, self.timeout, body)

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise KagiError("FastGPT returned no answer")

        answer = Answer(output=str(data.get("output") or "").strip(), references=_coerce_items(data.get("references")))
        self._api_cache.set(cache_key, answer)
        return answer

    async def summarize(
        self,
        target: str,
        engine: str = "cecil",
        summary_type: str = "summary",
        target_language: str = "",
        is_url: bool = True,
    ) -> Answer:
        """Summarize a URL or a block of text. Each uncached call costs credits."""

        cache_key = f"summarize:{engine}:{summary_type}:{target_language}:{target}"
        cached = self._api_cache.get(cache_key)
        if cached is not None:
            return cached

        params: Dict[str, str] = {
            "url" if is_url else "text": target,
            "engine": engine,
            "summary_type": summary_type,
        }
        if target_language:
            params["target_language"] = target_language

        body = json.dumps(params).encode("utf-8")
        headers = {**self._auth_headers(), "Content-Type": "application/json"}
        payload = await asyncio.to_thread(_read_json, f"{API_BASE}/v0/summarize", headers, self.timeout, body)

        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise KagiError("The summarizer returned no output")

        answer = Answer(output=str(data.get("output") or "").strip())
        self._api_cache.set(cache_key, answer)
        return answer

    async def _cached_items(self, namespace: str, term: str, limit: int, fetch: Any) -> List[SearchItem]:
        cache_key = f"{namespace}:{limit}:{term}"
        cached = self._api_cache.get(cache_key)
        if cached is not None:
            return cached

        items = await fetch(term, limit)
        self._api_cache.set(cache_key, items)
        return items
