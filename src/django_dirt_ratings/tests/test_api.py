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


@pytest.mark.django_db
class TestRatingsAPI:
    def test_list_ratings_empty(self, client):
        response = client.get("/api/ratings/")
        assert response.status_code == 200
        assert response.json() == []
