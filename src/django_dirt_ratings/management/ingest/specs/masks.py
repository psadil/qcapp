"""Brain-mask QC: the brain mask contoured over its same-space preproc T1w."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django_dirt_ratings import models

from .. import lake as lake_mod
from .. import render
from ..registry import Lake, RenderJob, StepSpec, register

logger = logging.getLogger(__name__)

# Rational-subgroup entities the T1w must share with its mask: prioritize
# z-scores mask volume within a space (a native-space volume isn't comparable to
# an MNI-space one).
_SHARED = ("sub", "ses", "space", "res")


def discover(lake: Lake, filters: Mapping[str, Any]) -> list[RenderJob]:
    rows = lake_mod.unit_rows(
        lake,
        anchor={
            "datatype": "anat",
            "suffix": "mask",
            "desc": "brain",
            "extension": ".nii.gz",
            **filters,
        },
        entities=_SHARED,
        roles={
            # Pair with the same-space preproc T1w by shared entities: exactly
            # one match, or the mask is skipped — never a silently guessed T1w.
            "anat": lake_mod.Role(
                join=_SHARED,
                where={
                    "datatype": "anat",
                    "suffix": "T1w",
                    "desc": "preproc",
                    "extension": ".nii.gz",
                },
            ),
        },
    )
    jobs: list[RenderJob] = []
    for row in rows:
        if row.warn_unresolved(logger):
            continue
        anat = row.roles["anat"]
        if anat is None:  # warn_unresolved already covered this; narrows the type
            continue
        jobs.append(
            RenderJob(
                file1=Path(row.file_path).name,
                file2=Path(anat.file_path).name,
                render_key="mask",
                inputs={"mask": row.local, "anat": anat.local},
                cuts=list(range(render.N_CUTS)),
                displays=list(models.DisplayMode),
                metrics=dict(row.entities),
            )
        )
    return jobs


register(StepSpec(step=models.Step.MASK, name="masks", discover=discover))
