"""Tests for django_dirt_ratings selectors."""

import base64

import pytest
from asgiref.sync import async_to_sync

from django_dirt_ratings.models import (
    ClickedCoordinate,
    DisplayMode,
    Image,
    Rating,
    Ratings,
    Session,
    Step,
)
from django_dirt_ratings.selectors import (
    ImageResult,
    get_image_with_fewest_ratings,
    get_related_from_step,
    img_type_for_step,
)


class TestImgTypeForStep:
    @pytest.mark.parametrize(
        "step, expected",
        [
            (Step.MASK, "png"),
            (Step.SPATIAL_NORMALIZATION, "png"),
            (Step.SURFACE_LOCALIZATION, "png"),
            (Step.FMAP_COREGISTRATION, "apng"),
            (Step.DTIFIT, "apng"),
            (999, "png"),  # unknown falls through to default
        ],
    )
    def test_returns_correct_type(self, step, expected):
        assert img_type_for_step(step) == expected


class TestImageResult:
    def test_img_type_delegates_to_utility(self):
        ir = ImageResult(id=1, step=Step.MASK, img=b"\x89PNG")
        assert ir.img_type == "png"

    def test_img_type_apng(self):
        ir = ImageResult(id=1, step=Step.DTIFIT, img=b"\x89PNG")
        assert ir.img_type == "apng"

    def test_img_decoded_returns_base64_string(self):
        raw = b"\x89PNG\r\n"
        ir = ImageResult(id=1, step=Step.MASK, img=raw)
        assert ir.img_decoded == base64.b64encode(raw).decode()


class TestGetRelatedFromStep:
    @pytest.mark.parametrize(
        "step, expected",
        [
            (Step.MASK, "clickedcoordinate"),
            (Step.SPATIAL_NORMALIZATION, "clickedcoordinate"),
            (Step.SURFACE_LOCALIZATION, "clickedcoordinate"),
            (Step.FMAP_COREGISTRATION, "rating"),
            (Step.DTIFIT, "rating"),
        ],
    )
    def test_maps_step_to_related_name(self, step, expected):
        assert get_related_from_step(step) == expected


def _make_image(step=Step.FMAP_COREGISTRATION, **kwargs):
    defaults = {
        "img": b"\x89PNG",
        "file1": f"file_{Image.objects.count()}.nii.gz",
        "display": DisplayMode.X,
        "step": step,
        "slice": Image.objects.count(),
    }
    defaults.update(kwargs)
    return Image.objects.create(**defaults)


@pytest.mark.django_db
class TestGetImageWithFewestRatings:
    def test_returns_image_with_no_ratings(self):
        """With two images, one rated and one not, returns the unrated one."""
        img_rated = _make_image()
        img_unrated = _make_image()
        session = Session.objects.create(step=Step.FMAP_COREGISTRATION)
        Rating.objects.create(image=img_rated, session=session, rating=Ratings.PASS)

        result = async_to_sync(get_image_with_fewest_ratings)(
            step=Step.FMAP_COREGISTRATION
        )
        assert result.pk == img_unrated.pk

    def test_raises_on_empty_db(self):
        with pytest.raises(ValueError, match="No image found"):
            async_to_sync(get_image_with_fewest_ratings)(step=Step.FMAP_COREGISTRATION)

    def test_excludes_last_pk(self):
        """get_image_with_fewest_ratings should skip the excluded image."""
        img1 = _make_image()
        img2 = _make_image()

        result = async_to_sync(get_image_with_fewest_ratings)(
            step=Step.FMAP_COREGISTRATION, exclude=img1.pk
        )
        assert result.pk == img2.pk

    def test_exclude_only_image_raises(self):
        """Excluding the only image should raise ValueError."""
        img = _make_image()
        with pytest.raises(ValueError, match="No image found"):
            async_to_sync(get_image_with_fewest_ratings)(
                step=Step.FMAP_COREGISTRATION, exclude=img.pk
            )

    def test_click_step_uses_clickedcoordinate(self):
        """For MASK step, ratings come from ClickedCoordinate, not Rating."""
        img_clicked = _make_image(step=Step.MASK)
        img_unclicked = _make_image(step=Step.MASK)
        session = Session.objects.create(step=Step.MASK)
        ClickedCoordinate.objects.create(
            image=img_clicked, session=session, x=1.0, y=2.0
        )

        result = async_to_sync(get_image_with_fewest_ratings)(step=Step.MASK)
        assert result.pk == img_unclicked.pk
