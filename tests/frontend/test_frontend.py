"""Frontend browser integration tests using Playwright."""

import os
import struct
import zlib
from collections.abc import Iterator
from typing import NamedTuple

import pytest
from playwright.sync_api import Browser, BrowserContext, FloatRect, Page, expect
from pytest_django import live_server_helper

from django_dirt_ratings import models

BOOTSWATCH = "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist"
LIGHT_CSS = f"{BOOTSWATCH}/flatly/bootstrap.min.css"
DARK_CSS = f"{BOOTSWATCH}/darkly/bootstrap.min.css"


@pytest.fixture(scope="class")
def live_server(
    request: pytest.FixtureRequest,
) -> Iterator[live_server_helper.LiveServer]:
    """pytest-django's `live_server`, widened from per-test to per-class.

    One server thread for the whole class, with the per-test flush happening
    underneath it — the same lifetime Django's own LiveServerTestCase uses.
    pytest-django's autouse `_live_server_helper` keys off the fixture *name*, so
    it still pulls in `transactional_db` and toggles ALLOWED_HOSTS per test.
    """
    addr = (
        request.config.getvalue("liveserver")
        or os.getenv("DJANGO_LIVE_TEST_SERVER_ADDRESS")
        or "localhost"
    )
    server = live_server_helper.LiveServer(addr)
    yield server
    server.stop()


@pytest.fixture(scope="class")
def class_context(
    browser: Browser, browser_context_args: dict
) -> Iterator[BrowserContext]:
    """One browser context per class, replacing pytest-playwright's per-test one.

    Building the context and page is most of these tests' setup cost, and every
    test that shares one re-navigates from the landing page, which resets the
    Django session cookie. Two things it costs:

    - a class whose subject *is* persisted client state must not share one — see
      TestThemeToggle, which keeps the per-test `page` fixture;
    - it bypasses pytest-playwright's artifacts recorder, so --video, --tracing
      and --screenshot capture nothing for the classes that share a context.
    """
    context = browser.new_context(**browser_context_args)
    yield context
    context.close()


@pytest.fixture(scope="class")
def class_page(class_context: BrowserContext) -> Iterator[Page]:
    """One page per class, reused by every test in it."""
    page = class_context.new_page()
    yield page
    page.close()


def _make_png(width: int, height: int) -> bytes:
    """A solid light-gray RGB PNG (stdlib only), big enough to show a grid."""
    row = bytes([200, 200, 205]) * width
    raw = b"".join(b"\x00" + row for _ in range(height))

    def chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _seed_images(step: models.Step, size: int) -> set[int]:
    """Two images for `step` — enough that a "next" one exists after a review."""
    return {
        models.Image.objects.create(
            img=_make_png(size, size),
            slice=i,
            file1=f"test_{step.value}_{i}.nii.gz",
            display=models.DisplayMode.X,
            step=step,
        ).pk
        for i in range(2)
    }


@pytest.fixture
def locmem_cache(settings):
    """Use an in-memory cache so the live-server tests need no cache table."""
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }


@pytest.fixture
def index_page(
    live_server: live_server_helper.LiveServer, page: Page, locmem_cache
) -> Page:
    """The browser sitting on the landing step-selection page."""
    page.goto(live_server.url)
    return page


@pytest.fixture
def dark_page(index_page: Page) -> Page:
    """The landing page after one theme toggle — i.e. switched to dark."""
    index_page.locator("#theme-toggle").click()
    return index_page


@pytest.mark.django_db(transaction=True)
class TestThemeToggle:
    """The theme switcher (themes.js) and its localStorage persistence.

    These deliberately keep pytest-playwright's per-test `page`: the stored
    preference is the subject under test, so a context shared across the class
    would carry one test's theme into the next one's arrange.
    """

    def test_default_theme_is_light(
        self, live_server: live_server_helper.LiveServer, page: Page, locmem_cache
    ):
        page.goto(live_server.url)

        expect(page.locator("#theme-css")).to_have_attribute("href", LIGHT_CSS)

    def test_toggle_switches_to_dark(self, index_page: Page):
        index_page.locator("#theme-toggle").click()

        expect(index_page.locator("#theme-css")).to_have_attribute("href", DARK_CSS)

    def test_toggle_again_switches_back_to_light(self, dark_page: Page):
        dark_page.locator("#theme-toggle").click()

        expect(dark_page.locator("#theme-css")).to_have_attribute("href", LIGHT_CSS)

    def test_theme_persists_across_reloads(self, dark_page: Page):
        """State lives in localStorage, not the server session."""
        dark_page.reload()

        expect(dark_page.locator("#theme-css")).to_have_attribute("href", DARK_CSS)


