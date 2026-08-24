from importlib import resources
from pathlib import Path


def get_data(file: str) -> Path:
    with resources.as_file(
        resources.files("django_dirt_ratings.data").joinpath(file)
    ) as f:
        out = f
    return out


def get_landmarks() -> Path:
    """The canonical hand-drawn landmark dseg (see the sibling PROVENANCE.md).

    Built by ``tools/make_landmarks.py``; its label table lives in the sidecar
    JSON next to it. Consumed by ``management.ingest.rois``.
    """
    return get_data("tpl-MNI152NLin2009cAsym_desc-landmarks_dseg.nii.gz")
