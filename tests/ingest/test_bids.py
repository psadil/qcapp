"""Tests for the BIDS spec helpers (web-safe; no neuro stack)."""

from django_dirt_ratings.management.ingest import bids


class _File:
    def __init__(self, **entities):
        self.entities = entities


class _FakeLake:
    """A minimal duck-typed lake: one canned result list, whatever the filters."""

    def __init__(self, files):
        self._files = files

    def get(self, **filters):
        return list(self._files)


class TestIndexBy:
    def test_keys_by_the_requested_entities(self):
        target = _File(sub="01", ses="V1")
        lake = _FakeLake([target])

        index = bids.index_by(lake, ("sub", "ses"))

        assert index[("01", "V1")] is target

    def test_a_missing_entity_keys_as_none(self):
        target = _File(sub="01")
        lake = _FakeLake([target])

        index = bids.index_by(lake, ("sub", "ses"))

        assert index[("01", None)] is target

    def test_an_ambiguous_key_is_unusable(self):
        lake = _FakeLake([_File(sub="01"), _File(sub="01")])

        index = bids.index_by(lake, ("sub",))

        assert index[("01",)] is None

    def test_a_third_match_stays_unusable(self):
        lake = _FakeLake([_File(sub="01"), _File(sub="01"), _File(sub="01")])

        index = bids.index_by(lake, ("sub",))

        assert index[("01",)] is None
