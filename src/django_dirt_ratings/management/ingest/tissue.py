"""FreeSurfer segmentation groups, verified against their sidecar lookup table.

fMRIPrep writes ``*_desc-aseg_dseg.nii.gz`` (FreeSurfer's ``aseg`` numbering,
resampled onto the preproc T1w grid) beside a ``*_desc-aseg_dseg.tsv`` BIDS
lookup. This module turns that pair into the handful of structure groups DIRT
cares about for field-of-view questions — is the frame cutting cortex, or only
cerebellum?

The label indices below are FreeSurfer's, but they are **checked, not trusted**:
every index must appear in the sidecar and its name must carry the expected token,
so a relabelled or reordered segmentation fails loudly instead of quietly scoring
the wrong structure. That is the same rule ``rois.py`` applies to its atlas.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from pathlib import Path

#: Structure group -> the FreeSurfer aseg indices it pools (left and right).
GROUPS: Mapping[str, tuple[int, ...]] = {
    "cortex": (3, 42),
    "cerebellum": (7, 8, 46, 47),  # cerebellar white matter + cortex
    "brainstem": (16,),
    "cerebral_wm": (2, 41),
}

#: Substring (case-folded) every label in a group must carry in the lookup table.
#: Chosen to discriminate: "Left-Cerebellum-Cortex" does not contain
#: "cerebral-cortex", so a cortex/cerebellum swap cannot pass.
_EXPECTED: Mapping[str, str] = {
    "cortex": "cerebral-cortex",
    "cerebellum": "cerebellum",
    "brainstem": "brain-stem",
    "cerebral_wm": "cerebral-white-matter",
}


class LabelTableError(ValueError):
    """A segmentation's lookup table is missing or does not match aseg numbering."""


def load_label_table(location: str) -> dict[int, str]:
    """Read a BIDS ``_dseg.tsv`` lookup into ``{index: name}``."""
    path = Path(location)
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        fields = set(reader.fieldnames or ())
        if not {"index", "name"} <= fields:
            raise LabelTableError(
                f"{path.name}: expected `index` and `name` columns, got {sorted(fields)}"
            )
        table: dict[int, str] = {}
        for row in reader:
            index, name = row.get("index"), row.get("name")
            if index is None or name is None:
                continue
            try:
                table[int(index)] = name
            except ValueError:  # a non-numeric index is not aseg numbering
                raise LabelTableError(
                    f"{path.name}: non-integer index {index!r}"
                ) from None
    return table


def verify(table: Mapping[int, str]) -> None:
    """Raise unless every group's indices are present and named as expected."""
    for group, indices in GROUPS.items():
        token = _EXPECTED[group]
        for index in indices:
            name = table.get(index)
            if name is None:
                raise LabelTableError(
                    f"label {index} ({group}) is absent from the lookup table; "
                    "this segmentation does not use FreeSurfer aseg numbering"
                )
            if token not in name.casefold():
                raise LabelTableError(
                    f"label {index} is named {name!r}, which does not look like "
                    f"{group} (expected {token!r}); the lookup table does not match "
                    "the assumed aseg numbering"
                )
