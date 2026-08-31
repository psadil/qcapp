"""Brain-mask QC: the brain mask contoured over its same-space preproc T1w."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django_dirt_ratings import models

from .. import bids, render
from .. import lake as lake_mod
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
            # Optional: FreeSurfer's aseg on the preproc T1w grid, plus its label
            # lookup. Present, the tissue metrics run and say *what* the frame is
            # cutting; absent (no FreeSurfer, or a template-space mask, which
            # shares no `space` with the native-space aseg), they simply do not.
            "dseg": lake_mod.Role(
                join=_SHARED,
                where={
                    "datatype": "anat",
                    "suffix": "dseg",
                    "desc": "aseg",
                    "extension": ".nii.gz",
                },
                optional=True,
            ),
        },
    )
    # The aseg's label lookup is a dataset-root file carrying no entities (BIDS
    # inheritance), so it pairs by the tree it sits at the top of — the *aseg's*
    # tree, which is not the mask's when the two come from different derivative
    # runs (an fMRIPrep aseg beside a synthstrip mask, as in A2CPS).
    labels_by_root = bids.index_by(
        lake, ("root_uri",), suffix="dseg", desc="aseg", extension=".tsv"
    )
    jobs: list[RenderJob] = []
    for row in rows:
        if row.warn_unresolved(logger):
            continue
        anat = row.roles["anat"]
        if anat is None:  # warn_unresolved already covered this; narrows the type
            continue
        inputs = {"mask": row.local, "anat": anat.local}
        # The segmentation only reaches `inputs` with the lookup that verifies its
        # numbering, and that pair is what gates the tissue extractors.
        dseg = row.roles["dseg"]
        labels = labels_by_root.get((dseg.root_uri,)) if dseg is not None else None
        if dseg is not None and labels is not None:
            inputs["dseg"] = dseg.local
            inputs["dseg_labels"] = str(labels.local_path)
        jobs.append(
            RenderJob(
                file1=Path(row.file_path).name,
                file2=Path(anat.file_path).name,
                render_key="mask",
                inputs=inputs,
                cuts=list(range(render.N_CUTS)),
                displays=list(models.DisplayMode),
                entities=dict(row.entities),
            )
        )
    return jobs


register(StepSpec(step=models.Step.MASK, name="masks", discover=discover))
