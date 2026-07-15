"""DTI-fit QC: an RGB-encoded principal-diffusion-direction animation.

Depends on the ``fsl_dtifit`` bidslake adapter (Phase 2d), which maps the
qsirecon FSL-dtifit outputs onto BIDS concepts so the FA map and its V1/V2/V3
eigenvector siblings pair by shared entities. Until that adapter indexes the
tree, ``discover`` finds nothing and yields no jobs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django_dirt_ratings import models

from .. import bids
from ..registry import RenderJob, StepSpec, register


def discover(lake: Any, filters: dict[str, Any]) -> list[RenderJob]:
    query = {"suffix": "FA", "extension": ".nii.gz", **filters}
    jobs: list[RenderJob] = []
    for fa in lake.get(**query):
        e = fa.entities
        shared = {"sub": e.get("sub"), "ses": e.get("ses"), "run": e.get("run")}
        vecs = {
            p: bids.first(lake, suffix=p, extension=".nii.gz", **shared)
            for p in ("V1", "V2", "V3")
        }
        if not all(vecs.values()):
            continue
        jobs.append(
            RenderJob(
                file1=Path(fa.file_path).name,
                file2=None,
                render_key="dtifit",
                inputs={
                    "fa": str(fa.local_path),
                    "v1": str(vecs["V1"].local_path),
                    "v2": str(vecs["V2"].local_path),
                    "v3": str(vecs["V3"].local_path),
                },
                cuts=[None],
                displays=[models.DisplayMode.Z],
            )
        )
    return jobs


register(StepSpec(step=models.Step.DTIFIT, name="dtifit", discover=discover))
