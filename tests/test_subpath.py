"""With FORCE_SCRIPT_NAME set, every generated URL carries the prefix.

The deployment serves at https://<host>/dirt/ behind a proxy that forwards the
prefixed path through UNstripped (Django strips it for routing — under ASGI,
request.path comes straight from the scope, so a proxy-side strip would leak
into redirects). Unprefixed paths must keep resolving too: the container
healthcheck requests /accounts/login/ directly.
"""

import pytest
from django.test import Client
from django.urls import base

from django_dirt_ratings.models import Session, Step


@pytest.fixture
def subpath(settings):
    """The deployed configuration: FORCE_SCRIPT_NAME plus the script prefix.

    Real handlers (WSGI/ASGI) set the thread-local script prefix from
    FORCE_SCRIPT_NAME per request; Django's test client does not, so the
    fixture sets it the way the handler would. Re-assigning MEDIA_URL and
    STATIC_URL (to their real values) makes the override and its teardown fire
    setting_changed for them, busting the storages' cached, prefix-bearing
    base_url so it cannot leak into later tests.
    """
    settings.FORCE_SCRIPT_NAME = "/dirt"
    settings.MEDIA_URL = "media/"
    settings.STATIC_URL = "static/"
    base.set_script_prefix("/dirt")
    yield
    base.clear_script_prefix()


@pytest.mark.django_db
class TestSubpathUrls:
    def test_the_login_redirect_is_prefixed(self, subpath):
        response = Client().get("/")

        assert response.headers["Location"].startswith("/dirt/accounts/login/")

    def test_an_unprefixed_path_still_resolves(self, subpath):
        """The compose healthcheck hits the container directly, prefixless."""
        response = Client().get("/accounts/login/")

        assert response.status_code == 200

    def test_static_urls_are_prefixed(self, subpath, client):
        response = client.get("/")

        assert "/dirt/static/ratings/style.css" in response.text

    def test_served_images_are_prefixed(self, subpath, client, make_image):
        make_image(step=Step.MASK, slice=0)
        session = Session.objects.create(step=Step.MASK)
        browser_session = client.session
        browser_session.update({"step": int(Step.MASK), "session_id": session.pk})
        browser_session.save()

        response = client.get("/rate_partial/")

        assert 'src="/dirt/media/images/' in response.text