def _start_review(
    live_server: live_server_helper.LiveServer, page: Page, step: models.Step
) -> None:
    """Walk the landing page so the browser session (session_id/step) is set up."""
    page.goto(live_server.url)
    page.select_option("select[name=step]", str(step.value))
    page.click("button[type=submit]")


def _posted_to(page: Page, path: str):
    """Wait for the submit POST itself, so the row is committed before we query."""
    return page.expect_response(
        lambda r: r.request.method == "POST" and r.url.rstrip("/").endswith(path)
    )


class _RatingPage(NamedTuple):
    page: Page
    seeded: set[int]


HOTKEYS = [
    ("p", models.Ratings.PASS),
    ("u", models.Ratings.UNSURE),
    ("f", models.Ratings.FAIL),
]


@pytest.fixture
def rating_page(
    live_server: live_server_helper.LiveServer, class_page: Page, locmem_cache
) -> _RatingPage:
    """Two fmap images seeded, with the browser on the rating page and focused."""
    seeded = _seed_images(models.Step.FMAP_COREGISTRATION, size=64)
    _start_review(live_server, class_page, models.Step.FMAP_COREGISTRATION)
    expect(class_page).to_have_url(f"{live_server.url}/fmap_coregistration/")
    class_page.click("body")
    return _RatingPage(page=class_page, seeded=seeded)


def _rate_and_submit(rating_page: _RatingPage, hotkey: str) -> None:
    """Pick a verdict with its hotkey, then submit with Enter."""
    rating_page.page.keyboard.press(hotkey)
    with _posted_to(rating_page.page, "fmap_coregistration"):
        rating_page.page.keyboard.press("Enter")


@pytest.mark.django_db(transaction=True)
class TestRatingHotkeys:
    """Rating radios respond to p/u/f hotkeys and Enter submits (selects.js)."""

    @pytest.mark.parametrize("hotkey, expected", HOTKEYS)
    def test_hotkey_checks_the_matching_radio(
        self, rating_page: _RatingPage, hotkey: str, expected: models.Ratings
    ):
        rating_page.page.keyboard.press(hotkey)

        expect(
            rating_page.page.locator(f"input[value='{expected.value}']")
        ).to_be_checked()

    @pytest.mark.parametrize("hotkey, expected", HOTKEYS)
    def test_enter_stores_the_chosen_verdict(
        self, rating_page: _RatingPage, hotkey: str, expected: models.Ratings
    ):
        _rate_and_submit(rating_page, hotkey)

        assert models.Rating.objects.get().rating == expected

    def test_enter_submits_exactly_one_rating(self, rating_page: _RatingPage):
        _rate_and_submit(rating_page, "p")

        assert models.Rating.objects.count() == 1

    def test_the_rating_is_attached_to_a_served_image(self, rating_page: _RatingPage):
        _rate_and_submit(rating_page, "p")

        assert models.Rating.objects.get().image_id in rating_page.seeded

    def test_hotkey_fires_while_a_radio_is_focused(self, rating_page: _RatingPage):
        """Native validation focuses the first radio when it blocks a submit."""
        rating_page.page.focus(f"input[value='{models.Ratings.FAIL.value}']")

        rating_page.page.keyboard.press("p")

        expect(
            rating_page.page.locator(f"input[value='{models.Ratings.PASS.value}']")
        ).to_be_checked()

    def test_hotkey_fires_while_the_flag_checkbox_is_focused(
        self, rating_page: _RatingPage
    ):
        """Checking the source-data-issue box leaves focus on it."""
        rating_page.page.focus("#id_source_data_issue")

        rating_page.page.keyboard.press("u")

        expect(
            rating_page.page.locator(f"input[value='{models.Ratings.UNSURE.value}']")
        ).to_be_checked()


