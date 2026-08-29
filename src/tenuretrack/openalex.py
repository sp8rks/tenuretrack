"""A small, cached, polite client for the OpenAlex REST API.

Design rules that come from `.claude/skills/openalex-api` and CLAUDE.md:

- Every request carries `mailto`, read from `OPENALEX_MAILTO`. Network stages
  refuse to start without it, and no address is ever hardcoded.
- Every GET is cached on disk under `.cache/`, keyed by a hash of the request.
  A cache hit never touches the network, so a run killed by quota restarts with
  zero repeated requests.
- 429 is quota, not a transient error. If the server asks for more than 60 s,
  we raise `QuotaExhausted` with the reset time instead of sleeping.
- 5xx and transport failures retry with exponential backoff, at most 5 tries,
  with each sleep capped at 60 s.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import httpx

__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_CACHE_DIR",
    "MAX_RETRY_SLEEP",
    "MailtoNotConfigured",
    "OpenAlexClient",
    "OpenAlexError",
    "OpenAlexHTTPError",
    "QuotaExhausted",
    "api_key_from_env",
    "mailto_from_env",
]

DEFAULT_BASE_URL = "https://api.openalex.org"
DEFAULT_CACHE_DIR = Path(".cache")
DEFAULT_PER_PAGE = 200
DEFAULT_MAX_TRIES = 5
DEFAULT_REQUESTS_PER_SECOND = 10.0
DEFAULT_TIMEOUT = 30.0
MAX_RETRY_SLEEP = 60.0
"""Never sleep longer than this inside a retry. Anything longer is quota."""

MAILTO_ENV_VAR = "OPENALEX_MAILTO"
API_KEY_ENV_VAR = "OPENALEX_API_KEY"

FREE_KEYLESS_BUDGET = 1000
"""Requests a day without a key, measured against the live API in August 2026.

