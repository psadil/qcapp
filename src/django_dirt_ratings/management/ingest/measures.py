"""Metric extractors — light quantitative measures DIRT computes at ingest.

Each extractor turns a job's resolved source inputs (the same ``role -> location``
map the renderer gets) into one scalar stored in ``Image.raw_metrics``. Extractors
self-register by ``key`` (the ``compute`` id a review plan references) using the
same ``__init_subclass__`` registry idiom as the ordering strategies.

This is a *separate* stage from rendering: the renderer's contract is untouched, and
the review plan — not a dispatch hard-wired to render keys — decides which measures
run. An extractor loads only what it needs (cheap relative to rendering).
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from typing import ClassVar

import numpy as np

from . import loading


class MetricExtractor(abc.ABC):
    """Base class + registry for computed measures."""

    key: ClassVar[str]
    _registry: ClassVar[dict[str, type["MetricExtractor"]]] = {}

    def __init_subclass__(cls, /, key: str, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        cls.key = key
        MetricExtractor._registry[key] = cls

    @classmethod
    def get(cls, key: str) -> "MetricExtractor":
        """Instantiate the extractor registered under ``key``."""
        try:
            return cls._registry[key]()
        except KeyError as e:
            raise KeyError(
                f"unknown metric extractor {key!r}; have {sorted(cls._registry)}"
            ) from e

    @abc.abstractmethod
    def extract(self, inputs: Mapping[str, str]) -> float | None:
        """Compute the scalar for one job, or None if it cannot be measured."""
        raise NotImplementedError


class MaskVolume(MetricExtractor, key="mask_volume"):
    """Brain-mask volume in mm^3 (voxel count x per-voxel volume).

    mm^3 (not voxels) so it is comparable across images with different voxel
    sizes; the affine maps voxel->mm, so ``|det(affine[:3, :3])|`` is the volume
    of one voxel. Two-sided by nature: an atypically large *or* small brain mask is
    worth a look (a bad skull-strip either way).
    """

    def extract(self, inputs: Mapping[str, str]) -> float | None:
        mask = loading.load_nifti(inputs["mask"])
        voxel_mm3 = float(abs(np.linalg.det(mask.affine[:3, :3])))
        return float(np.count_nonzero(np.asanyarray(mask.dataobj) > 0)) * voxel_mm3


def _voxel_to_mm(affine: np.ndarray, ijk: np.ndarray) -> np.ndarray:
    """Map voxel indices (N x 3) to mm coordinates via a NIfTI affine."""
    return ijk @ affine[:3, :3].T + affine[:3, 3]


def _brain_centroid_radius_mm(mask_location: str) -> tuple[np.ndarray, float] | None:
    """The brain's centroid (mm) and bounding radius (mm) from a mask, or None if empty."""
    mask = loading.load_nifti(mask_location)
    ijk = np.argwhere(np.asanyarray(mask.dataobj) > 0)
    if ijk.size == 0:
        return None
    xyz = _voxel_to_mm(mask.affine, ijk)
    centroid = xyz.mean(axis=0)
    radius = float(np.linalg.norm(xyz - centroid, axis=1).max())
    return centroid, radius


class AffineDisplacement(MetricExtractor, key="affine_displacement"):
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

    def extract(self, inputs: Mapping[str, str]) -> float | None:
        import nitransforms as nt

        cr = _brain_centroid_radius_mm(inputs["mask"])
        if cr is None:
            return None
        centroid, radius = cr
        matrix = np.asarray(nt.linear.load(loading._local(inputs["transform"])).matrix)
        a = matrix[:3, :3] - np.eye(3)
        displacement = matrix[:3, 3] + a @ centroid
        return float(
            np.sqrt(
                0.2 * radius**2 * np.trace(a.T @ a) + float(displacement @ displacement)
            )
        )
