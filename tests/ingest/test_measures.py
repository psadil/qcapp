"""Tests for computed metric extractors (require the neuro stack)."""

from typing import NamedTuple

import pytest

np = pytest.importorskip("numpy")
nb = pytest.importorskip("nibabel")
measures = pytest.importorskip("django_dirt_ratings.management.ingest.measures")

from django_dirt_ratings.models import ComputedMetric as M

#: Every aseg label the phantoms below use, named as FreeSurfer names them.
LABEL_TSV = "\n".join(
    ["index\tname"]
    + [
        f"{index}\t{name}"
        for index, name in (
            (2, "Left-Cerebral-White-Matter"),
            (3, "Left-Cerebral-Cortex"),
            (7, "Left-Cerebellum-White-Matter"),
            (8, "Left-Cerebellum-Cortex"),
            (16, "Brain-Stem"),
            (41, "Right-Cerebral-White-Matter"),
            (42, "Right-Cerebral-Cortex"),
            (46, "Right-Cerebellum-White-Matter"),
            (47, "Right-Cerebellum-Cortex"),
        )
    ]
)


class _CubeMask(NamedTuple):
    """A written-out mask plus the reference image transforms are defined against."""

    path: str
    reference: object


def _write(data, affine, path) -> str:
    """Write an array as a NIfTI and hand back its path."""
    nb.Nifti1Image(data, affine).to_filename(path)
    return str(path)


@pytest.fixture
def label_tsv(tmp_path) -> str:
    """The aseg lookup table fMRIPrep writes beside its segmentation."""
    path = tmp_path / "labels.tsv"
    path.write_text(LABEL_TSV + "\n")
    return str(path)


@pytest.fixture
def cube_mask(tmp_path) -> _CubeMask:
    """A 20 mm cube brain mask at 1 mm iso, centroid offset from the origin."""
    data = np.zeros((40, 40, 40), np.uint8)
    data[10:30, 10:30, 10:30] = 1
    affine = np.eye(4)
    affine[:3, 3] = [-20, -20, -20]
    path = tmp_path / "mask.nii.gz"
    nb.Nifti1Image(data, affine).to_filename(path)
    return _CubeMask(path=str(path), reference=nb.Nifti1Image(data, affine))


@pytest.fixture
def write_itk_affine(tmp_path):
    """Write a 4x4 matrix as an ITK transform file; hand back its path."""
    nt = pytest.importorskip("nitransforms")

    def _write_affine(matrix, reference) -> str:
        path = tmp_path / "xfm.txt"
        nt.linear.Affine(matrix, reference=reference).to_filename(path, fmt="itk")
        return str(path)

    return _write_affine


def test_mask_volume_is_mm3(tmp_path):
    # 2 mm isotropic voxels (8 mm^3 each); 8 nonzero voxels -> 64 mm^3.
    affine = np.diag([2.0, 2.0, 2.0, 1.0])
    data = np.zeros((4, 4, 4), dtype=np.uint8)
    data[:2, :2, :2] = 1
    path = _write(data, affine, tmp_path / "mask.nii.gz")

    volume = measures.MaskVolume().extract({"mask": path})

    assert volume[M.MASK_VOLUME] == pytest.approx(64.0)


