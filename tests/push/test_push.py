"""Tests for the Django-free push client (httpx.MockTransport, no database)."""

import httpx
import pytest

from django_dirt_ratings import push

TARGET = push.PushTarget(
    base_url="https://203.0.113.5/dirt", username="u", password="p", timeout=1.0
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), auth=("u", "p"))


class TestUrls:
    def test_paths_join_under_the_api_prefix(self):
        assert TARGET.url("/units") == "https://203.0.113.5/dirt/api/units"

    def test_a_trailing_slash_in_the_base_is_tolerated(self):
        target = push.PushTarget(base_url="https://h/dirt/", username="u", password="p")

        assert target.url("/plan") == "https://h/dirt/api/plan"


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    """Retries sleep BACKOFF seconds between attempts; tests need not."""
    monkeypatch.setattr(push, "BACKOFF", 0.0)


class TestPushUnitRetries:
    @pytest.fixture
    def flaky(self):
        """A server that fails twice with a 500, then accepts."""
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) < 3:
                return httpx.Response(500, text="worker crashed")
            return httpx.Response(200, json={"created": True})

        return calls, handler

    def test_a_5xx_is_retried_to_success(self, flaky):
        _, handler = flaky

        result = push.push_unit(_client(handler), TARGET, payload=b"{}", tar=b"")

        assert result == {"created": True}

    def test_the_flaky_server_saw_every_attempt(self, flaky):
        calls, handler = flaky

        push.push_unit(_client(handler), TARGET, payload=b"{}", tar=b"")

        assert len(calls) == 3

    def test_transport_errors_are_retried(self):
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            if len(calls) < 2:
                raise httpx.ConnectError("refused")
            return httpx.Response(200, json={"created": True})

        result = push.push_unit(_client(handler), TARGET, payload=b"{}", tar=b"")

        assert result == {"created": True}

    def test_a_dead_server_raises_after_the_retry_budget(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="down")

        with pytest.raises(push.PushFailed):
            push.push_unit(_client(handler), TARGET, payload=b"{}", tar=b"")


class TestPushUnit4xx:
    @pytest.fixture
    def rejecting(self):
        """A server that rejects the unit outright (a 415), counting calls."""
        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(415, json={"message": "not an AVIF", "extra": {}})

        return calls, handler

    def test_a_4xx_raises(self, rejecting):
        _, handler = rejecting

        with pytest.raises(push.PushFailed):
            push.push_unit(_client(handler), TARGET, payload=b"{}", tar=b"")

    def test_a_4xx_is_never_retried(self, rejecting):
        calls, handler = rejecting

        with pytest.raises(push.PushFailed):
            push.push_unit(_client(handler), TARGET, payload=b"{}", tar=b"")

        assert len(calls) == 1

    def test_the_failure_carries_the_server_message(self, rejecting):
        _, handler = rejecting

        with pytest.raises(push.PushFailed, match="not an AVIF"):
            push.push_unit(_client(handler), TARGET, payload=b"{}", tar=b"")


class TestFetchUnits:
    def test_maps_file1_to_the_digest_pair(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "file1": "a.nii.gz",
                        "unit_digest": "d" * 16,
                        "meta_digest": "m" * 16,
                    }
                ],
            )

        index = push.fetch_units(_client(handler), TARGET, step="masks")

        assert index == {"a.nii.gz": ("d" * 16, "m" * 16)}

    def test_an_error_status_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="")

        with pytest.raises(push.PushFailed):
            push.fetch_units(_client(handler), TARGET, step="masks")


class TestFetchPlan:
    def test_a_null_plan_reads_as_none(self):
        def handler(request: httpx.Request) -> httpx.Response:
            # json=None means "no body" to httpx, so spell the JSON null out
            return httpx.Response(
                200, content=b"null", headers={"content-type": "application/json"}
            )

        assert push.fetch_plan(_client(handler), TARGET) is None
