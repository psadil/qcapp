from importlib import resources
from pathlib import Path


def get_data(file: str) -> Path:
    with resources.as_file(
        resources.files("django_dirt_ratings.data").joinpath(file)
    ) as f:
        out = f
    return out


def get_layout() -> Path:
    return get_data("tpl-MNI152NLin2009cAsym_res-01_desc-rois_dseg.nii.gz")
