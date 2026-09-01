"""Tests for the login requirement on the rating views."""

import pytest
from django.test import Client
from django.urls import reverse

from django_dirt_ratings.models import Session, Step


@pytest.fixture
def anon() -> Client:
    """A client that never logged in."""
    return Client()


@pytest.mark.django_db
class TestAnonymousRedirects:
    @pytest.mark.parametrize(
        "route", ["index", "rate_partial", "click_partial", "fmap_coregistration"]
    )
    def test_view_redirects_to_login(self, anon, route):
        response = anon.get(reverse(route))

        assert response.url.startswith(f"{reverse('login')}?next=")


@pytest.mark.django_db
class TestLoginPage:
    def test_renders_anonymously(self, anon):
        response = anon.get(reverse("login"))

        assert response.status_code == 200

    def test_a_correct_password_logs_in(self, anon, rater):
        response = anon.post(
            reverse("login"), data={"username": "rater", "password": "pw"}
        )

        assert response.status_code == 302


@pytest.mark.django_db
class TestSessionIdentity:
    def test_session_user_is_the_login_name(self, client):
        client.post(reverse("index"), data={"step": Step.MASK})

        assert Session.objects.get().user == "rater"
