"""Metric extractors — the quantitative measures DIRT computes at ingest.

Each extractor turns a job's resolved source inputs (the same ``role -> location``
map the renderer gets) into one or more named scalars, stored as
:class:`~django_dirt_ratings.models.Metric` rows against the measured file.

Two class-level declarations drive everything:

- ``requires`` names the input roles the extractor needs. The orchestrator runs
  **every** extractor whose roles are present in a job, so a metric is computed
  wherever the data supports it — the review plan chooses what to *order* by, never
  what to measure. A step that gains a role gains its metrics for free.
- ``emits`` names the values produced. One extractor may emit several, because the
  cost here is loading and decompressing volumes, not arithmetic: the three
  field-of-view scores come from one pass over one mask rather than three loads.

Extraction is a separate stage from rendering — the renderer's contract is
untouched — and runs in the parent process, so keeping the loads down matters.
"""

from __future__ import annotations

import abc
import logging
from collections.abc import Mapping
from typing import ClassVar

import nibabel as nb
import numpy as np

from django_dirt_ratings import models

from . import loading, tissue

logger = logging.getLogger(__name__)

#: One extractor's output: every name it emits, mapped to a value or None.
Values = Mapping[models.ComputedMetric, float | None]


class MetricExtractor(abc.ABC):
    """Base class + registry for computed measures."""

    emits: ClassVar[tuple[models.ComputedMetric, ...]]
    requires: ClassVar[tuple[str, ...]]
    _registry: ClassVar[list[type[MetricExtractor]]] = []

    def __init_subclass__(
        cls,
        /,
        emits: tuple[models.ComputedMetric, ...],
        requires: tuple[str, ...],
        **kwargs,
    ) -> None:
        super().__init_subclass__(**kwargs)
        cls.emits = emits
        cls.requires = requires
        MetricExtractor._registry.append(cls)

    @classmethod
    def applicable(cls, inputs: Mapping[str, str]) -> list[MetricExtractor]:
        """Every extractor whose required roles are all present in ``inputs``."""
        available = set(inputs)
        return [c() for c in cls._registry if set(c.requires) <= available]

    @classmethod
    def emitted(cls) -> set[models.ComputedMetric]:
        """Every metric name the registry can produce."""
        return {name for c in cls._registry for name in c.emits}

    def unmeasured(self) -> dict[models.ComputedMetric, float | None]:
        """This extractor's names, all None — "we tried and could not measure"."""
        return dict.fromkeys(self.emits, None)

    @abc.abstractmethod
    def extract(self, inputs: Mapping[str, str]) -> Values:
        """Compute this extractor's values for one job."""
        raise NotImplementedError


def _binary(image: nb.nifti1.Nifti1Image) -> np.ndarray | None:
    """A loaded volume as a 3-D boolean array, or None if it is not 3-D."""
    data = np.squeeze(np.asanyarray(image.dataobj))
    return data > 0 if data.ndim == 3 else None


