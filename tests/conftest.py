"""Pytest fixtures shared across django_dirt_ratings tests."""

import os

# Playwright's synchronous API runs a greenlet event loop in the main thread,
# so Django's sync DB calls in test setup / assertions would raise
# SynchronousOnlyOperation. This is a test-harness concern only — the app's
# views are synchronous and need no such flag at runtime. Set before Django
# touches the database (import time, ahead of django_db_setup).
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

import pytest

from django_dirt_ratings.models import (
    DisplayMode,
    Image,
    Session,
    Step,
)


@pytest.fixture(scope="session")
def django_db_modify_db_settings(django_db_modify_db_settings, tmp_path_factory):
    """Use a file-based test database.

    The default SQLite test DB is in-memory and private per connection, so the
    ``live_server`` thread (and eager Celery tasks that run in it) cannot see
    rows created by the test thread. A file is shared across all connections.
    """
    from django.conf import settings

    test_db = tmp_path_factory.getbasetemp() / "test_dirt.sqlite3"
    test = settings.DATABASES["default"].setdefault("TEST", {})
    for key, default in [
        ("CHARSET", None),
        ("COLLATION", None),
        ("MIGRATE", True),
        ("MIRROR", None),
    ]:
        test.setdefault(key, default)
    test["NAME"] = str(test_db)


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
