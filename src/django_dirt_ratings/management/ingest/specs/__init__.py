"""Importing this package registers every step spec (see ``registry.STEP_SPECS``)."""

from . import (  # noqa: F401
    dtifit,
    fmap_coregistration,
    masks,
    spatial_normalization,
    surface_localization,
)
