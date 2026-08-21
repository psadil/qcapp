"""Tests for the cross-dataset catalog-metric harvest (web-safe; no neuro stack)."""

from django_dirt_ratings import plan
from django_dirt_ratings.management.ingest import harvest


class _Rec:
    def __init__(self, metadata):
        self.metadata = metadata


class _FakeLake:
    """A minimal duck-typed lake: `siblings` maps dataset_id -> related ids; `records`
    is a list of (exact-get-filters, record) pairs."""

    def __init__(self, siblings, records):
        self._siblings = siblings
        self._records = records

    def related_datasets(self, dataset_id, relation=harvest.SHARES_SOURCE):
        return list(self._siblings.get(dataset_id, []))

    def get(self, **filters):
        return [rec for f, rec in self._records if f == filters]


CATALOG = plan.Measure(
    name="fd_mean",
    catalog="fd_mean",
    catalog_suffix="bold",
    match=("sub", "ses", "task", "run"),
)
ENT = {"sub": "01", "ses": "01", "task": "faces", "run": "01"}
# The exact filters harvest_catalog builds for the sibling lookup.
MATCH = {"dataset_id": "mriqc", "suffix": "bold", "extension": ".json", **ENT}


def test_harvests_from_sibling():
    lake = _FakeLake({"fmriprep": ["mriqc"]}, [(MATCH, _Rec({"fd_mean": 0.42}))])
    assert harvest.harvest_catalog(lake, "fmriprep", ENT, [CATALOG]) == {
        "fd_mean": 0.42
    }


def test_no_sibling_yields_none():
    lake = _FakeLake({}, [(MATCH, _Rec({"fd_mean": 0.42}))])
    assert harvest.harvest_catalog(lake, "orphan", ENT, [CATALOG]) == {"fd_mean": None}


def test_ambiguous_match_yields_none():
    # Two records match — the harvest never guesses which is right.
    lake = _FakeLake(
        {"fmriprep": ["mriqc"]},
        [(MATCH, _Rec({"fd_mean": 0.42})), (MATCH, _Rec({"fd_mean": 0.99}))],
    )
    assert harvest.harvest_catalog(lake, "fmriprep", ENT, [CATALOG]) == {
        "fd_mean": None
    }


def test_plain_sidecar_row_is_not_a_candidate():
    # `lake.get` iterates every walked file, so an ordinary bold .json sidecar
    # in the sibling matches the query too — but its registry row owns no
    # metadata (only the data file it describes does). The promoted record is
    # the sole candidate, so the pair is not ambiguous.
    lake = _FakeLake(
        {"fmriprep": ["mriqc"]},
        [(MATCH, _Rec({"fd_mean": 0.42})), (MATCH, _Rec({}))],
    )
    assert harvest.harvest_catalog(lake, "fmriprep", ENT, [CATALOG]) == {
        "fd_mean": 0.42
    }


def test_same_dataset_catalog_measure_is_not_harvested_here():
    same = plan.Measure(name="x", catalog="x")  # no catalog_suffix -> not cross-dataset
    lake = _FakeLake({"fmriprep": ["mriqc"]}, [])
    assert harvest.harvest_catalog(lake, "fmriprep", ENT, [same]) == {}


def test_missing_source_dataset_is_empty():
    lake = _FakeLake({"fmriprep": ["mriqc"]}, [(MATCH, _Rec({"fd_mean": 0.42}))])
    assert harvest.harvest_catalog(lake, None, ENT, [CATALOG]) == {}
