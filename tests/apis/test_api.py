"""Tests for django_dirt_ratings API (django-ninja)."""

import base64

import pytest

from django_dirt_ratings.models import DisplayMode, Image, Step

PNG = b"\x89PNG"


@pytest.fixture
def make_image(db):
    """Create an Image with a fresh identity, overriding any field."""

    def _make(**overrides) -> Image:
        n = Image.objects.count()
        fields = {
            "img": PNG,
            "slice": n,
            "file1": f"file_{n}.nii.gz",
            "display": DisplayMode.X,
            "step": Step.MASK,
        }
        return Image.objects.create(**(fields | overrides))

    return _make


def _payload(**overrides) -> dict:
    """The JSON body the create endpoint expects."""
    return {
        "img": base64.b64encode(PNG).decode(),
        "file1": "posted.nii.gz",
        "display": DisplayMode.X.value,
        "step": Step.MASK.value,
        "slice": 0,
    } | overrides


@pytest.mark.django_db
class TestGetImage:
    @pytest.fixture
    def image(self, make_image) -> Image:
        return make_image()

    @pytest.fixture
    def response(self, client, image):
        return client.get(f"/api/image/{image.pk}/")

    def test_responds_ok(self, response):
        assert response.status_code == 200

    def test_body_carries_the_id(self, response, image):
        assert response.json()["id"] == image.pk

    def test_body_carries_the_filename(self, response, image):
        assert response.json()["file1"] == image.file1

    def test_body_base64_encodes_the_bytes(self, response):
        assert response.json()["img"] == base64.b64encode(PNG).decode()

    def test_nonexistent_image_returns_404(self, client):
        response = client.get("/api/image/99999/")

        assert response.status_code == 404


@pytest.mark.django_db
class TestDeleteImage:
    @pytest.fixture
    def image(self, make_image) -> Image:
        return make_image()

    @pytest.fixture
    def response(self, client, image):
        return client.delete(f"/api/image/{image.pk}/")

    def test_responds_ok(self, response):
        assert response.status_code == 200

    def test_body_reports_success(self, response):
        assert response.json()["success"] is True

    def test_row_is_gone(self, response, image):
        assert not Image.objects.filter(pk=image.pk).exists()

    def test_nonexistent_image_returns_404(self, client):
        response = client.delete("/api/image/99999/")

        assert response.status_code == 404


@pytest.mark.django_db
class TestListImages:
    def test_responds_ok(self, client, make_image):
        make_image()

        response = client.get("/api/images/")

        assert response.status_code == 200

    def test_lists_every_image(self, client, make_image):
        for _ in range(3):
            make_image()

        response = client.get("/api/images/")

        assert len(response.json()) == 3

    def test_respects_limit(self, client, make_image):
        for _ in range(5):
            make_image()

        response = client.get("/api/images/?limit=2")

        assert len(response.json()) == 2

    def test_filters_by_step(self, client, make_image):
        make_image(step=Step.MASK)
        dtifit = make_image(step=Step.DTIFIT)

        response = client.get(f"/api/images/?step={Step.DTIFIT.value}")

        assert [row["file1"] for row in response.json()] == [dtifit.file1]


@pytest.mark.django_db
class TestCreateImage:
    @pytest.fixture
    def response(self, client):
        return client.post(
            "/api/image/", data=_payload(), content_type="application/json"
        )

    def test_responds_ok(self, response):
        assert response.status_code == 200

    def test_decodes_the_base64_bytes(self, response):
        created = Image.objects.get(pk=response.json()["id"])

        assert bytes(created.img) == PNG


@pytest.mark.django_db
class TestErrorEnvelope:
    """All API errors share the {"message": ..., "extra": {...}} shape."""

    @pytest.fixture
    def duplicate(self, client):
        """Posting the same identity twice — the second response is a 400."""
        body = _payload(file1="dup.nii.gz")
        client.post("/api/image/", data=body, content_type="application/json")
        return client.post("/api/image/", data=body, content_type="application/json")

    def test_not_found_envelope(self, client):
        response = client.get("/api/image/99999/")

        assert response.json() == {"message": "Image 99999 not found", "extra": {}}

    def test_duplicate_is_a_400(self, duplicate):
        assert duplicate.status_code == 400

    def test_validation_error_message(self, duplicate):
        assert duplicate.json()["message"] == "Validation error"

    def test_validation_error_names_the_fields(self, duplicate):
        assert "fields" in duplicate.json()["extra"]


@pytest.mark.django_db
class TestRatingsAPI:
    def test_list_ratings_empty(self, client):
        response = client.get("/api/ratings/")

        assert response.json() == []

    def test_list_ratings_responds_ok(self, client):
        response = client.get("/api/ratings/")

        assert response.status_code == 200
