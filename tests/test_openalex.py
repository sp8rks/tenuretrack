"""The cached, polite OpenAlex client. No test here touches the network."""

from __future__ import annotations

import datetime as _dt
import json

import httpx
import pytest

from tenuretrack.openalex import (
    MAILTO_ENV_VAR,
    MAX_RETRY_SLEEP,
    MailtoNotConfigured,
    OpenAlexClient,
    OpenAlexError,
    OpenAlexHTTPError,
    QuotaExhausted,
    mailto_from_env,
)

FIXED_NOW = _dt.datetime(2026, 8, 28, 12, 0, 0, tzinfo=_dt.UTC)


class Recorder:
    """A fake transport that replays canned responses and logs the requests."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError(f"unexpected extra request to {request.url}")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def make_client(tmp_path, responses, sleeps=None, **kwargs):
    recorder = Recorder(responses)
    client = OpenAlexClient(
        mailto="tester@example.edu",
        cache_dir=tmp_path / ".cache",
        transport=recorder.transport,
        requests_per_second=0,  # throttling is exercised in its own test
        sleep=(sleeps.append if sleeps is not None else lambda _seconds: None),
        now=lambda: FIXED_NOW,
        **kwargs,
    )
    return client, recorder


def ok(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


# --------------------------------------------------------------------- mailto


def test_mailto_from_env_reads_the_variable():
    assert mailto_from_env({MAILTO_ENV_VAR: " tester@example.edu "}) == "tester@example.edu"


def test_missing_mailto_refuses_and_explains():
    with pytest.raises(MailtoNotConfigured, match=MAILTO_ENV_VAR):
        mailto_from_env({})


def test_blank_mailto_refuses():
    with pytest.raises(MailtoNotConfigured):
        mailto_from_env({MAILTO_ENV_VAR: "   "})


def test_non_email_mailto_refuses():
    with pytest.raises(MailtoNotConfigured):
        mailto_from_env({MAILTO_ENV_VAR: "not-an-email"})


def test_client_falls_back_to_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(MAILTO_ENV_VAR, "env@example.edu")
    client = OpenAlexClient(cache_dir=tmp_path / ".cache")
    assert client.mailto == "env@example.edu"
    client.close()


def test_client_without_mailto_refuses_to_start(tmp_path):
    with pytest.raises(MailtoNotConfigured):
        OpenAlexClient(cache_dir=tmp_path / ".cache")


# ---------------------------------------------------------------------- get


def test_every_request_carries_mailto(tmp_path):
    client, recorder = make_client(tmp_path, [ok({"id": "A1"})])
    client.get("/authors/A1")
    assert recorder.requests[0].url.params["mailto"] == "tester@example.edu"


def test_second_call_is_served_from_cache(tmp_path):
    client, recorder = make_client(tmp_path, [ok({"id": "A1"})])
    first = client.get("/authors/A1")
    second = client.get("/authors/A1")
    assert first == second == {"id": "A1"}
    assert len(recorder.requests) == 1
    assert client.request_count == 1
    assert client.cache_hits == 1


def test_a_fresh_client_reuses_the_cache_on_disk(tmp_path):
    client, _ = make_client(tmp_path, [ok({"id": "A1"})])
    client.get("/authors/A1")
    resumed, recorder = make_client(tmp_path, [])
    assert resumed.get("/authors/A1") == {"id": "A1"}
    assert recorder.requests == []
    assert resumed.request_count == 0


def test_cache_key_ignores_mailto_but_not_params(tmp_path):
    client, _ = make_client(tmp_path, [])
    other = OpenAlexClient(
        mailto="someone-else@example.edu",
        cache_dir=tmp_path / ".cache",
        transport=httpx.MockTransport(lambda r: ok({})),
    )
    assert client.cache_key("/works", {"filter": "x"}) == other.cache_key(
        "/works", {"filter": "x"}
    )
    assert client.cache_key("/works", {"filter": "x"}) != client.cache_key(
        "/works", {"filter": "y"}
    )
    other.close()


def test_param_order_does_not_change_the_cache_key(tmp_path):
    client, _ = make_client(tmp_path, [])
    assert client.cache_key("/works", {"a": 1, "b": 2}) == client.cache_key(
        "/works", {"b": 2, "a": 1}
    )


def test_refresh_bypasses_the_cache(tmp_path):
    client, recorder = make_client(tmp_path, [ok({"v": 1}), ok({"v": 2})])
    assert client.get("/authors/A1") == {"v": 1}
    assert client.get("/authors/A1", refresh=True) == {"v": 2}
    assert len(recorder.requests) == 2
    assert client.get("/authors/A1") == {"v": 2}


def test_cache_file_is_json_with_the_body_inside(tmp_path):
    client, _ = make_client(tmp_path, [ok({"id": "A1"})])
    client.get("/authors/A1")
    files = list((tmp_path / ".cache").glob("*.json"))
    assert len(files) == 1
    envelope = json.loads(files[0].read_text(encoding="utf-8"))
    assert envelope["body"] == {"id": "A1"}
    assert envelope["url"].endswith("/authors/A1")


def test_a_corrupt_cache_entry_is_refetched(tmp_path):
    client, _ = make_client(tmp_path, [ok({"id": "A1"})])
    client.get("/authors/A1")
    cache_file = next((tmp_path / ".cache").glob("*.json"))
    cache_file.write_text("{not json", encoding="utf-8")
    resumed, recorder = make_client(tmp_path, [ok({"id": "A1"})])
    assert resumed.get("/authors/A1") == {"id": "A1"}
    assert len(recorder.requests) == 1


# --------------------------------------------------------------------- quota


def test_long_retry_after_raises_quota_exhausted_without_sleeping(tmp_path):
    sleeps: list[float] = []
    client, recorder = make_client(
        tmp_path,
        [httpx.Response(429, headers={"Retry-After": "3600"})],
        sleeps=sleeps,
    )
    with pytest.raises(QuotaExhausted) as excinfo:
        client.get("/authors/A1")
    assert sleeps == []
    assert len(recorder.requests) == 1
    assert excinfo.value.retry_after == 3600
    assert excinfo.value.reset_at == FIXED_NOW + _dt.timedelta(seconds=3600)


def test_short_retry_after_is_waited_out(tmp_path):
    sleeps: list[float] = []
    client, recorder = make_client(
        tmp_path,
        [httpx.Response(429, headers={"Retry-After": "5"}), ok({"id": "A1"})],
        sleeps=sleeps,
    )
    assert client.get("/authors/A1") == {"id": "A1"}
    assert sleeps == [5.0]
    assert len(recorder.requests) == 2


def test_retry_after_as_an_http_date_is_parsed(tmp_path):
    sleeps: list[float] = []
    later = FIXED_NOW + _dt.timedelta(seconds=7200)
    header = later.strftime("%a, %d %b %Y %H:%M:%S GMT")
    client, _ = make_client(
        tmp_path, [httpx.Response(429, headers={"Retry-After": header})], sleeps=sleeps
    )
    with pytest.raises(QuotaExhausted) as excinfo:
        client.get("/authors/A1")
    assert excinfo.value.retry_after == pytest.approx(7200, abs=1)
    assert sleeps == []


def test_repeated_429_gives_up_as_quota(tmp_path):
    sleeps: list[float] = []
    client, recorder = make_client(
        tmp_path,
        [httpx.Response(429, headers={"Retry-After": "2"})] * 3,
        sleeps=sleeps,
        max_tries=3,
    )
    with pytest.raises(QuotaExhausted):
        client.get("/authors/A1")
    assert len(recorder.requests) == 3
    assert sleeps == [2.0, 2.0]


def test_429_without_a_header_backs_off(tmp_path):
    sleeps: list[float] = []
    client, _ = make_client(
        tmp_path, [httpx.Response(429), ok({"id": "A1"})], sleeps=sleeps
    )
    assert client.get("/authors/A1") == {"id": "A1"}
    assert sleeps == [1.0]


def test_quota_message_says_the_cache_makes_the_rerun_free(tmp_path):
    client, _ = make_client(
        tmp_path, [httpx.Response(429, headers={"Retry-After": "3600"})]
    )
    with pytest.raises(QuotaExhausted, match="cached"):
        client.get("/authors/A1")


# ------------------------------------------------------------------- retries


def test_server_error_is_retried_then_succeeds(tmp_path):
    sleeps: list[float] = []
    client, recorder = make_client(
        tmp_path, [httpx.Response(503), httpx.Response(502), ok({"id": "A1"})], sleeps=sleeps
    )
    assert client.get("/authors/A1") == {"id": "A1"}
    assert sleeps == [1.0, 2.0]
    assert len(recorder.requests) == 3


def test_server_error_gives_up_after_max_tries(tmp_path):
    client, recorder = make_client(
        tmp_path, [httpx.Response(500)] * 5, max_tries=5
    )
    with pytest.raises(OpenAlexHTTPError) as excinfo:
        client.get("/authors/A1")
    assert excinfo.value.status_code == 500
    assert len(recorder.requests) == 5


def test_retry_sleep_is_capped_at_sixty_seconds(tmp_path):
    sleeps: list[float] = []
    client, _ = make_client(
        tmp_path, [httpx.Response(500)] * 9, sleeps=sleeps, max_tries=9
    )
    with pytest.raises(OpenAlexHTTPError):
        client.get("/authors/A1")
    assert max(sleeps) == MAX_RETRY_SLEEP
    assert sleeps == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]


def test_transport_failure_is_retried(tmp_path):
    client, recorder = make_client(
        tmp_path, [httpx.ConnectError("boom"), ok({"id": "A1"})]
    )
    assert client.get("/authors/A1") == {"id": "A1"}
    assert len(recorder.requests) == 2


def test_transport_failure_eventually_raises(tmp_path):
    client, _ = make_client(
        tmp_path, [httpx.ConnectError("boom")] * 3, max_tries=3
    )
    with pytest.raises(OpenAlexError, match="could not reach OpenAlex"):
        client.get("/authors/A1")


def test_client_error_is_not_retried(tmp_path):
    client, recorder = make_client(tmp_path, [httpx.Response(404, text="not found")])
    with pytest.raises(OpenAlexHTTPError) as excinfo:
        client.get("/authors/A1")
    assert excinfo.value.status_code == 404
    assert len(recorder.requests) == 1


def test_a_failed_request_is_not_cached(tmp_path):
    client, _ = make_client(tmp_path, [httpx.Response(404)])
    with pytest.raises(OpenAlexHTTPError):
        client.get("/authors/A1")
    assert list((tmp_path / ".cache").glob("*.json")) == []


# ---------------------------------------------------------------- throttling


def test_requests_are_spaced_to_the_rate_limit(tmp_path):
    clock = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    recorder = Recorder([ok({"n": 1}), ok({"n": 2})])
    client = OpenAlexClient(
        mailto="tester@example.edu",
        cache_dir=tmp_path / ".cache",
        transport=recorder.transport,
        requests_per_second=10,
        sleep=sleep,
        monotonic=lambda: clock[0],
        now=lambda: FIXED_NOW,
    )
    client.get("/authors/A1")
    client.get("/authors/A2")
    assert sleeps == [pytest.approx(0.1)]


# ---------------------------------------------------------------- pagination


def test_paginate_follows_the_cursor(tmp_path):
    pages = [
        ok({"results": [{"id": "A1"}, {"id": "A2"}], "meta": {"next_cursor": "c2"}}),
        ok({"results": [{"id": "A3"}], "meta": {"next_cursor": None}}),
    ]
    client, recorder = make_client(tmp_path, pages)
    got = list(client.paginate("/authors", {"filter": "topics.id:T10001"}))
    assert [item["id"] for item in got] == ["A1", "A2", "A3"]
    assert recorder.requests[0].url.params["cursor"] == "*"
    assert recorder.requests[0].url.params["per-page"] == "200"
    assert recorder.requests[1].url.params["cursor"] == "c2"


def test_paginate_stops_on_an_empty_page(tmp_path):
    pages = [ok({"results": [], "meta": {"next_cursor": "c2"}})]
    client, recorder = make_client(tmp_path, pages)
    assert list(client.paginate("/authors")) == []
    assert len(recorder.requests) == 1


def test_paginate_replays_from_cache_for_free(tmp_path):
    pages = [
        ok({"results": [{"id": "A1"}], "meta": {"next_cursor": "c2"}}),
        ok({"results": [{"id": "A2"}], "meta": {"next_cursor": None}}),
    ]
    client, _ = make_client(tmp_path, pages)
    first = list(client.paginate("/authors"))
    resumed, recorder = make_client(tmp_path, [])
    assert list(resumed.paginate("/authors")) == first
    assert recorder.requests == []


def test_paginate_refuses_to_loop_on_a_repeated_cursor(tmp_path):
    pages = [
        ok({"results": [{"id": "A1"}], "meta": {"next_cursor": "*"}}),
    ]
    client, _ = make_client(tmp_path, pages)
    with pytest.raises(OpenAlexError, match="repeated cursor"):
        list(client.paginate("/authors"))
