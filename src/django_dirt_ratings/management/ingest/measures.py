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
