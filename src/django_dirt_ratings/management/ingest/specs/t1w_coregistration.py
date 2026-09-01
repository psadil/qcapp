"""T1w coregistration QC: the BOLD reference against the session's anatomical,
each in the T1w frame, animated so the reviewer can flip between them.

The sibling of ``fmap_coregistration``, with the anatomical standing in for the
field map. It is anchored on the boldref rather than on a field map, so it also
covers studies acquired without one — and for those studies it is the only place
the tissue-coverage measures get computed at all.

fMRIPrep writes this alignment as a ``from-boldref_to-T1w`` affine per run. Its
fixed image is the T1w, so the ITK matrix maps T1w points back into the run's
frame — which is what pulls the boldref onto the T1w grid for display.
"""

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

# The BOLD run's identity, shared by its mask and its transform.
_TARGET = ("sub", "ses", "task", "run", "acq")
# The anatomical derivatives a whole session shares.
_ANAT = ("sub", "ses")


def discover(lake: Lake, filters: Mapping[str, Any]) -> list[RenderJob]:
    rows = lake_mod.unit_rows(
        lake,
        anchor={
            "datatype": "func",
            "suffix": "boldref",
            "desc": "coreg",
            "extension": ".nii.gz",
            **filters,
        },
        entities=_TARGET,
        roles={
            "mask": lake_mod.Role(
                join=_TARGET,
                where={
                    "datatype": "func",
                    "suffix": "mask",
                    "desc": "brain",
                    "space": None,
                    "extension": ".nii.gz",
                },
            ),
            # The native-space T1w this run was coregistered to: the transform's
            # target is the anatomical frame, not any template.
            "anat": lake_mod.Role(
                join=_ANAT,
                where={
                    "datatype": "anat",
                    "suffix": "T1w",
                    "desc": "preproc",
                    "space": None,
                    "extension": ".nii.gz",
                },
            ),
            # Optional (see masks.py): present, the tissue measures run; absent,
            # they simply do not.
            "dseg": lake_mod.Role(
                join=_ANAT,
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
    # A `Role.where` builds against the SQLAlchemy table bidslake exposes, which
    # declares no `from`/`to` (the catalog itself has them) — so this transform
    # cannot be a unit-query role and comes through `lake.get`, which filters on
    # the parsed entities. `from` is a keyword, hence the dict rather than kwargs.
    boldref_to_anat: dict[str, Any] = {"from": "boldref", "to": "T1w"}
    xfms = bids.index_by(
        lake,
        _TARGET,
        datatype="func",
        suffix="xfm",
        extension=".txt",
        **boldref_to_anat,
    )
    # The aseg's label lookup is a dataset-root file carrying no entities (BIDS
    # inheritance), so it pairs by the tree it sits at the top of (see masks.py).
    labels_by_root = bids.index_by(
        lake, ("root_uri",), suffix="dseg", desc="aseg", extension=".tsv"
    )
    return _jobs_from_rows(rows, xfms, labels_by_root)


def _jobs_from_rows(
    rows: list[lake_mod.UnitRow],
    xfms: Mapping[tuple, Any],
    labels_by_root: Mapping[tuple, Any],
) -> list[RenderJob]:
    """The pure half of :func:`discover`, so it is testable without a catalog."""
    jobs: list[RenderJob] = []
    for row in rows:
        if row.warn_unresolved(logger):
            continue
        mask = row.roles["mask"]
        anat = row.roles["anat"]
        if mask is None or anat is None:  # warn_unresolved covered it; narrows the type
            continue
        xfm = xfms.get(tuple(row.entities[k] for k in _TARGET))
        if xfm is None:
            logger.debug("skipping %s: no boldref->T1w transform", row.file_path)
            continue
        transform = str(xfm.local_path)
        inputs = {
            "boldref": row.local,
            "anat": anat.local,
            "mask": mask.local,
            "transform": transform,
        }
        # The segmentation only reaches `inputs` with the lookup that verifies its
        # numbering, and that pair is what gates the tissue extractors.
        dseg = row.roles["dseg"]
        labels = labels_by_root.get((dseg.root_uri,)) if dseg is not None else None
        if dseg is not None and labels is not None:
            inputs["dseg"] = dseg.local
            inputs["dseg_labels"] = str(labels.local_path)
            # The same affine under the role TissueCoverage names it by: this is
            # the only step that can measure coverage for a study with no fieldmap.
            inputs["boldref2anat"] = transform
        jobs.append(
            RenderJob(
                file1=Path(row.file_path).name,
                file2=Path(anat.file_path).name,
                render_key="t1w_coregistration",
                inputs=inputs,
                cuts=list(range(render.COREG_N_CUTS)),
                displays=list(models.DisplayMode),
                entities=dict(row.entities),
                # The BOLD run's identity, so a cross-dataset catalog measure (an
                # MRIQC bold IQM in a sibling dataset) can be paired by entity.
                source_dataset_id=row.dataset_id,
                source_entities=dict(row.entities),
            )
        )
    return jobs


register(
    StepSpec(
        step=models.Step.T1W_COREGISTRATION,
        name="t1w_coregistration",
        discover=discover,
    )
)
