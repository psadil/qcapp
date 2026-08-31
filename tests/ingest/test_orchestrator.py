"""Tests for the measure stage: what gets computed, and what a value means."""

import dataclasses

import pytest

np = pytest.importorskip("numpy")
nb = pytest.importorskip("nibabel")
orchestrator = pytest.importorskip("django_dirt_ratings.management.ingest.orchestrator")

from django_dirt_ratings.management.ingest.registry import RenderJob
from django_dirt_ratings.models import ComputedMetric as M


@pytest.fixture
def mask_job(tmp_path) -> RenderJob:
    """A mask job carrying only a brain mask and its subgroup entities."""
    data = np.zeros((10, 10, 10), np.uint8)
    data[3:7, 3:7, 3:7] = 1
    path = tmp_path / "mask.nii.gz"
    nb.Nifti1Image(data, np.eye(4)).to_filename(path)
    return RenderJob(
        file1="sub-01_mask.nii.gz",
        file2=None,
        render_key="mask",
        inputs={"mask": str(path)},
        cuts=[0],
        displays=[],
        entities={"space": "MNI152NLin2009cAsym"},
    )


class TestMeasureWithoutAPlan:
    """No plan is needed to measure: the roles a job carries decide everything."""

    @pytest.fixture
    def measured(self, mask_job) -> tuple[dict, dict]:
        return orchestrator._measure(job=mask_job, catalog=None)

    def test_the_mask_metrics_are_computed(self, measured):
        _, values = measured

        assert values[M.MASK_VOLUME] == pytest.approx(64.0)

    def test_the_fov_metrics_are_computed(self, measured):
        _, values = measured

        assert set(values) >= {
            M.FOV_CUTOFF_DORSAL,
            M.FOV_CUTOFF_VENTRAL,
            M.FOV_CUTOFF_MAX,
        }

    def test_an_inapplicable_metric_is_absent_not_null(self, measured):
        """Absence means the extractor never applied; NULL would mean it failed."""
        _, values = measured

        assert M.AFFINE_DISPLACEMENT not in values

    def test_the_subgroup_entities_are_kept_as_context(self, measured):
        entities, _ = measured

        assert entities == {"space": "MNI152NLin2009cAsym"}


class TestCatalogValues:
    """A harvested catalog value is a number to rank on, or context to rank within."""

    def test_a_number_becomes_a_metric(self, mask_job):
        _, values = orchestrator._measure(job=mask_job, catalog={"fd_mean": 0.3})

        assert values["fd_mean"] == pytest.approx(0.3)

    def test_an_unresolved_value_is_a_null_metric(self, mask_job):
        _, values = orchestrator._measure(job=mask_job, catalog={"fd_mean": None})

        assert values["fd_mean"] is None

    def test_a_string_becomes_context(self, mask_job):
        entities, _ = orchestrator._measure(job=mask_job, catalog={"scanner": "Prisma"})

        assert entities["scanner"] == "Prisma"


def test_a_failing_extractor_nulls_only_its_own_metrics(mask_job):
    """One unreadable input must not cost the file its other measurements."""
    broken = dataclasses.replace(
        mask_job, inputs={**mask_job.inputs, "transform": "/nonexistent/xfm.txt"}
    )

    _, values = orchestrator._measure(job=broken, catalog=None)

    assert values[M.AFFINE_DISPLACEMENT] is None
