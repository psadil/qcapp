"""DTI-fit QC: an RGB-encoded principal-diffusion-direction animation.

The FSL-dtifit outputs (e.g. from qsirecon) are ordinary ``.nii.gz`` volumes, so
bidslake catalogs them without a custom adapter; this spec pairs the FA map with
its V1/V2/V3 eigenvector siblings by shared entities. The exact ``suffix`` bidslake
parses from the filenames depends on the qsirecon naming — verify it against your
tree if ``discover`` finds nothing (the sample dataset has no DWI to exercise it).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django_dirt_ratings import models

from .. import lake as lake_mod
from ..registry import Lake, RenderJob, StepSpec, register

logger = logging.getLogger(__name__)


def discover(lake: Lake, filters: Mapping[str, Any]) -> list[RenderJob]:
    rows = lake_mod.unit_rows(
        lake,
        anchor={"suffix": "FA", "extension": ".nii.gz", **filters},
        roles={
            v.lower(): lake_mod.Role(
                join=("sub", "ses", "run"),
                where={"suffix": v, "extension": ".nii.gz"},
            )
            for v in ("V1", "V2", "V3")
        },
    )
    jobs: list[RenderJob] = []
    for row in rows:
        if row.warn_unresolved(logger):
            continue
        vecs = {name: role.local for name, role in row.roles.items() if role}
        jobs.append(
            RenderJob(
                file1=Path(row.file_path).name,
                file2=None,
                render_key="dtifit",
                inputs={"fa": row.local, **vecs},
                cuts=[None],
                displays=[models.DisplayMode.Z],
            )
        )
    return jobs


register(StepSpec(step=models.Step.DTIFIT, name="dtifit", discover=discover))
