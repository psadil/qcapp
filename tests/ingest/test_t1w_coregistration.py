"""Tests for T1w-coregistration job building (web-safe; no bidslake).

``_jobs_from_rows`` is the pure half of ``discover`` — the catalog queries need
bidslake (manage env only), but every pairing decision is testable on hand-built
:class:`lake_mod.UnitRow` rows and plain index dicts.
"""

import dataclasses

from django_dirt_ratings.management.ingest import lake as lake_mod
from django_dirt_ratings.management.ingest.specs import t1w_coregistration

KEY = ("01", "V1", "rest", "01", None)
ROOT = "/data/fmriprep"


@dataclasses.dataclass(frozen=True)
class FakeFile:
    """The two attributes ``_jobs_from_rows`` reads off an ``index_by`` hit."""

    local_path: str
    root_uri: str = ROOT


def make_row(*, dseg: bool = True) -> lake_mod.UnitRow:
    """One boldref row with its mask and anat resolved; ``dseg`` is optional."""
    stem = "sub-01_ses-V1_task-rest_run-01"
    return lake_mod.UnitRow(
        file_path=f"sub-01/ses-V1/func/{stem}_desc-coreg_boldref.nii.gz",
        local=f"{ROOT}/{stem}_desc-coreg_boldref.nii.gz",
        entities=dict(zip(t1w_coregistration._TARGET, KEY)),
        roles={
            "mask": lake_mod.Resolved(
                f"{ROOT}/{stem}_desc-brain_mask.nii.gz",
                f"{stem}_desc-brain_mask.nii.gz",
                ROOT,
            ),
            "anat": lake_mod.Resolved(
                f"{ROOT}/sub-01_ses-V1_desc-preproc_T1w.nii.gz",
                "sub-01_ses-V1_desc-preproc_T1w.nii.gz",
                ROOT,
            ),
            "dseg": (
                lake_mod.Resolved(
                    f"{ROOT}/sub-01_ses-V1_desc-aseg_dseg.nii.gz",
                    "sub-01_ses-V1_desc-aseg_dseg.nii.gz",
                    ROOT,
                )
                if dseg
                else None
            ),
        },
        unresolved={} if dseg else {"dseg": 0},
        optional_roles=frozenset({"dseg"}),
        dataset_id="fmriprep",
    )


XFMS = {KEY: FakeFile(f"{ROOT}/sub-01_ses-V1_from-boldref_to-T1w_xfm.txt")}
LABELS = {(ROOT,): FakeFile(f"{ROOT}/desc-aseg_dseg.tsv")}


class TestJobsFromRows:
    def test_builds_a_job_per_boldref(self):
        jobs = t1w_coregistration._jobs_from_rows([make_row()], XFMS, LABELS)

        assert [j.render_key for j in jobs] == ["t1w_coregistration"]

    def test_the_anatomical_is_the_second_file(self):
        jobs = t1w_coregistration._jobs_from_rows([make_row()], XFMS, LABELS)

        assert jobs[0].file2 == "sub-01_ses-V1_desc-preproc_T1w.nii.gz"

    def test_nine_views_are_declared(self):
        jobs = t1w_coregistration._jobs_from_rows([make_row()], XFMS, LABELS)

        assert len(jobs[0].cuts) * len(jobs[0].displays) == 9

    def test_a_missing_transform_skips_the_row(self):
        jobs = t1w_coregistration._jobs_from_rows([make_row()], {}, LABELS)

        assert jobs == []

    def test_the_transform_doubles_as_the_coverage_role(self):
        """TissueCoverage names this affine ``boldref2anat``; it is the same file."""
        jobs = t1w_coregistration._jobs_from_rows([make_row()], XFMS, LABELS)

        assert jobs[0].inputs["boldref2anat"] == jobs[0].inputs["transform"]

    def test_a_segmentation_without_its_lookup_is_not_offered(self):
        """The label table is what verifies the numbering, so neither goes alone."""
        jobs = t1w_coregistration._jobs_from_rows([make_row()], XFMS, {})

        assert "dseg" not in jobs[0].inputs

    def test_a_row_without_a_segmentation_still_renders(self):
        jobs = t1w_coregistration._jobs_from_rows([make_row(dseg=False)], XFMS, LABELS)

        assert [j.file1 for j in jobs] == [
            "sub-01_ses-V1_task-rest_run-01_desc-coreg_boldref.nii.gz"
        ]
