"""Pytest fixtures shared across django_dirt_ratings tests."""

import pytest

from django_dirt_ratings.models import (
    DisplayMode,
    Image,
    Session,
    Step,
)


@pytest.fixture
def mask_session(db):
    """A Session configured for the MASK step."""
    return Session.objects.create(step=Step.MASK)


@pytest.fixture
def fmap_session(db):
    """A Session configured for the FMAP_COREGISTRATION step."""
    return Session.objects.create(step=Step.FMAP_COREGISTRATION)


@pytest.fixture
def mask_image(db):
    """A minimal Image for the MASK step."""
    return Image.objects.create(
        img=b"\x89PNG",
        slice=0,
        file1="test.nii.gz",
        display=DisplayMode.X,
        step=Step.MASK,
    )


@pytest.fixture
def fmap_image(db):
    """A minimal Image for the FMAP_COREGISTRATION step."""
    return Image.objects.create(
        img=b"\x89PNG",
        slice=0,
        file1="test.nii.gz",
        display=DisplayMode.X,
        step=Step.FMAP_COREGISTRATION,
    )
