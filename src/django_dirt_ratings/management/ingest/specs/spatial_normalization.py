"""Spatial-normalization QC: landmark ROIs overlaid on the normalized T1w.

Any space found is discovered (no hardcoded template): anchors are grouped by
their ``space``/``cohort`` entities and each group's landmark ROI artifact is
resolved via :func:`rois.ensure_rois` — built once per space and cached on
disk, so the (deliberate) heavyweight work in this ``discover`` is amortized
O(1); it must happen here because only path strings cross the render-pool
boundary. A space without a recipe (or unreachable TemplateFlow assets — e.g.
offline compute nodes with a cold cache; pre-warm with ``manage build_rois``)
skips its whole group with one loud warning, never a guessed overlay.

Each T1w is paired with its same-space brain mask (used to strip the
not-brain-extracted ``desc-preproc`` background before display); a T1w without
exactly one such mask is skipped, never guessed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django_dirt_ratings import models

from .. import lake as lake_mod
from .. import rois
from ..registry import Lake, RenderJob, StepSpec, register

logger = logging.getLogger(__name__)

N_CUTS = 3

# Rational-subgroup entities the T1w must share with its brain mask, and which
# identify the ROI artifact for its group.
_SHARED = ("sub", "ses", "space", "cohort", "res")


def discover(lake: Lake, filters: Mapping[str, Any]) -> list[RenderJob]:
    rows = lake_mod.unit_rows(
        lake,
        anchor={
            "datatype": "anat",
            "suffix": "T1w",
            "desc": "preproc",
            "extension": ".nii.gz",
            **filters,
        },
        entities=_SHARED,
        require=("space",),
        roles={
            "mask": lake_mod.Role(
                join=_SHARED,
                where={
                    "datatype": "anat",
                    "suffix": "mask",
                    "desc": "brain",
                    "extension": ".nii.gz",
                },
            ),
        },
    )
    artifacts: dict[tuple[str, str | None], rois.RoiArtifact | None] = {}
    skipped: dict[tuple[str, str | None], int] = {}
    jobs: list[RenderJob] = []
    for row in rows:
        if row.warn_unresolved(logger):
            continue
        mask = row.roles["mask"]
        if mask is None:  # warn_unresolved already covered this; narrows the type
            continue
        group = (row.entities["space"], row.entities["cohort"])
        if group not in artifacts:
            try:
                artifacts[group] = rois.ensure_rois(group[0], group[1])
            except rois.RoiUnavailableError as err:
                logger.warning("no landmark ROIs for space %s: %s", group, err)
                artifacts[group] = None
        artifact = artifacts[group]
        if artifact is None:
            skipped[group] = skipped.get(group, 0) + 1
            continue
        jobs.append(
            RenderJob(
                file1=Path(row.file_path).name,
                file2=Path(mask.file_path).name,
                render_key="spatial_normalization",
                inputs={
                    "anat": row.local,
                    "mask": mask.local,
                    "rois": str(artifact.dseg),
                    "roi_meta": str(artifact.meta),
                },
                cuts=list(range(N_CUTS)),
                displays=list(models.DisplayMode),
                metrics=dict(row.entities),
            )
        )
    for group, count in skipped.items():
        logger.warning("skipped %d file(s) in space %s: no landmark ROIs", count, group)
    return jobs


register(
    StepSpec(
        step=models.Step.SPATIAL_NORMALIZATION,
        name="spatial_normalization",
        discover=discover,
    )
)
