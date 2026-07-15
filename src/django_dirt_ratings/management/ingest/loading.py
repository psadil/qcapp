"""The single seam for loading neuroimaging inputs.

Renderers receive their inputs as location strings (from a bidslake ``BidsFile``)
and load them here, so there is exactly one place that turns a location into a
loaded image. That is also the seam where remote (S3) support will drop in later:
``bidslake`` hands back a ``UPath`` that can open remote objects, but ``nibabel``
cannot read an fsspec URL directly, so remote loading will read bytes through the
UPath and hand a file object to nibabel. For now only local paths are supported.
"""

from __future__ import annotations

import nibabel as nb
from nibabel import spatialimages


def _local(location: str) -> str:
    """Return a local filesystem path for ``location`` (``file://`` tolerated)."""
    if location.startswith("file://"):
        return location[len("file://") :]
    if "://" in location:
        raise NotImplementedError(
            f"remote inputs are not supported yet (got {location!r}); "
            "render locally, or wait for the S3 render seam"
        )
    return location


def load_nifti(location: str) -> nb.nifti1.Nifti1Image:
    """Load a NIfTI image from a local path."""
    return nb.nifti1.Nifti1Image.load(_local(location))


def load_mgz(location: str) -> nb.nifti1.Nifti1Image:
    """Load a FreeSurfer ``.mgz`` volume as a NIfTI image."""
    mgh = nb.freesurfer.mghformat.load(_local(location))
    return nb.nifti1.Nifti1Image.from_image(mgh)


def load_transform_reference(location: str) -> spatialimages.SpatialImage:
    """Load an image to use as a resampling reference (alias for :func:`load_nifti`)."""
    return load_nifti(location)