class TestFovCutoff:
    """A brain that reaches a frame face is being cut by it."""

    @pytest.fixture
    def clipped_at_the_top(self, tmp_path) -> str:
        """A block running off the last slice of a superior-last (RAS) frame."""
        data = np.zeros((10, 10, 10), np.uint8)
        data[3:7, 3:7, 4:10] = 1
        return _write(data, np.eye(4), tmp_path / "mask.nii.gz")

    @pytest.fixture
    def scores(self, clipped_at_the_top) -> dict:
        return measures.FovCutoff().extract({"mask": clipped_at_the_top})

    def test_the_cut_face_scores_full(self, scores):
        assert scores[M.FOV_CUTOFF_DORSAL] == pytest.approx(100.0)

    def test_the_opposite_face_scores_nothing(self, scores):
        assert scores[M.FOV_CUTOFF_VENTRAL] == pytest.approx(0.0)

    def test_the_worst_face_is_the_cut_one(self, scores):
        assert scores[M.FOV_CUTOFF_MAX] == pytest.approx(100.0)

    def test_a_brain_clear_of_every_face_scores_nothing(self, cube_mask):
        scores = measures.FovCutoff().extract({"mask": cube_mask.path})

        assert scores[M.FOV_CUTOFF_MAX] == pytest.approx(0.0)

    def test_dorsal_follows_the_affine_not_the_array_order(self, tmp_path):
        """An L/A/I frame has its superior face at index 0, not -1."""
        data = np.zeros((10, 10, 10), np.uint8)
        data[3:7, 3:7, 0:6] = 1
        path = _write(data, np.diag([-1.0, 1.0, -1.0, 1.0]), tmp_path / "lai.nii.gz")

        scores = measures.FovCutoff().extract({"mask": path})

        assert scores[M.FOV_CUTOFF_DORSAL] == pytest.approx(100.0)

    def test_a_narrow_cut_scores_its_share_of_the_widest_slice(self, tmp_path):
        # 36 voxels per slice, but only 18 survive on the face -> half.
        data = np.zeros((10, 10, 10), np.uint8)
        data[2:8, 2:8, 5:10] = 1
        data[2:5, 2:8, 9] = 0
        path = _write(data, np.eye(4), tmp_path / "narrow.nii.gz")

        scores = measures.FovCutoff().extract({"mask": path})

        assert scores[M.FOV_CUTOFF_DORSAL] == pytest.approx(50.0)

    def test_an_empty_mask_is_unmeasurable(self, tmp_path):
        path = _write(np.zeros((4, 4, 4), np.uint8), np.eye(4), tmp_path / "e.nii.gz")

        scores = measures.FovCutoff().extract({"mask": path})

        assert scores[M.FOV_CUTOFF_MAX] is None


class TestTissueFovCutoff:
    """Which tissue the frame cuts through, on the anatomical's own grid."""

    @pytest.fixture
    def anat(self, tmp_path) -> dict:
        """Cortex running off the top of the frame; cerebellum well clear of it."""
        mask = np.zeros((10, 10, 10), np.uint8)
        mask[2:8, 2:8, 2:10] = 1
        labels = np.zeros((10, 10, 10), np.int16)
        labels[2:8, 2:8, 8:10] = 3
        labels[2:8, 2:8, 2:4] = 8
        return {
            "mask": _write(mask, np.eye(4), tmp_path / "mask.nii.gz"),
            "dseg": _write(labels, np.eye(4), tmp_path / "dseg.nii.gz"),
        }

    @pytest.fixture
    def scores(self, anat, label_tsv) -> dict:
        return measures.TissueFovCutoff().extract({**anat, "dseg_labels": label_tsv})

    def test_the_cut_tissue_scores(self, scores):
        assert scores[M.FOV_CUTOFF_CORTEX] == pytest.approx(100.0)

    def test_tissue_clear_of_the_frame_scores_nothing(self, scores):
        assert scores[M.FOV_CUTOFF_CEREBELLUM] == pytest.approx(0.0)

    def test_absent_tissue_is_unmeasurable(self, scores):
        assert scores[M.FOV_CUTOFF_BRAINSTEM] is None

    def test_a_segmentation_on_another_grid_is_unmeasurable(
        self, anat, label_tsv, tmp_path
    ):
        """Nothing here is resampled, so a mismatched grid must not be guessed at."""
        other = _write(
            np.zeros((8, 8, 8), np.int16), np.eye(4), tmp_path / "other.nii.gz"
        )

        scores = measures.TissueFovCutoff().extract(
            {"mask": anat["mask"], "dseg": other, "dseg_labels": label_tsv}
        )

        assert scores[M.FOV_CUTOFF_CORTEX] is None


