"""Tests for django_dirt_ratings API (django-ninja)."""

import base64

import pytest

from django_dirt_ratings.models import DisplayMode, Image, Step


@pytest.mark.django_db
class TestImageAPI:
    def test_get_image(self, client):
        img = Image.objects.create(
            img=b"\x89PNG",
            slice=0,
            file1="test.nii.gz",
            display=DisplayMode.X,
            step=Step.MASK,
        )
        response = client.get(f"/api/image/{img.pk}/")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == img.pk
        assert data["file1"] == "test.nii.gz"
        assert data["img"] == base64.b64encode(b"\x89PNG").decode()

    def test_get_nonexistent_image_returns_404(self, client):
        response = client.get("/api/image/99999/")
        assert response.status_code == 404

    def test_delete_image(self, client):
        img = Image.objects.create(
            img=b"\x89PNG",
            slice=0,
            file1="test.nii.gz",
            display=DisplayMode.X,
            step=Step.MASK,
        )
        response = client.delete(f"/api/image/{img.pk}/")
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert Image.objects.count() == 0

    def test_delete_nonexistent_image_returns_404(self, client):
        response = client.delete("/api/image/99999/")
        assert response.status_code == 404

    def test_list_images(self, client):
        for i in range(3):
            Image.objects.create(
                img=b"\x89PNG",
                slice=i,
                file1=f"file_{i}.nii.gz",
                display=DisplayMode.X,
                step=Step.MASK,
            )
        response = client.get("/api/images/")
        assert response.status_code == 200
        assert len(response.json()) == 3

    def test_list_images_respects_limit(self, client):
        for i in range(5):
            Image.objects.create(
                img=b"\x89PNG",
                slice=i,
                file1=f"file_{i}.nii.gz",
                display=DisplayMode.X,
                step=Step.MASK,
            )
        response = client.get("/api/images/?limit=2")
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_list_images_filters_by_step(self, client):
        Image.objects.create(
            img=b"\x89PNG",
            slice=0,
            file1="mask.nii.gz",
            display=DisplayMode.X,
            step=Step.MASK,
        )
        Image.objects.create(
            img=b"\x89PNG",
            slice=0,
            file1="dtifit.nii.gz",
            display=DisplayMode.X,
            step=Step.DTIFIT,
        )
        response = client.get(f"/api/images/?step={Step.DTIFIT.value}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["file1"] == "dtifit.nii.gz"

    def test_create_image_decodes_base64(self, client):
        payload = {
            "img": base64.b64encode(b"\x89PNG").decode(),
            "file1": "posted.nii.gz",
            "display": DisplayMode.X.value,
            "step": Step.MASK.value,
            "slice": 0,
        }
        response = client.post(
            "/api/image/", data=payload, content_type="application/json"
        )
        assert response.status_code == 200
        img = Image.objects.get(pk=response.json()["id"])
        assert bytes(img.img) == b"\x89PNG"


@pytest.mark.django_db
class TestErrorEnvelope:
    """All API errors share the {"message": ..., "extra": {...}} shape."""

    def test_not_found_envelope(self, client):
        response = client.get("/api/image/99999/")
        assert response.status_code == 404
        assert response.json() == {"message": "Image 99999 not found", "extra": {}}

    def test_validation_error_envelope(self, client):
        payload = {
            "img": base64.b64encode(b"\x89PNG").decode(),
            "file1": "dup.nii.gz",
            "display": DisplayMode.X.value,
            "step": Step.MASK.value,
            "slice": 0,
        }
        first = client.post(
            "/api/image/", data=payload, content_type="application/json"
        )
        assert first.status_code == 200

        duplicate = client.post(
            "/api/image/", data=payload, content_type="application/json"
        )
        assert duplicate.status_code == 400
        body = duplicate.json()
        assert body["message"] == "Validation error"
        assert "fields" in body["extra"]


@pytest.mark.django_db
class TestRatingsAPI:
    def test_list_ratings_empty(self, client):
        response = client.get("/api/ratings/")
        assert response.status_code == 200
        assert response.json() == []
