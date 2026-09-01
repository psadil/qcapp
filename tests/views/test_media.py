"""Tests for the login-required media view that serves rendered images."""

import pytest
from django.test import Client


@pytest.fixture
def image_url(make_image) -> str:
    return make_image().img.url


@pytest.mark.django_db
class TestMediaView:
    def test_anonymous_is_redirected_to_login(self, image_url):
        response = Client().get(image_url)

        assert response.status_code == 302

    def test_logged_in_gets_the_image(self, client, image_url):
        response = client.get(image_url)

        assert response.status_code == 200

    def test_the_response_is_immutably_cacheable(self, client, image_url):
        response = client.get(image_url)

        assert response.headers["Cache-Control"] == (
            "private, max-age=31536000, immutable"
        )

    def test_the_bytes_round_trip(self, client, image_url):
        response = client.get(image_url)

        assert b"".join(response.streaming_content) == b"\x89PNG"
