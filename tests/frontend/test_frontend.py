"""Frontend browser integration tests using Playwright."""

import struct
import zlib

import pytest
from playwright.sync_api import Page, expect
from pytest_django import live_server_helper

from django_dirt_ratings import models


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


@pytest.fixture
def test_cache(settings):
    """Use an in-memory cache so the live-server tests need no cache table."""
    settings.CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    }


@pytest.mark.django_db(transaction=True)
def test_index_and_theme_toggling(
    live_server: live_server_helper.LiveServer,
    page: Page,
    test_cache,
):
    """Landing step-selection page and the theme switcher (themes.js)."""
    page.goto(live_server.url)

    theme_css = page.locator("#theme-css")
    expect(theme_css).to_have_attribute(
        "href",
        "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/flatly/bootstrap.min.css",
    )

    page.locator("#theme-toggle").click()
    expect(theme_css).to_have_attribute(
        "href",
        "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/darkly/bootstrap.min.css",
    )

    # State persists across reloads via localStorage.
    page.reload()
    expect(theme_css).to_have_attribute(
        "href",
        "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/darkly/bootstrap.min.css",
    )

    page.locator("#theme-toggle").click()
    expect(theme_css).to_have_attribute(
        "href",
        "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/flatly/bootstrap.min.css",
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("hotkey", ["p", "u", "f"])
def test_rating_hotkeys(
    live_server: live_server_helper.LiveServer,
    page: Page,
    hotkey: str,
    test_cache,
):
    """Rating radios respond to p/u/f hotkeys and Enter submits (selects.js)."""
    # Two images so there is a "next" image after the first is reviewed.
    seeded = {
        models.Image.objects.create(
            img=_make_png(64, 64),
            slice=i,
            file1=f"test{i}.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.FMAP_COREGISTRATION,
        ).pk
        for i in range(2)
    }

    # Start from the landing page so the session (session_id/step) is set up.
    page.goto(live_server.url)
    page.select_option("select[name=step]", str(models.Step.FMAP_COREGISTRATION.value))
    page.click("button[type=submit]")
    expect(page).to_have_url(f"{live_server.url}/fmap_coregistration/")

    page.click("body")
    page.keyboard.press(hotkey)

    expected = {
        "p": models.Ratings.PASS,
        "u": models.Ratings.UNSURE,
        "f": models.Ratings.FAIL,
    }[hotkey]
    expect(page.locator(f"input[value='{expected.value}']")).to_be_checked()

    # Wait for the submit POST itself so the row is committed before we query.
    with page.expect_response(
        lambda r: (
            r.request.method == "POST"
            and r.url.rstrip("/").endswith("fmap_coregistration")
        )
    ):
        page.keyboard.press("Enter")

    r = models.Rating.objects.first()
    assert models.Rating.objects.count() == 1
    assert r is not None and r.rating == expected and r.image_id in seeded


@pytest.mark.django_db(transaction=True)
def test_canvas_grid_paint_flow(
    live_server: live_server_helper.LiveServer,
    page: Page,
    test_cache,
):
    """Paint cells on the grid at two levels and submit; cells persist."""
    # Two images so there is a "next" image after the first is reviewed.
    seeded = {
        models.Image.objects.create(
            img=_make_png(200, 200),
            slice=i,
            file1=f"test_mask{i}.nii.gz",
            display=models.DisplayMode.X,
            step=models.Step.MASK,
        ).pk
        for i in range(2)
    }

    page.goto(live_server.url)
    page.select_option("select[name=step]", str(models.Step.MASK.value))
    page.click("button[type=submit]")

    expect(page).to_have_url(f"{live_server.url}/mask/")
    canvas = page.locator("#canvas")
    expect(canvas).to_be_visible()
    page.wait_for_timeout(500)  # let the image load and the grid draw

    box = canvas.bounding_box()
    assert box is not None

    # One cell at the default UNSURE level.
    page.mouse.click(box["x"] + 40, box["y"] + 40)
    # Switch to FAIL and mark a second, distinct cell.
    page.keyboard.press("f")
    page.mouse.click(box["x"] + box["width"] - 40, box["y"] + box["height"] - 40)

    expect(page.locator("#cell-count")).to_have_text("2")
    assert models.Annotation.objects.count() == 0  # not submitted yet

    # Wait for the submit POST itself so the row is committed before we query.
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.rstrip("/").endswith("mask")
    ):
        page.click("#submit")

    annotation = models.Annotation.objects.first()
    assert annotation is not None
    assert annotation.image_id in seeded
    assert annotation.cells.count() == 2
    assert set(annotation.cells.values_list("rating", flat=True)) == {
        models.Ratings.UNSURE,
        models.Ratings.FAIL,
    }