class TestTissueCoverage:
    """How much of each structure a narrower field of view never reached."""

    @pytest.fixture
    def aseg(self, tmp_path) -> str:
        """Cerebellum in the bottom three slices, cortex in the top three."""
        labels = np.zeros((10, 10, 10), np.int16)
        labels[2:8, 2:8, 0:3] = 8
        labels[2:8, 2:8, 7:10] = 3
        return _write(labels, np.eye(4), tmp_path / "aseg.nii.gz")

    @pytest.fixture
    def short_stack(self, tmp_path) -> str:
        """A functional frame covering only the top half of the anatomical."""
        affine = np.eye(4)
        affine[2, 3] = 5.0
        return _write(
            np.ones((10, 10, 5), np.uint8), affine, tmp_path / "boldmask.nii.gz"
        )

    @pytest.fixture
    def scores(self, aseg, short_stack, label_tsv, write_itk_affine) -> dict:
        identity = write_itk_affine(np.eye(4), nb.load(short_stack))
        return measures.TissueCoverage().extract(
            {
                "mask": short_stack,
                "dseg": aseg,
                "dseg_labels": label_tsv,
                "boldref2anat": identity,
            }
        )

    def test_structure_below_the_stack_is_wholly_excluded(self, scores):
        assert scores[M.FOV_EXCLUDED_CEREBELLUM] == pytest.approx(100.0)

    def test_structure_inside_the_stack_is_not_excluded(self, scores):
        assert scores[M.FOV_EXCLUDED_CORTEX] == pytest.approx(0.0)

    def test_absent_structure_is_unmeasurable(self, scores):
        assert scores[M.FOV_EXCLUDED_BRAINSTEM] is None

    def test_the_transform_moves_the_anatomical_into_the_functional_frame(
        self, aseg, short_stack, label_tsv, write_itk_affine
    ):
        """Pins the direction the matrix is applied in, which identity cannot.

        The stack covers z >= 4.5 and the cerebellum sits at z = 0, 1, 2. Shifting
        the anatomical up by 3 mm brings exactly its top slice (z = 2 -> 5) inside,
        leaving two of three excluded. Applied the other way the cerebellum lands
        at negative z and all three are excluded, so a flipped matrix fails here.
        """
        matrix = np.eye(4)
        matrix[2, 3] = 3.0
        xfm = write_itk_affine(matrix, nb.load(short_stack))

        scores = measures.TissueCoverage().extract(
            {
                "mask": short_stack,
                "dseg": aseg,
                "dseg_labels": label_tsv,
                "boldref2anat": xfm,
            }
        )

        assert scores[M.FOV_EXCLUDED_CEREBELLUM] == pytest.approx(100 * 2 / 3)


def test_identity_transform_displaces_nothing(cube_mask, write_itk_affine):
    xfm = write_itk_affine(np.eye(4), cube_mask.reference)

    displacement = measures.AffineDisplacement().extract(
        {"mask": cube_mask.path, "transform": xfm}
    )

    assert displacement[M.AFFINE_DISPLACEMENT] == pytest.approx(0.0)


def test_pure_translation_displaces_by_its_own_length(cube_mask, write_itk_affine):
    """A = 0 for a pure translation, so the radius/centroid terms drop out."""
    matrix = np.eye(4)
    matrix[0, 3] = 5.0
    xfm = write_itk_affine(matrix, cube_mask.reference)

    displacement = measures.AffineDisplacement().extract(
        {"mask": cube_mask.path, "transform": xfm}
    )

    assert displacement[M.AFFINE_DISPLACEMENT] == pytest.approx(5.0)


def test_small_rotation_is_a_small_positive_displacement(cube_mask, write_itk_affine):
    theta = np.deg2rad(2)
    matrix = np.eye(4)
    matrix[:2, :2] = [[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]]
    xfm = write_itk_affine(matrix, cube_mask.reference)

    displacement = measures.AffineDisplacement().extract(
        {"mask": cube_mask.path, "transform": xfm}
    )

    assert displacement[M.AFFINE_DISPLACEMENT] > 0


class TestApplicability:
    """Which extractors a job gets is decided by the roles it carries, nothing else."""

    def test_a_mask_alone_runs_the_mask_only_extractors(self):
        applicable = {
            type(e) for e in measures.MetricExtractor.applicable({"mask": ""})
        }

        assert applicable == {measures.MaskVolume, measures.FovCutoff}

    def test_a_transform_adds_the_coregistration_metric(self):
        applicable = {
            type(e)
            for e in measures.MetricExtractor.applicable({"mask": "", "transform": ""})
        }

        assert measures.AffineDisplacement in applicable

    def test_a_job_without_a_mask_runs_nothing(self):
        # The dtifit step's roles: no mask, so no measure applies to it today.
        assert measures.MetricExtractor.applicable({"fa": "", "v1x": ""}) == []

    def test_coverage_needs_the_whole_anatomical_trio(self):
        applicable = {
            type(e)
            for e in measures.MetricExtractor.applicable(
                {"mask": "", "dseg": "", "dseg_labels": ""}
            )
        }

        assert measures.TissueCoverage not in applicable


def test_registry_emits_every_declared_metric():
    """The plan validates order_by against the enum, so the two cannot drift."""
    assert measures.MetricExtractor.emitted() == set(M)
