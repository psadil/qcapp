"""Spatial-normalization QC: an atlas overlaid on the normalized T1w.

The target space is a property of this step (it selects both the files to query
and the bundled atlas + cut coordinates the renderer uses), so it lives here as
one constant instead of being split between a command's filter and the renderer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django_dirt_ratings import models

from ..registry import RenderJob, StepSpec, register

SPACE = "MNI152NLin2009cAsym"
N_CUTS = 3


def discover(lake: Any, filters: dict[str, Any]) -> list[RenderJob]:
    query = {
        "datatype": "anat",
        "suffix": "T1w",
        "desc": "preproc",
        "space": SPACE,
        "extension": ".nii.gz",
        **filters,
    }
    return [
        RenderJob(
            file1=Path(anat.file_path).name,
            file2=None,
            render_key="spatial_normalization",
            inputs={"anat": str(anat.local_path)},
            cuts=list(range(N_CUTS)),
            displays=list(models.DisplayMode),
        )
        for anat in lake.get(**query)
    ]


register(
    StepSpec(
        step=models.Step.SPATIAL_NORMALIZATION,
        name="spatial_normalization",
        discover=discover,
    )
)
