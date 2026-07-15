"""Frontend browser integration tests using Playwright."""

import pytest
from playwright.sync_api import Page, expect
from pytest_django import live_server_helper

from django_dirt_ratings import models


@pytest.fixture
def eager_celery_and_test_cache(settings):
    """Ensure celery tasks run eagerly and cache doesn't require memcached."""
    import os

    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }


@pytest.mark.skip
@pytest.mark.django_db(transaction=True)
def test_index_and_theme_toggling(
    live_server: live_server_helper.LiveServer,
    page: Page,
    eager_celery_and_test_cache,
):
    """Test landing step selection page and the reactive theme switcher."""
    page.on("console", lambda msg: print(f"CONSOLE: {msg.text}"))
    page.goto(live_server.url)

    # Check theme is initially light (Bootswatch Flatly theme link)
    theme_css = page.locator("#theme-css")
    expect(theme_css).to_have_attribute(
        "href",
        "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/flatly/bootstrap.min.css",
    )

    # Toggle to dark mode
    toggle_btn = page.locator("#theme-toggle")
    toggle_btn.click()

    # Check theme is now dark (Bootswatch Darkly theme link)
    expect(theme_css).to_have_attribute(
        "href",
        "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/darkly/bootstrap.min.css",
    )

    # Reload page to verify state persists in localStorage
    page.reload()
    expect(theme_css).to_have_attribute(
        "href",
        "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/darkly/bootstrap.min.css",
    )

    # Toggle back to light mode
    toggle_btn.click()
    expect(theme_css).to_have_attribute(
        "href",
        "https://cdn.jsdelivr.net/npm/bootswatch@5.3.0/dist/flatly/bootstrap.min.css",
    )


@pytest.mark.skip
@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("hotkey", ["p", "u", "f"])
def test_rating_hotkeys(
    live_server: live_server_helper.LiveServer,
    page: Page,
    hotkey: str,
    eager_celery_and_test_cache,
):
    """Test selecting values with hotkeys, and submitting."""
    # Seed DB
    img1 = models.Image.objects.create(
        img=b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",
        slice=0,
        file1="test1.nii.gz",
        display=models.DisplayMode.X,
        step=models.Step.FMAP_COREGISTRATION,
    )

    # Go to landing page
    page.goto(f"{live_server.url}/fmap_coregistration")

    # Ensure window is focused
    page.click("body")
    # Press hotkey 'p' to select Pass
    page.keyboard.press(hotkey)
    match hotkey:
        case "p":
            expected = models.Ratings.PASS
        case "u":
            expected = models.Ratings.UNSURE
        case "f":
            expected = models.Ratings.FAIL
        case _:
            raise ValueError

    # Verify Pass radio button becomes selected
    pass_radio = page.locator(f"input[value='{expected.value}']")
    expect(pass_radio).to_be_checked()

    # Submit with Enter
    page.keyboard.press("Enter")

    # Check rating created in DB
    r = models.Rating.objects.first()
    assert (
        models.Rating.objects.count() == 1
        and isinstance(r, models.Rating)
        and r.rating == expected
        and r.image_id == img1.pk
    )


@pytest.mark.skip
@pytest.mark.django_db(transaction=True)
def test_canvas_clicking_flow(live_server, page: Page, eager_celery_and_test_cache):
    """Test clicking on the canvas to add coordinates and submitting."""
    # Seed DB with MASK images
    valid_png = __import__("base64").b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    img1 = models.Image.objects.create(
        img=valid_png,
        slice=0,
        file1="test_mask.nii.gz",
        display=models.DisplayMode.X,
        step=models.Step.MASK,
    )

    # Go through step selection on landing page
    page.goto(live_server.url)
    page.select_option("select[name=step]", str(models.Step.MASK.value))
    page.click("button[type=submit]")

    # Expect coordinates template to load
    expect(page).to_have_url(f"{live_server.url}/mask/")
    canvas = page.locator("#canvas")

    # Tap a grid cell inside the canvas bounds
    page.wait_for_timeout(500)
    box = canvas.bounding_box()
    assert box is not None
    page.mouse.click(box["x"] + 100, box["y"] + 100)

    assert models.Annotation.objects.count() == 0

    # Press Enter to submit
    page.keyboard.press("Enter")

    # Wait for the response to render and the transaction to commit
    page.wait_for_load_state("networkidle")

    # One Annotation submission with at least one marked cell should be saved
    annotation = models.Annotation.objects.first()
    assert (
        models.Annotation.objects.count() == 1
        and isinstance(annotation, models.Annotation)
        and annotation.image_id == img1.pk
        and annotation.cells.count() >= 1
    )
