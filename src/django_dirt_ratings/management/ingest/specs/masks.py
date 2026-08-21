"""Brain-mask QC: the brain mask contoured over its same-space preproc T1w."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django_dirt_ratings import models

from .. import bids, render
from ..registry import Lake, RenderJob, StepSpec, register


def discover(lake: Lake, filters: Mapping[str, Any]) -> list[RenderJob]:
    query = {
        "datatype": "anat",
        "suffix": "mask",
        "desc": "brain",
        "extension": ".nii.gz",
        **filters,
    }
    jobs: list[RenderJob] = []
    for mask in lake.get(**query):
        e = mask.entities
        shared = {
            "sub": e.get("sub"),
            "ses": e.get("ses"),
            "space": e.get("space"),
            "res": e.get("res"),
        }
        # Pair with the same-space preproc T1w by shared entities; fall back to a
        # bare T1w (no desc) — not by editing the filename string.
        anat = bids.first(
            lake,
            datatype="anat",
            suffix="T1w",
            desc="preproc",
            extension=".nii.gz",
            **shared,
        ) or bids.first(
            lake, datatype="anat", suffix="T1w", extension=".nii.gz", **shared
        )
        if anat is None:
            continue
        jobs.append(
            RenderJob(
                file1=Path(mask.file_path).name,
                file2=Path(anat.file_path).name,
                render_key="mask",
                inputs={"mask": str(mask.local_path), "anat": str(anat.local_path)},
                cuts=list(range(render.N_CUTS)),
                displays=list(models.DisplayMode),
                # Rational-subgroup entities: prioritize z-scores mask volume within a
                # space (a native-space volume isn't comparable to an MNI-space one).
                metrics=dict(shared),
            )
        )
    return jobs


register(StepSpec(step=models.Step.MASK, name="masks", discover=discover))
