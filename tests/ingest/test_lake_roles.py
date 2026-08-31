"""Tests for role resolution: a required role gates a job, an optional one does not."""

import logging

import pytest

lake = pytest.importorskip("django_dirt_ratings.management.ingest.lake")


def _row(*, unresolved, optional=frozenset()) -> lake.UnitRow:
    """One anchor row with the given roles left unresolved."""
    return lake.UnitRow(
        file_path="sub-01_mask.nii.gz",
        local="/tmp/sub-01_mask.nii.gz",
        entities={},
        roles=dict.fromkeys(unresolved),
        unresolved=unresolved,
        optional_roles=optional,
    )


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_lake_roles")


def test_a_fully_resolved_row_is_kept(logger):
    assert _row(unresolved={}).warn_unresolved(logger) is False


def test_a_missing_required_role_skips_the_row(logger):
    row = _row(unresolved={"anat": 0})

    assert row.warn_unresolved(logger) is True


def test_an_ambiguous_required_role_skips_the_row(logger):
    row = _row(unresolved={"anat": 2})

    assert row.warn_unresolved(logger) is True


def test_a_missing_optional_role_keeps_the_row(logger):
    row = _row(unresolved={"dseg": 0}, optional=frozenset({"dseg"}))

    assert row.warn_unresolved(logger) is False


def test_an_ambiguous_optional_role_keeps_the_row(logger):
    """Ambiguity is still never resolved by guessing — the role just stays absent."""
    row = _row(unresolved={"dseg": 2}, optional=frozenset({"dseg"}))

    assert row.warn_unresolved(logger) is False


def test_a_required_role_still_skips_alongside_an_optional_one(logger):
    row = _row(unresolved={"anat": 0, "dseg": 0}, optional=frozenset({"dseg"}))

    assert row.warn_unresolved(logger) is True
