"""Tests for `manage push` reconciliation against a mocked server."""

import httpx
import pytest
from django.core.management import call_command

from django_dirt_ratings import push, selectors, services
from django_dirt_ratings.models import DisplayMode, Step


class FakeServer:
    """The ingest API's read side, plus a recorder for what gets pushed."""

    def __init__(self, units: list[dict]):
        self.units = units
        self.pushed: list[dict] = []
        self.prioritized = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/plan") and request.method == "GET":
            return httpx.Response(
                200, content=b"null", headers={"content-type": "application/json"}
            )
        if request.url.path.endswith("/api/units") and request.method == "GET":
            return httpx.Response(200, json=self.units)
        if request.url.path.endswith("/api/units") and request.method == "POST":
            self.pushed.append({"body_bytes": len(request.content)})
            return httpx.Response(
                200,
                json={
                    "step": "masks",
                    "file1": "x",
                    "created": True,
                    "n_images": 1,
                    "unit_digest": "d" * 16,
                },
            )
        if request.url.path.endswith("/api/prioritize"):
            self.prioritized += 1
            return httpx.Response(200, json={"images_updated": 0})
        return httpx.Response(404, json={"message": "?", "extra": {}})


@pytest.fixture
def local_unit(db) -> dict:
    """One rendered unit in the local database + media, and its server index row."""
    services.unit_store(
        step=int(Step.MASK),
        file1="unit.nii.gz",
        file2=None,
        entities={"space": "MNI"},
        values={"mask_volume": 100.0},
        review_plan_id=None,
        blobs={(int(DisplayMode.X), 0): b"x-bytes"},
    )
    return selectors.unit_digests(step=int(Step.MASK))[0]


@pytest.fixture
def run_push(monkeypatch):
    """Run `manage push` with the HTTP layer swapped for a FakeServer."""

    def _run(server: FakeServer) -> FakeServer:
        monkeypatch.setenv("DIRT_PUSH_PASSWORD", "pw")
        monkeypatch.setattr(
            push,
            "open_client",
            lambda target: httpx.Client(
                transport=httpx.MockTransport(server.handler), auth=("u", "pw")
            ),
        )
        call_command("push", server="https://t/dirt", user="u")
        return server

    return _run


@pytest.mark.django_db
class TestSkipDecision:
    def test_a_current_unit_is_skipped(self, local_unit, run_push):
        server = run_push(FakeServer([local_unit]))

        assert server.pushed == []

    def test_a_missing_unit_is_pushed(self, local_unit, run_push):
        server = run_push(FakeServer([]))

        assert len(server.pushed) == 1

    def test_a_changed_image_set_is_pushed(self, local_unit, run_push):
        stale = local_unit | {"unit_digest": "0" * 16}

        server = run_push(FakeServer([stale]))

        assert len(server.pushed) == 1

    def test_a_metadata_only_change_is_pushed(self, local_unit, run_push):
        """Byte-identical images with stale server metrics must still travel."""
        stale = local_unit | {"meta_digest": "0" * 16}

        server = run_push(FakeServer([stale]))

        assert len(server.pushed) == 1


@pytest.mark.django_db
class TestPrioritizeTrigger:
    def test_runs_after_a_push(self, local_unit, run_push):
        server = run_push(FakeServer([]))

        assert server.prioritized == 1

    def test_does_not_run_when_everything_was_current(self, local_unit, run_push):
        server = run_push(FakeServer([local_unit]))

        assert server.prioritized == 0