@pytest.mark.django_db(transaction=True)
class TestFlagOnlySubmitIsBlockedNatively:
    """Submitting only the source-data-issue flag never reaches the server.

    Regression: the blank '---------' choice rendered as a pre-checked radio,
    so a flag-only submit passed native required validation and POSTed an
    empty rating; the invalid-form response was the full page, which htmx
    nested inside #main.
    """

    @pytest.fixture
    def flagged_only(self, rating_page: _RatingPage) -> _RatingPage:
        """Check only the source-data-issue box and try to submit."""
        rating_page.page.check("#id_source_data_issue")
        rating_page.page.click("#submit")
        return rating_page

    def test_the_blank_choice_is_not_rendered(self, rating_page: _RatingPage):
        expect(rating_page.page.locator("input[name='rating']")).to_have_count(3)

    def test_no_rating_is_preselected(self, rating_page: _RatingPage):
        expect(rating_page.page.locator("input[name='rating']:checked")).to_have_count(
            0
        )

    def test_native_validation_holds_the_form_invalid(self, flagged_only: _RatingPage):
        expect(flagged_only.page.locator("#form:invalid")).to_have_count(1)

    def test_the_image_pane_is_not_nested(self, flagged_only: _RatingPage):
        expect(flagged_only.page.locator("#main")).to_have_count(1)

    @pytest.fixture
    def corrected(self, flagged_only: _RatingPage) -> _RatingPage:
        """Pick a verdict after the blocked attempt and submit for real."""
        _rate_and_submit(flagged_only, "p")
        return flagged_only

    def test_only_the_corrected_submission_is_stored(self, corrected: _RatingPage):
        # One row proves the flag-only click never POSTed: the awaited
        # corrected submit would otherwise have been the second rating.
        assert models.Rating.objects.count() == 1

    def test_the_flag_rides_along_with_the_verdict(self, corrected: _RatingPage):
        assert models.Rating.objects.get().source_data_issue is True


class _CanvasPage(NamedTuple):
    page: Page
    box: FloatRect
    seeded: set[int]


# clicks.js sizes the canvas from the image inside img.onload; until that runs the
# element still has its pre-load default box and painted cells would land in the
# wrong grid squares. `style.width` is set by the same call that draws the grid.
_GRID_DRAWN = "() => !!document.getElementById('canvas')?.style.width"


@pytest.fixture
def canvas_page(
    live_server: live_server_helper.LiveServer, class_page: Page, locmem_cache
) -> _CanvasPage:
    """Two mask images seeded, with the grid canvas drawn and ready to paint."""
    seeded = _seed_images(models.Step.MASK, size=200)
    _start_review(live_server, class_page, models.Step.MASK)
    expect(class_page).to_have_url(f"{live_server.url}/mask/")

    class_page.wait_for_function(_GRID_DRAWN)
    box = class_page.locator("#canvas").bounding_box()
    if box is None:
        pytest.fail("#canvas has no bounding box, so it cannot be painted")
    return _CanvasPage(page=class_page, box=box, seeded=seeded)


def _paint_two_cells(canvas_page: _CanvasPage) -> None:
    """Mark one cell at the default UNSURE level and a distinct one at FAIL."""
    page, box = canvas_page.page, canvas_page.box
    page.mouse.click(box["x"] + 40, box["y"] + 40)
    page.keyboard.press("f")
    page.mouse.click(box["x"] + box["width"] - 40, box["y"] + box["height"] - 40)


@pytest.mark.django_db(transaction=True)
class TestCanvasGridPaint:
    """Paint cells on the grid at two levels and submit; cells persist."""

    @pytest.fixture
    def submitted(self, canvas_page: _CanvasPage) -> models.Annotation:
        _paint_two_cells(canvas_page)
        with _posted_to(canvas_page.page, "mask"):
            canvas_page.page.click("#submit")
        return models.Annotation.objects.get()

    def test_painting_updates_the_cell_count(self, canvas_page: _CanvasPage):
        _paint_two_cells(canvas_page)

        expect(canvas_page.page.locator("#cell-count")).to_have_text("2")

    def test_painting_alone_submits_nothing(self, canvas_page: _CanvasPage):
        _paint_two_cells(canvas_page)

        assert models.Annotation.objects.count() == 0

    def test_submission_is_attached_to_a_served_image(
        self, submitted: models.Annotation, canvas_page: _CanvasPage
    ):
        assert submitted.image_id in canvas_page.seeded

    def test_submission_stores_both_painted_cells(self, submitted: models.Annotation):
        assert submitted.cells.count() == 2

    def test_submission_keeps_each_cell_level(self, submitted: models.Annotation):
        levels = set(submitted.cells.values_list("rating", flat=True))

        assert levels == {models.Ratings.UNSURE, models.Ratings.FAIL}

    def test_level_hotkey_fires_while_the_flag_checkbox_is_focused(
        self, canvas_page: _CanvasPage
    ):
        canvas_page.page.focus("#id_source_data_issue")

        canvas_page.page.keyboard.press("f")

        expect(canvas_page.page.locator("button[data-level='2']")).to_have_attribute(
            "aria-pressed", "true"
        )

    def test_enter_submits_the_flag_while_its_checkbox_is_focused(
        self, canvas_page: _CanvasPage
    ):
        canvas_page.page.check("#id_source_data_issue")
        with _posted_to(canvas_page.page, "mask"):
            canvas_page.page.keyboard.press("Enter")

        assert models.Annotation.objects.get().source_data_issue is True
