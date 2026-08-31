"""Tests for the aseg label table: DIRT checks its numbering, never assumes it."""

import pytest

tissue = pytest.importorskip("django_dirt_ratings.management.ingest.tissue")

FREESURFER = {
    2: "Left-Cerebral-White-Matter",
    3: "Left-Cerebral-Cortex",
    7: "Left-Cerebellum-White-Matter",
    8: "Left-Cerebellum-Cortex",
    16: "Brain-Stem",
    41: "Right-Cerebral-White-Matter",
    42: "Right-Cerebral-Cortex",
    46: "Right-Cerebellum-White-Matter",
    47: "Right-Cerebellum-Cortex",
}


@pytest.fixture
def write_tsv(tmp_path):
    """Write a ``{index: name}`` mapping as a BIDS lookup table."""

    def _write(table, header="index\tname") -> str:
        rows = "\n".join(f"{index}\t{name}" for index, name in table.items())
        path = tmp_path / "labels.tsv"
        path.write_text(f"{header}\n{rows}\n")
        return str(path)

    return _write


def test_reads_every_row(write_tsv):
    table = tissue.load_label_table(write_tsv(FREESURFER))

    assert table == FREESURFER


def test_a_freesurfer_table_verifies(write_tsv):
    table = tissue.load_label_table(write_tsv(FREESURFER))

    assert tissue.verify(table) is None


def test_a_missing_label_is_rejected(write_tsv):
    table = tissue.load_label_table(
        write_tsv({k: v for k, v in FREESURFER.items() if k != 16})
    )

    with pytest.raises(tissue.LabelTableError, match="16"):
        tissue.verify(table)


def test_a_renumbered_table_is_rejected(write_tsv):
    """Cortex and cerebellum swapped: the very mistake this guard exists for."""
    swapped = {**FREESURFER, 3: "Left-Cerebellum-Cortex"}

    with pytest.raises(tissue.LabelTableError, match="cerebral-cortex"):
        tissue.verify(tissue.load_label_table(write_tsv(swapped)))


def test_a_table_without_the_expected_columns_is_rejected(write_tsv):
    with pytest.raises(tissue.LabelTableError, match="columns"):
        tissue.load_label_table(write_tsv(FREESURFER, header="id\tlabel"))


def test_every_group_has_an_expected_name(write_tsv):
    """The group table and its verification tokens are kept in lockstep."""
    assert set(tissue.GROUPS) == set(tissue._EXPECTED)
