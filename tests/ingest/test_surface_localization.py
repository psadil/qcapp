"""Tests for surface-localization job building (web-safe; no bidslake).

``_jobs_from_rows`` is the pure half of ``discover`` — the catalog query itself
needs bidslake (manage env only), but every merging/dedup decision is testable
on hand-built :class:`lake_mod.UnitRow` rows.
"""

import logging

from django_dirt_ratings.management.ingest import lake as lake_mod
from django_dirt_ratings.management.ingest.specs import surface_localization


def make_row(
    file_path: str,
    *,
    sub: str | None = "01",
    ses: str | None = "V1",
    root: str = "/data/freesurfer",
    brain: bool = True,
) -> lake_mod.UnitRow:
    """A ribbon row rooted at ``root``; ``brain=False`` leaves the role unresolved."""
    brain_path = file_path.replace("ribbon.mgz", "brain.mgz")
    return lake_mod.UnitRow(
        file_path=file_path,
        local=f"{root}/{file_path}",
        entities={"sub": sub, "ses": ses},
        roles={
            "brain": (
                lake_mod.Resolved(f"{root}/{brain_path}", brain_path) if brain else None
            )
        },
        unresolved={} if brain else {"brain": 0},
    )


class TestJobsFromRows:
    def test_builds_a_job_per_subject(self):
        row = make_row("sub-01_ses-V1/mri/ribbon.mgz")

        jobs = surface_localization._jobs_from_rows([row])

        assert [j.file1 for j in jobs] == ["sub-01_ses-V1/mri/ribbon.mgz"]

    def test_duplicate_index_runs_collapse_to_the_direct_root(self):
        # The same physical file, catalogued from two roots: its own dataset,
        # and the fMRIPrep dataset that contains it under sourcedata/.
        direct = make_row(
            "sub-01_ses-V1/mri/ribbon.mgz",
            root="/data/fmriprep/sourcedata/freesurfer",
        )
        nested = make_row(
            "sourcedata/freesurfer/sub-01_ses-V1/mri/ribbon.mgz",
            root="/data/fmriprep",
        )

        jobs = surface_localization._jobs_from_rows([nested, direct])

        assert [j.file1 for j in jobs] == ["sub-01_ses-V1/mri/ribbon.mgz"]

    def test_distinct_subjectless_rows_are_never_merged(self):
        # Subject-less rows (e.g. fsaverage) share the (None, None) key; two
        # different physical files must not last-wins-merge into one job.
        rows = [
            make_row("fsaverage/mri/ribbon.mgz", sub=None, ses=None),
            make_row("fsaverage/xhemi/mri/ribbon.mgz", sub=None, ses=None),
        ]

        jobs = surface_localization._jobs_from_rows(rows)

        assert jobs == []

    def test_skipping_distinct_ribbons_warns(self, caplog):
        rows = [
            make_row("fsaverage/mri/ribbon.mgz", sub=None, ses=None),
            make_row("fsaverage/xhemi/mri/ribbon.mgz", sub=None, ses=None),
        ]

        with caplog.at_level(logging.WARNING):
            surface_localization._jobs_from_rows(rows)

        assert "distinct ribbon volumes" in caplog.text

    def test_an_unresolved_brain_skips_the_subject(self):
        row = make_row("sub-01_ses-V1/mri/ribbon.mgz", brain=False)

        jobs = surface_localization._jobs_from_rows([row])

        assert jobs == []
