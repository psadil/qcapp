"""Tests for the prune_media safety valve."""

import pytest
from django.core.management import call_command

from django_dirt_ratings import storage


@pytest.fixture
def referenced(make_image) -> str:
    """A stored file an Image row points at."""
    return make_image().img.name


@pytest.fixture
def orphan(db) -> str:
    """A stored file no row references."""
    name = "images/masks/gone/aaaaaaaaaaaaaaaa-d0s0.avif"
    storage.save(name, b"stale")
    return name


@pytest.mark.django_db
class TestPruneMedia:
    def test_a_fresh_orphan_is_left_alone(self, referenced, orphan):
        """Write paths save files before rows commit; recency means in-flight."""
        call_command("prune_media")

        assert sorted(storage.stored_names()) == sorted([referenced, orphan])

    def test_an_old_orphan_is_deleted(self, referenced, orphan):
        call_command("prune_media", min_age_hours=0)

        assert list(storage.stored_names()) == [referenced]

    def test_dry_run_deletes_nothing(self, referenced, orphan):
        call_command("prune_media", min_age_hours=0, dry_run=True)

        assert sorted(storage.stored_names()) == sorted([referenced, orphan])