def _apply_affine(affine: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Push N x 3 points through a 4x4 affine (voxel->mm, mm->mm, or mm->voxel)."""
    return points @ affine[:3, :3].T + affine[:3, 3]


def _brain_centroid_radius_mm(mask_location: str) -> tuple[np.ndarray, float] | None:
    """The brain's centroid (mm) and bounding radius (mm) from a mask, or None if empty."""
    mask = loading.load_nifti(mask_location)
    ijk = np.argwhere(np.asanyarray(mask.dataobj) > 0)
    if ijk.size == 0:
        return None
    xyz = _apply_affine(mask.affine, ijk)
    centroid = xyz.mean(axis=0)
    radius = float(np.linalg.norm(xyz - centroid, axis=1).max())
    return centroid, radius


def _border_fractions(binary: np.ndarray) -> dict[tuple[int, int], float] | None:
    """Per frame face, how much of the structure the frame cuts through.

    For each of the six faces — the first (``0``) and last (``-1``) plane of each
    array axis — this is ``100 * (voxels in that plane) / (widest cross-section
    along that axis)``. Normalizing by the structure's own widest cross-section
    rather than by the plane's area makes the score independent of how much empty
    field of view surrounds the head, so a native-space volume and a tightly
    cropped template-space one are comparable. 0 means the structure does not
    reach that face; 100 means it is cut at its widest.

    None when ``binary`` is empty. An axis of length 1 yields the same plane for
    both ends, which is correct — there is only one plane to cut.
    """
    if not binary.any():
        return None
    out: dict[tuple[int, int], float] = {}
    for axis in range(binary.ndim):
        others = tuple(i for i in range(binary.ndim) if i != axis)
        counts = binary.sum(axis=others)
        widest = int(counts.max())
        if widest == 0:  # unreachable while binary.any(), but keeps the ratio safe
            continue
        for end in (0, -1):
            out[(axis, end)] = 100.0 * float(counts[end]) / widest
    return out


def _superior_face(affine: np.ndarray) -> tuple[int, int, int]:
    """``(axis, superior end, inferior end)`` of the frame, read from the affine.

    Array order says nothing about anatomy — an ``L/A/I`` volume has its superior
    face at index 0 — so the axis and its direction come from the affine's axis
    codes. Beyond 45 degrees of obliquity the codes snap to a different axis; that
    is the right answer here, because it is the frame's faces that do the cutting.
    """
    codes = nb.aff2axcodes(affine)
    axis = next(i for i, code in enumerate(codes) if code in ("S", "I"))
    superior = -1 if codes[axis] == "S" else 0
    return axis, superior, 0 if superior == -1 else -1


class MaskVolume(
    MetricExtractor, emits=(models.ComputedMetric.MASK_VOLUME,), requires=("mask",)
):
    """Brain-mask volume in mm^3 (voxel count x per-voxel volume).

    mm^3 (not voxels) so it is comparable across images with different voxel
    sizes; the affine maps voxel->mm, so ``|det(affine[:3, :3])|`` is the volume
    of one voxel. Two-sided by nature: an atypically large *or* small brain mask is
    worth a look (a bad skull-strip either way).
    """

    def extract(self, inputs: Mapping[str, str]) -> Values:
        mask = loading.load_nifti(inputs["mask"])
        voxel_mm3 = float(abs(np.linalg.det(mask.affine[:3, :3])))
        count = float(np.count_nonzero(np.asanyarray(mask.dataobj) > 0))
        return {models.ComputedMetric.MASK_VOLUME: count * voxel_mm3}


class FovCutoff(
    MetricExtractor,
    emits=(
        models.ComputedMetric.FOV_CUTOFF_DORSAL,
        models.ComputedMetric.FOV_CUTOFF_VENTRAL,
        models.ComputedMetric.FOV_CUTOFF_MAX,
    ),
    requires=("mask",),
):
    """How much brain the field of view cuts off, per frame face (higher is worse).

    Scans acquired with a partial field of view lose the top or bottom of the brain
    — ABCD screens for exactly this, as "% intersection of brain mask with frame
    borders", split into a dorsal (superior) and ventral (inferior) score. ABCD
    publishes the wording but not the formula, so DIRT normalizes by the brain's
    own widest cross-section (see :func:`_border_fractions`); ABCD's numeric
    thresholds are therefore indicative, not transferable.

    ``fov_cutoff_max`` takes the worst of all six faces, so anterior/posterior and
    lateral clipping is caught too. All three are 0-100, and 0 means the brain
    never reaches the frame.
    """

    def extract(self, inputs: Mapping[str, str]) -> Values:
        mask = loading.load_nifti(inputs["mask"])
        binary = _binary(mask)
        if binary is None:
            return self.unmeasured()
        fractions = _border_fractions(binary)
        if fractions is None:
            return self.unmeasured()
        axis, superior, inferior = _superior_face(mask.affine)
        return {
            models.ComputedMetric.FOV_CUTOFF_DORSAL: fractions[(axis, superior)],
            models.ComputedMetric.FOV_CUTOFF_VENTRAL: fractions[(axis, inferior)],
            models.ComputedMetric.FOV_CUTOFF_MAX: max(fractions.values()),
        }


class AffineDisplacement(
    MetricExtractor,
    emits=(models.ComputedMetric.AFFINE_DISPLACEMENT,),
    requires=("mask", "transform"),
):
    """How far a coregistration affine moves the brain, in mm (higher is worse).

    fMRIPrep writes the boldref->anat/B0 coregistration as an ITK/ANTs affine .txt.
    The *determinant* is the wrong summary — it captures only volume scaling and
    misses translation and rotation entirely. Instead use the RMS displacement the
    transform induces over the brain (Jenkinson et al. 2002): for x -> Mx + t, with
    A = M - I, over a sphere of radius R at the brain centroid c,

        E_rms = sqrt( (1/5) R^2 * tr(A^T A) + |t + A c|^2 )   [mm]

    which folds in rotation, translation, and the scale/shear of A together. A well
    coregistered run barely moves (E ~ 0); a large E flags a suspect alignment.
    """

    def extract(self, inputs: Mapping[str, str]) -> Values:
        cr = _brain_centroid_radius_mm(inputs["mask"])
        if cr is None:
            return self.unmeasured()
        centroid, radius = cr
        matrix = _ras_matrix(inputs["transform"])
        a = matrix[:3, :3] - np.eye(3)
        displacement = matrix[:3, 3] + a @ centroid
        return {
            models.ComputedMetric.AFFINE_DISPLACEMENT: float(
                np.sqrt(
                    0.2 * radius**2 * np.trace(a.T @ a)
                    + float(displacement @ displacement)
                )
            )
        }


def _ras_matrix(location: str) -> np.ndarray:
    """Load an ITK/ANTs affine as a 4x4 matrix acting on RAS mm coordinates."""
    import nitransforms as nt

    return np.asarray(nt.linear.load(loading._local(location)).matrix)


#: Group name -> the metric that reports the frame cutting through it.
_CUTOFF_BY_GROUP: Mapping[str, models.ComputedMetric] = {
    "cortex": models.ComputedMetric.FOV_CUTOFF_CORTEX,
    "cerebellum": models.ComputedMetric.FOV_CUTOFF_CEREBELLUM,
    "brainstem": models.ComputedMetric.FOV_CUTOFF_BRAINSTEM,
    "cerebral_wm": models.ComputedMetric.FOV_CUTOFF_CEREBRAL_WM,
}

#: Group name -> the metric that reports how much of it the FOV missed outright.
_EXCLUDED_BY_GROUP: Mapping[str, models.ComputedMetric] = {
    "cortex": models.ComputedMetric.FOV_EXCLUDED_CORTEX,
    "cerebellum": models.ComputedMetric.FOV_EXCLUDED_CEREBELLUM,
    "brainstem": models.ComputedMetric.FOV_EXCLUDED_BRAINSTEM,
    "cerebral_wm": models.ComputedMetric.FOV_EXCLUDED_CEREBRAL_WM,
}


def _same_grid(a: nb.nifti1.Nifti1Image, b: nb.nifti1.Nifti1Image) -> bool:
    """Whether two volumes share a voxel grid (shape and affine)."""
    return bool(
        a.shape[:3] == b.shape[:3] and np.allclose(a.affine, b.affine, atol=1e-3)
    )


def _verify_labels(inputs: Mapping[str, str]) -> None:
    """Check the segmentation's lookup against aseg numbering, or raise.

    The values below are read by label index, so a segmentation numbered some
    other way would score a different structure under the right name — the one
    failure mode a reviewer could never catch from the figure.
    """
    tissue.verify(tissue.load_label_table(loading._local(inputs["dseg_labels"])))


class TissueFovCutoff(
    MetricExtractor,
    emits=tuple(_CUTOFF_BY_GROUP.values()),
    requires=("mask", "dseg", "dseg_labels"),
):
    """Which tissue the frame cuts through (higher is worse) — a proxy, by necessity.

    Not all cutoff is equally bad: clipping some cerebellum is a nuisance, clipping
    cortex is not. But when the *anatomical itself* is short, the segmentation was
    derived from that same short image, so nothing downstream can say how much
    tissue is missing — it was never imaged. What is measurable is the size of the
    cut surface per structure: :class:`FovCutoff`'s score computed over one tissue
    at a time, worst face. 0 means that structure never reaches the frame.

    For the honest "how much did we lose" question, see :class:`TissueCoverage`,
    which can answer it because it has a second image with fuller coverage.

    Requires the segmentation to share the mask's grid — fMRIPrep's
    ``desc-aseg_dseg`` is written on the preproc T1w grid, so it does for an
    anatomical mask and does not for a functional one, where these values are None.
    """

    def extract(self, inputs: Mapping[str, str]) -> Values:
        mask = loading.load_nifti(inputs["mask"])
        dseg = loading.load_nifti(inputs["dseg"])
        if not _same_grid(mask, dseg):
            # Says why the values came back NULL: expected on a functional mask,
            # but worth grepping for when an anatomical one scores nothing.
            logger.debug(
                "tissue cutoff skipped: %s is %s, %s is %s",
                inputs["mask"],
                mask.shape[:3],
                inputs["dseg"],
                dseg.shape[:3],
            )
            return self.unmeasured()
        brain = _binary(mask)
        if brain is None:
            return self.unmeasured()
        _verify_labels(inputs)
        labels = np.squeeze(np.asanyarray(dseg.dataobj))
        out: dict[models.ComputedMetric, float | None] = {}
        for group, metric in _CUTOFF_BY_GROUP.items():
            # Intersect with the brain mask so a label stranded outside it — which
            # the frame is not really "cutting" — cannot inflate the score.
            binary = np.isin(labels, tissue.GROUPS[group]) & brain
            fractions = _border_fractions(binary)
            out[metric] = None if fractions is None else max(fractions.values())
        return out


class TissueCoverage(
    MetricExtractor,
    emits=tuple(_EXCLUDED_BY_GROUP.values()),
    requires=("mask", "dseg", "dseg_labels", "boldref2anat"),
):
    """What fraction of each structure the acquisition missed outright (0-100).

    Unlike :class:`TissueFovCutoff` this is an exact measurement, not a proxy: the
    T1w covers the whole head, so its segmentation knows each structure's true
    extent, and a functional run acquired with a shorter stack simply does not
    reach some of it. Mapping the segmentation into the functional frame and
    counting what lands outside gives a real percentage — "this run is missing 38%
    of the cerebellum".

    Exclusion is defined by the **frame**, not by the functional brain mask.
    Tissue outside the acquisition matrix was never sampled; tissue inside the
    frame but missing from the mask is signal dropout, a different question that
    this metric deliberately does not conflate with coverage.

    Direction of the transform: fMRIPrep's ``from-boldref_to-T1w`` resamples BOLD
    *into* T1w space, so T1w is its reference and the ANTs matrix maps points the
    other way, T1w -> boldref — which is the direction needed here, applied as-is.
    """

    def extract(self, inputs: Mapping[str, str]) -> Values:
        reference = loading.load_nifti(inputs["mask"])
        dseg = loading.load_nifti(inputs["dseg"])
        _verify_labels(inputs)
        matrix = _ras_matrix(inputs["boldref2anat"])
        to_voxel = np.linalg.inv(reference.affine)
        shape = np.asarray(reference.shape[:3], dtype=float)
        labels = np.squeeze(np.asanyarray(dseg.dataobj))
        out: dict[models.ComputedMetric, float | None] = {}
        for group, metric in _EXCLUDED_BY_GROUP.items():
            ijk = np.argwhere(np.isin(labels, tissue.GROUPS[group]))
            if ijk.size == 0:
                out[metric] = None
                continue
            anat_mm = _apply_affine(dseg.affine, ijk.astype(float))
            target_mm = _apply_affine(matrix, anat_mm)
            target_ijk = _apply_affine(to_voxel, target_mm)
            inside = np.all((target_ijk >= -0.5) & (target_ijk <= shape - 0.5), axis=1)
            out[metric] = 100.0 * float(np.count_nonzero(~inside)) / len(ijk)
        return out


# Import-time drift guard: the enum is what the web-safe review plan validates
# against, so a metric the registry emits but the enum omits (or vice versa) would
# be silently unorderable. Fail at import instead.
_declared = set(models.ComputedMetric)
_emitted = MetricExtractor.emitted()
if _emitted != _declared:
    raise RuntimeError(
        "metric registry drifted from models.ComputedMetric: "
        f"emitted-only={sorted(m.value for m in _emitted - _declared)}, "
        f"declared-only={sorted(m.value for m in _declared - _emitted)}"
    )