OpenAlex moved to a spending budget: every call costs about $0.0001, a caller
with only a `mailto` gets $0.10 a day, and a free account key gets ten times
that. The daily budget resets at midnight UTC. This constant is documentation,
not a limit the client enforces; the server is the authority.
"""
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class OpenAlexError(RuntimeError):
    """Base class for every failure raised by this module."""


class MailtoNotConfigured(OpenAlexError):
    """`OPENALEX_MAILTO` is unset or does not look like an email address."""


class OpenAlexHTTPError(OpenAlexError):
    """A non-retryable HTTP error, or a 5xx that survived every retry."""

    def __init__(self, status_code: int, url: str, body: str = "") -> None:
        self.status_code = status_code
        self.url = url
        self.body = body[:400]
        detail = f": {self.body}" if self.body else ""
        super().__init__(f"OpenAlex returned {status_code} for {url}{detail}")


class QuotaExhausted(OpenAlexError):
    """The daily or per-second quota is spent and the wait is too long.

    The caller should write partial results and exit nonzero. Everything already
    fetched is in the cache, so the rerun costs no repeated requests.
    """

    def __init__(
        self,
        url: str,
        retry_after: float | None = None,
        reset_at: _dt.datetime | None = None,
        *,
        has_api_key: bool = True,
        budget_limit: int | None = None,
    ) -> None:
        self.url = url
        self.retry_after = retry_after
        self.reset_at = reset_at
        self.has_api_key = has_api_key
        self.budget_limit = budget_limit
        parts = [f"OpenAlex daily budget spent on {url}"]
        if budget_limit is not None:
            parts.append(f"the budget was {budget_limit} requests")
        if retry_after is not None:
            parts.append(f"the server asked for {retry_after:.0f} s")
        if reset_at is not None:
            parts.append(f"it resets at {reset_at.isoformat(timespec='seconds')}")
        parts.append(
            "everything fetched so far is cached, so rerunning repeats no requests"
        )
        message = "; ".join(parts)
        if not has_api_key:
            message += (
                f"\n\nWithout an API key the budget is about {FREE_KEYLESS_BUDGET} "
                "requests a day, which one cohort build can spend. A free account "
                "key raises it tenfold: make an account at openalex.org, copy the "
                "key from openalex.org/settings/api, and set "
                f"{API_KEY_ENV_VAR}=your-key. It costs nothing."
            )
        super().__init__(message)


def mailto_from_env(env: Mapping[str, str] | None = None) -> str:
    """Read the polite-pool contact address, or explain how to set it."""
    env = os.environ if env is None else env
    value = (env.get(MAILTO_ENV_VAR) or "").strip()
    if not value:
        raise MailtoNotConfigured(
            f"{MAILTO_ENV_VAR} is not set. OpenAlex asks every caller to identify "
            "itself, and the polite pool is faster and more reliable. Set it with "
            f"`export {MAILTO_ENV_VAR}=you@university.edu` before running any stage "
            "that touches the network."
        )
    if not _EMAIL_RE.match(value):
        raise MailtoNotConfigured(
            f"{MAILTO_ENV_VAR}={value!r} does not look like an email address."
        )
    return value


def api_key_from_env(env: Mapping[str, str] | None = None) -> str | None:
    """Read an optional OpenAlex API key.

    A key is not needed to run, but without one the daily budget is about
    `FREE_KEYLESS_BUDGET` requests, which a single cohort build can spend. A
    free account key raises it tenfold. Absent is a normal state, so this
    returns None rather than raising.
    """
    env = os.environ if env is None else env
    value = (env.get(API_KEY_ENV_VAR) or "").strip()
    return value or None


class OpenAlexClient:
    """Cached GET access to `api.openalex.org`.

    Every knob that touches time is injectable so tests run without sleeping and
    without a network.
    """

    def __init__(
        self,
        mailto: str | None = None,
        cache_dir: str | Path = DEFAULT_CACHE_DIR,
        *,
        base_url: str = DEFAULT_BASE_URL,
        max_tries: int = DEFAULT_MAX_TRIES,
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        timeout: float = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], _dt.datetime] = lambda: _dt.datetime.now(_dt.UTC),
        user_agent: str = "tenuretrack",
        api_key: str | None = None,
    ) -> None:
        self.mailto = mailto if mailto is not None else mailto_from_env()
        self.api_key = api_key if api_key is not None else api_key_from_env()
        self.cache_dir = Path(cache_dir)
        self.base_url = base_url.rstrip("/")
        self.max_tries = max(1, int(max_tries))
        self.min_interval = 1.0 / requests_per_second if requests_per_second > 0 else 0.0
        self._sleep = sleep
        self._monotonic = monotonic
        self._now = now
        self._last_request_at: float | None = None
        self.request_count = 0
        """Requests that actually went over the wire. Print this while running."""
        self.cache_hits = 0
        self.budget_limit: int | None = None
        self.budget_remaining: int | None = None
        """Daily budget as the server last reported it, or None before any live
        request. Cache hits never update these, because they cost nothing."""

        headers = {"User-Agent": f"{user_agent} (mailto:{self.mailto})"}
        if self.api_key:
            # A header, not a query parameter: it keeps the key out of the cache
            # key, out of any logged URL, and out of the on-disk cache envelope.
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------ cache

    def cache_key(self, path: str, params: Mapping[str, Any] | None = None) -> str:
        """Hash of the request, ignoring `mailto`.

        `mailto` is politeness metadata, not part of what was asked, so two users
        of the same machine share cache entries instead of refetching.
        """
        canonical = json.dumps(
            {
                "method": "GET",
                "url": self._url(path),
                "params": _canonical_params(params),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> dict | None:
        path = self.cache_path(key)
        if not path.is_file():
            return None
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        body = envelope.get("body")
        return body if isinstance(body, dict) else None

    def _write_cache(self, key: str, path: str, params: Mapping[str, Any], body: dict) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        envelope = {
            "url": self._url(path),
            "params": _canonical_params(params),
            "fetched_at": self._now().isoformat(timespec="seconds"),
            "body": body,
        }
        target = self.cache_path(key)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(envelope), encoding="utf-8")
        os.replace(tmp, target)

    # ----------------------------------------------------------------- public

    def get(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        refresh: bool = False,
    ) -> dict:
        """GET a single OpenAlex URL, from cache when possible."""
        params = dict(params or {})
        key = self.cache_key(path, params)
        if not refresh:
            cached = self._read_cache(key)
            if cached is not None:
                self.cache_hits += 1
                return cached
        body = self._fetch(path, params)
        self._write_cache(key, path, params, body)
        return body

    def paginate(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
        *,
        per_page: int = DEFAULT_PER_PAGE,
        refresh: bool = False,
    ) -> Iterator[dict]:
        """Yield every result across cursor pages.

        Cursor pagination is the only form that works past 10,000 results, and
        each page is cached under its own cursor, so a resumed run replays the
        pages it already has for free.
        """
        base = dict(params or {})
        base["per-page"] = per_page
        cursor: str | None = "*"
        seen: set[str] = set()
        while cursor:
            if cursor in seen:
                raise OpenAlexError(
                    f"OpenAlex repeated cursor {cursor!r} on {path}; stopping to "
                    "avoid an endless loop"
                )
            seen.add(cursor)
            page = self.get(path, {**base, "cursor": cursor}, refresh=refresh)
            results = page.get("results") or []
            yield from results
            if not results:
                return
            meta = page.get("meta") or {}
            cursor = meta.get("next_cursor")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenAlexClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ---------------------------------------------------------------- network

    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.base_url}/{path.lstrip('/')}"

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        if self._last_request_at is not None:
            wait = self.min_interval - (self._monotonic() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._monotonic()

    def _fetch(self, path: str, params: Mapping[str, Any]) -> dict:
        url = self._url(path)
        query = {**_canonical_params(params), "mailto": self.mailto}
        last_error: Exception | None = None

        for attempt in range(1, self.max_tries + 1):
            self._throttle()
            try:
                response = self._client.get(url, params=query)
            except httpx.TransportError as exc:
                self.request_count += 1
                last_error = exc
                if attempt == self.max_tries:
                    raise OpenAlexError(
                        f"could not reach OpenAlex at {url} after "
                        f"{self.max_tries} tries: {exc}"
                    ) from exc
                self._sleep(_backoff(attempt))
                continue

            self.request_count += 1
            status = response.status_code
            self._note_budget(response)

            if status == 200:
                try:
                    body = response.json()
                except ValueError as exc:
                    raise OpenAlexError(
                        f"OpenAlex returned a non-JSON body for {url}"
                    ) from exc
                if not isinstance(body, dict):
                    raise OpenAlexError(
                        f"OpenAlex returned {type(body).__name__}, expected an object, "
                        f"for {url}"
                    )
                return body

            if status == 429:
                retry_after = _retry_after_seconds(response, self._now())
                if (
                    retry_after is not None and retry_after > MAX_RETRY_SLEEP
                ) or attempt == self.max_tries:
                    raise self._quota_exhausted(url, retry_after)
                delay = retry_after if retry_after is not None else _backoff(attempt)
                self._sleep(min(delay, MAX_RETRY_SLEEP))
                continue

            if 500 <= status < 600:
                last_error = OpenAlexHTTPError(status, url, response.text)
                if attempt == self.max_tries:
                    raise last_error
                self._sleep(_backoff(attempt))
                continue

            raise OpenAlexHTTPError(status, url, response.text)

        raise OpenAlexError(f"exhausted retries for {url}: {last_error}")

    def _note_budget(self, response: httpx.Response) -> None:
        """Remember the daily budget the server just reported."""
        self.budget_limit = _header_int(response, "x-ratelimit-limit", self.budget_limit)
        self.budget_remaining = _header_int(
            response, "x-ratelimit-remaining", self.budget_remaining
        )

    def _quota_exhausted(self, url: str, retry_after: float | None) -> QuotaExhausted:
        return QuotaExhausted(
            url,
            retry_after,
            self._reset_at(retry_after),
            has_api_key=bool(self.api_key),
            budget_limit=self.budget_limit,
        )

    def _reset_at(self, retry_after: float | None) -> _dt.datetime | None:
        if retry_after is None:
            return None
        return self._now() + _dt.timedelta(seconds=retry_after)


def _header_int(response: httpx.Response, name: str, fallback: int | None) -> int | None:
    raw = response.headers.get(name)
    if raw is None:
        return fallback
    try:
        return int(float(raw.strip()))
    except ValueError:
        return fallback


def _backoff(attempt: int) -> float:
    """1, 2, 4, 8 ... seconds, capped. Deterministic so tests can assert it."""
    return min(2.0 ** (attempt - 1), MAX_RETRY_SLEEP)


def _canonical_params(params: Mapping[str, Any] | None) -> dict[str, str]:
    """Stable string form of a query, so the cache key is stable too."""
    if not params:
        return {}
    out: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[str(key)] = "true" if value else "false"
        elif isinstance(value, (list, tuple)):
            out[str(key)] = "|".join(str(v) for v in value)
        else:
            out[str(key)] = str(value)
    return dict(sorted(out.items()))


def _retry_after_seconds(
    response: httpx.Response, now: _dt.datetime
) -> float | None:
    """Parse `Retry-After`, which is either seconds or an HTTP date."""
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime

        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.UTC)
    return max(0.0, (when - now).total_seconds())
