"""Per-space landmark ROIs for spatial-normalization QC.

Builds, for a given template ``space``, a labeled landmark image (uint8 dseg)
plus a JSON sidecar with the per-display cut coordinates and full provenance.
The design follows Benhajali et al. 2020 (doi:10.3389/fninf.2020.00007):
anatomy should fall inside wide "confidence band" ROIs.

Per-structure sourcing, procedural-first:

- **brain band** — always procedural: dilate(``BAND_MM``) XOR erode(``BAND_MM``)
  of the space's own TemplateFlow brain mask (Benhajali's own construction).
- **lateral ventricles, hippocampi** — the space's own TemplateFlow
  Harvard-Oxford subcortical atlas (``atlas-HOSPA``), where published.
- **sulcal/fissure/tentorium bands** — no atlas defines these; they are the
  hand-drawn Benhajali landmarks shipped with this package on the canonical
  ``MNI152NLin2009cAsym`` grid (see ``tools/make_landmarks.py`` and the
  ``PROVENANCE.md`` next to the file). For other spaces they are warped by a
  dipy affine+SyN registration between the two spaces' masked template T1ws,
  computed at build time. TemplateFlow's curated ``*_xfm.h5`` composites were
  evaluated and rejected: nitransforms misapplies their displacement-field
  component (warping *lowered* masked-T1w correlation below identity), whereas
  the computed registration is validated by construction — the build fails
  loudly unless warping *improves* on the identity alignment.

A space without a recipe, or whose assets cannot be fetched, raises
:class:`RoiUnavailableError`; callers must skip loudly, never guess. Artifacts
are cached under ``DIRT_ROI_CACHE`` (default ``~/.cache/dirt/rois``) with the
algorithm version in the filename, so bumping :data:`ROI_ALGORITHM_VERSION`
invalidates every stale artifact without deleting anything.

This module is deliberately Django-free so ``tools/`` scripts and tests can
import it without settings.
"""

from __future__ import annotations

import dataclasses
import functools
import hashlib
import json
import logging
import os
import tempfile
import typing
from pathlib import Path

import nibabel as nb
import numpy as np
import numpy.typing as npt
from nibabel import affines
from scipy import ndimage

from django_dirt_ratings import datasets

logger = logging.getLogger(__name__)

ROI_ALGORITHM_VERSION = 1
CANONICAL_SPACE = "MNI152NLin2009cAsym"
BAND_MM = 4.0
N_CUTS = 3

# Per-axis brain-bbox fractions for the display cuts, calibrated so that on
# MNI152NLin2009cAsym they reproduce the historical hardcoded mm cuts exactly
# (x: -50/5/30, y: -65/20/54, z: -6/13/58 on a bbox of x[-72,72] y[-108,73]
# z[-72,82]) while generalizing to any template's bounding box.
CUT_FRACTIONS: dict[str, tuple[float, float, float]] = {
    "x": (0.1528, 0.5347, 0.7083),
    "y": (0.2376, 0.7072, 0.8950),
    "z": (0.4286, 0.5519, 0.8442),
}

# Stable label table for the composed dseg. Groups (for display coloring):
# band (1), ventricles (2-3), hippocampi (4-5), hand-drawn sulcal bands (6-15).
LABELS: dict[str, int] = {
    "brain_band": 1,
    "left_lateral_ventricle": 2,
    "right_lateral_ventricle": 3,
    "left_hippocampus": 4,
    "right_hippocampus": 5,
    "left_central_sulcus": 6,
    "right_central_sulcus": 7,
    "left_cingulate_sulcus": 8,
    "right_cingulate_sulcus": 9,
    "left_calcarine_sulcus": 10,
    "right_calcarine_sulcus": 11,
    "left_parieto_occipital_fissure": 12,
    "right_parieto_occipital_fissure": 13,
    "left_tentorium_cerebelli": 14,
    "right_tentorium_cerebelli": 15,
}

# Rendering collapses left/right into one hue per structure type: label value
# -> display group. DISPLAY_COLORS[group - 1] is that group's color — the
# Okabe-Ito colorblind-safe palette (with grey replacing black, which would
# vanish on the dark background).
_GROUP_OF_STEM = {
    "brain_band": 1,
    "lateral_ventricle": 2,
    "hippocampus": 3,
    "central_sulcus": 4,
    "cingulate_sulcus": 5,
    "calcarine_sulcus": 6,
    "parieto_occipital_fissure": 7,
    "tentorium_cerebelli": 8,
}
DISPLAY_GROUPS: dict[int, int] = {
    value: _GROUP_OF_STEM[name.removeprefix("left_").removeprefix("right_")]
    for name, value in LABELS.items()
}
DISPLAY_COLORS = [
    "#56B4E9",  # brain band: sky blue
    "#E69F00",  # ventricles: orange
    "#CC79A7",  # hippocampi: reddish purple
    "#D55E00",  # central sulcus: vermilion
    "#009E73",  # cingulate sulcus: bluish green
    "#F0E442",  # calcarine sulcus: yellow
    "#0072B2",  # parieto-occipital fissure: blue
    "#999999",  # tentorium cerebelli: grey
]

# Structures taken from the space's own Harvard-Oxford subcortical atlas.
# HOSPA label indices follow FSL's fixed ordering; the authoritative TSV that
# TemplateFlow publishes (under tpl-MNI152NLin6Asym) spells them with a typo
# ("Ventrical"), so structures are located by index and *verified* by the
# center-of-mass guards in _atlas_structures rather than by name matching.
_HOSPA_STRUCTURES: dict[str, int] = {
    "left_lateral_ventricle": 3,
    "right_lateral_ventricle": 14,
    "left_hippocampus": 9,
    "right_hippocampus": 19,
}

# Registration parameters (recorded in the sidecar; changing them warrants a
# ROI_ALGORITHM_VERSION bump). Deterministic: full-sampling MI + CC metrics.
_AFFINE_LEVEL_ITERS = [10000, 1000, 100]
_AFFINE_SIGMAS = [3.0, 1.0, 0.0]
_AFFINE_FACTORS = [4, 2, 1]
_SYN_LEVEL_ITERS = [100, 50, 25]

# Warping a discrete label with nearest-neighbour interpolation chips voxels
# off the band edges; a recorded one-iteration closing plus largest-component
# pass repairs that. If cleanup changes a structure by more than this fraction
# the warp itself is suspect and the build fails.
_CLEANUP_MAX_CHANGE = 0.10


class RoiUnavailableError(RuntimeError):
    """ROIs cannot be built for this space; callers skip loudly."""


class RoiArtifact(typing.NamedTuple):
    dseg: Path
    meta: Path


@dataclasses.dataclass(frozen=True)
class _Recipe:
    """What this space's build uses. Adding a space is a reviewed change."""

    atlas: str = "HOSPA"
    atlas_desc: str = "th25"
    resolution: int = 1


_RECIPES: dict[str, _Recipe] = {
    "MNI152NLin2009cAsym": _Recipe(),
    "MNI152NLin6Asym": _Recipe(),
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def default_cache_dir() -> Path:
    env = os.environ.get("DIRT_ROI_CACHE")
    return Path(env) if env else Path.home() / ".cache" / "dirt" / "rois"


@functools.cache
def _ensure_cached(space: str, cohort: str | None, cache_dir: str) -> RoiArtifact:
    dseg, meta = _artifact_paths(space, cohort, Path(cache_dir))
    if dseg.exists() and meta.exists():
        return RoiArtifact(dseg=dseg, meta=meta)
    return build_rois(space, cohort, Path(cache_dir))


def ensure_rois(
    space: str, cohort: str | None = None, *, cache_dir: Path | None = None
) -> RoiArtifact:
    """Return the cached ROI artifact for ``space``, building it if absent."""
    return _ensure_cached(space, cohort, str(cache_dir or default_cache_dir()))


def load_cuts(meta: Path | str) -> dict[str, list[float]]:
    """The per-display cut coordinates (mm) recorded in an artifact sidecar."""
    payload = json.loads(Path(meta).read_text())
    return {
        axis: [float(c) for c in coords] for axis, coords in payload["cuts"].items()
    }


def build_rois(space: str, cohort: str | None, out_dir: Path) -> RoiArtifact:
    """Build the labeled landmark dseg + sidecar for ``space`` into ``out_dir``."""
    if space not in _RECIPES:
        raise RoiUnavailableError(
            f"no ROI recipe for space {space!r} (available: {sorted(_RECIPES)}); "
            "add one to django_dirt_ratings.management.ingest.rois._RECIPES"
        )
    recipe = _RECIPES[space]

    t1w_img = _load(
        _tf_get(space, cohort, suffix="T1w", desc=None, resolution=recipe.resolution)
    )
    mask_path = _tf_get(
        space, cohort, suffix="mask", desc="brain", resolution=recipe.resolution
    )
    mask_img = _load(mask_path)
    atlas_path = _tf_get(
        space,
        cohort,
        suffix="dseg",
        atlas=recipe.atlas,
        desc=recipe.atlas_desc,
        resolution=recipe.resolution,
    )
    atlas_img = _load(atlas_path)

    mask = np.asarray(mask_img.dataobj) > 0
    zooms = tuple(float(z) for z in mask_img.header.get_zooms()[:3])

    structures: dict[str, npt.NDArray[np.bool_]] = {
        "brain_band": _brain_band(mask, zooms, BAND_MM)
    }
    provenance: dict[str, dict[str, typing.Any]] = {
        "brain_band": {
            "source": "procedural",
            "method": f"dilate({BAND_MM}mm) XOR erode({BAND_MM}mm) of the brain mask",
            "inputs": {mask_path.name: _sha256(mask_path)},
        }
    }

    atlas_structs = _atlas_structures(atlas_img, mask_img)
    for name, arr in atlas_structs.items():
        structures[name] = arr
        provenance[name] = {
            "source": f"atlas-{recipe.atlas}",
            "label_index": _HOSPA_STRUCTURES[name],
            "inputs": {atlas_path.name: _sha256(atlas_path)},
        }

    landmark_structs, landmark_prov = _landmark_structures(space, t1w_img, mask_img)
    structures.update(landmark_structs)
    provenance.update(landmark_prov)

    data = np.zeros(mask_img.shape, dtype=np.uint8)
    # Band first so anatomical structures win any overlapping voxels.
    for name in sorted(structures, key=lambda n: LABELS[n]):
        data[structures[name]] = LABELS[name]

    cuts = _cuts_from_mask(mask_img)
    dseg_path, meta_path = _artifact_paths(space, cohort, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_img = nb.nifti1.Nifti1Image(data, mask_img.affine, dtype=np.uint8)
    # A default header carries qform_code=0/sform_code=ALIGNED and no units;
    # inherit the template mask's space code so external tools that read NIfTI
    # codes rather than affines see the space.
    out_img.header.set_qform(mask_img.affine, code=int(mask_img.header["sform_code"]))
    out_img.header.set_sform(mask_img.affine, code=int(mask_img.header["sform_code"]))
    out_img.header.set_xyzt_units(xyz="mm")
    _atomic_write_nifti(out_img, dseg_path)
    meta = {
        "algorithm_version": ROI_ALGORITHM_VERSION,
        "space": space,
        "cohort": cohort,
        "band_mm": BAND_MM,
        "cut_fractions": CUT_FRACTIONS,
        "cuts": cuts,
        "labels": LABELS,
        "structures": provenance,
    }
    _atomic_write_text(json.dumps(meta, indent=2, sort_keys=True), meta_path)
    logger.info("built ROIs for space %s -> %s", space, dseg_path)
    return RoiArtifact(dseg=dseg_path, meta=meta_path)


# --------------------------------------------------------------------------- #
# TemplateFlow access (the seam tests monkeypatch)
# --------------------------------------------------------------------------- #
def _tf_get(space: str, cohort: str | None, **query: typing.Any) -> Path:
    """Fetch one TemplateFlow asset, or raise :class:`RoiUnavailableError`."""
    import templateflow.api

    if cohort is not None:
        query["cohort"] = cohort
    query.setdefault("extension", ".nii.gz")
    try:
        result = templateflow.api.get(space, raise_empty=True, **query)
    except Exception as err:  # network, cold cache, or missing asset
        raise RoiUnavailableError(
            f"TemplateFlow asset unavailable for space {space!r} ({query}): {err}"
        ) from err
    if isinstance(result, list):
        raise RoiUnavailableError(
            f"ambiguous TemplateFlow query for space {space!r} ({query}): {result}"
        )
    return Path(result)


def _load(path: Path) -> nb.nifti1.Nifti1Image:
    img = nb.load(path)
    if not isinstance(img, nb.nifti1.Nifti1Image):
        raise TypeError(f"expected NIfTI at {path}, got {type(img)}")
    return img


# --------------------------------------------------------------------------- #
# Structure builders
# --------------------------------------------------------------------------- #
def _ellipsoid(radius_mm: float, zooms: tuple[float, ...]) -> npt.NDArray[np.bool_]:
    """A voxelized sphere of ``radius_mm`` on an anisotropic grid."""
    half = [max(1, round(radius_mm / z)) for z in zooms]
    grids = np.meshgrid(
        *(np.arange(-h, h + 1) * z for h, z in zip(half, zooms)), indexing="ij"
    )
    return np.add.reduce([g**2 for g in grids]) <= radius_mm**2


def _brain_band(
    mask: npt.NDArray[np.bool_], zooms: tuple[float, ...], band_mm: float
) -> npt.NDArray[np.bool_]:
    """Benhajali's brain-outline band: dilate(band) XOR erode(band).

    The band traces the *outer* brain boundary, so the mask is first reduced
    to its filled largest component — some templates' brain masks (e.g. FSL's
    MNI152NLin6Asym) carve out interior CSF, and eroding those directly would
    add spurious interior shells around the ventricles.
    """
    labeled, n = ndimage.label(mask)
    if n > 1:
        counts = np.bincount(labeled.ravel())[1:]
        mask = labeled == (int(counts.argmax()) + 1)
    hull = ndimage.binary_fill_holes(mask)
    ball = _ellipsoid(band_mm, zooms)
    band = ndimage.binary_dilation(hull, ball) ^ ndimage.binary_erosion(hull, ball)
    n_components = ndimage.label(band)[1]
    if n_components != 1:
        raise RoiUnavailableError(
            f"brain band should be one connected shell, got {n_components} components"
        )
    return band


def _atlas_structures(
    atlas_img: nb.nifti1.Nifti1Image, mask_img: nb.nifti1.Nifti1Image
) -> dict[str, npt.NDArray[np.bool_]]:
    """Extract ventricles + hippocampi from the space's HOSPA atlas.

    The fixed FSL label indices are verified structurally: each structure must
    be non-empty and its center of mass must land in a (generous) expected
    box, so a mislabeled or reordered atlas fails loudly instead of drawing
    the wrong outline.
    """
    if atlas_img.shape != mask_img.shape or not np.allclose(
        atlas_img.affine, mask_img.affine, atol=1e-3
    ):
        raise RoiUnavailableError(
            "atlas grid does not match the template brain-mask grid"
        )
    atlas = np.asarray(atlas_img.dataobj)
    # x sign selects the hemisphere (RAS: anatomical left is negative x);
    # boxes are generous mm bounds around each structure's textbook location
    # in any MNI-family space.
    com_boxes = {
        "left_lateral_ventricle": ((-45, -2), (-65, 45), (-5, 40)),
        "right_lateral_ventricle": ((2, 45), (-65, 45), (-5, 40)),
        "left_hippocampus": ((-45, -15), (-50, 5), (-40, 5)),
        "right_hippocampus": ((15, 45), (-50, 5), (-40, 5)),
    }
    out: dict[str, npt.NDArray[np.bool_]] = {}
    for name, index in _HOSPA_STRUCTURES.items():
        arr = atlas == index
        if not arr.any():
            raise RoiUnavailableError(f"atlas label {index} ({name}) is empty")
        com = affines.apply_affine(atlas_img.affine, ndimage.center_of_mass(arr))
        for axis, (lo, hi) in enumerate(com_boxes[name]):
            if not lo <= com[axis] <= hi:
                raise RoiUnavailableError(
                    f"{name} (label {index}) center of mass {com.round(1)} outside "
                    f"expected box on axis {'xyz'[axis]} [{lo}, {hi}]; "
                    "atlas labeling does not match the assumed FSL ordering"
                )
        out[name] = arr
    return out


def _landmark_structures(
    space: str, t1w_img: nb.nifti1.Nifti1Image, mask_img: nb.nifti1.Nifti1Image
) -> tuple[dict[str, npt.NDArray[np.bool_]], dict[str, dict[str, typing.Any]]]:
    """The hand-drawn sulcal bands, on this space's grid.

    On the canonical space the packaged dseg is used directly (its grid must
    match TemplateFlow's); any other space warps it through a dipy affine+SyN
    registration of the two spaces' masked template T1ws.
    """
    canonical_path = datasets.get_landmarks()
    canonical_img = _load(canonical_path)
    canonical = np.asarray(canonical_img.dataobj)
    packaged = json.loads(
        canonical_path.with_suffix("").with_suffix(".json").read_text()
    )
    names = [n for n in packaged["labels"] if n in LABELS]

    base_prov: dict[str, typing.Any] = {
        "source": "benhajali-landmarks",
        "inputs": {canonical_path.name: _sha256(canonical_path)},
    }
    if space == CANONICAL_SPACE:
        if canonical_img.shape != mask_img.shape or not np.allclose(
            canonical_img.affine, mask_img.affine, atol=1e-3
        ):
            raise RoiUnavailableError(
                "packaged landmark grid no longer matches the TemplateFlow "
                f"{CANONICAL_SPACE} grid; regenerate with tools/make_landmarks.py"
            )
        canonical_structs = {
            name: canonical == packaged["labels"][name] for name in names
        }
        return canonical_structs, {name: dict(base_prov) for name in canonical_structs}

    warped, registration = _warp_labels(canonical_img, t1w_img, mask_img)
    structs: dict[str, npt.NDArray[np.bool_]] = {}
    prov: dict[str, dict[str, typing.Any]] = {}
    for name in names:
        arr, cleanup = _cleanup_warped(warped == packaged["labels"][name], name)
        structs[name] = arr
        prov[name] = dict(base_prov) | {
            "registration": registration,
            "cleanup": cleanup,
        }
    return structs, prov


def _warp_labels(
    canonical_img: nb.nifti1.Nifti1Image,
    t1w_img: nb.nifti1.Nifti1Image,
    mask_img: nb.nifti1.Nifti1Image,
) -> tuple[npt.NDArray[np.integer], dict[str, typing.Any]]:
    """Register canonical-space template T1w to this space's, warp the labels.

    The result is gated: warping must *improve* the masked-T1w correlation
    over plain world-coordinate resampling, otherwise the registration (or an
    upstream convention) is broken and the build fails.
    """
    from dipy.align.imaffine import (
        AffineRegistration,
        MutualInformationMetric,
        transform_centers_of_mass,
    )
    from dipy.align.imwarp import SymmetricDiffeomorphicRegistration
    from dipy.align.metrics import CCMetric
    from dipy.align.transforms import (  # ty: ignore[unresolved-import]
        AffineTransform3D,
        RigidTransform3D,
    )
    from nilearn import image

    recipe = _RECIPES[CANONICAL_SPACE]
    mov_t1w_path = _tf_get(
        CANONICAL_SPACE, None, suffix="T1w", desc=None, resolution=recipe.resolution
    )
    mov_mask_path = _tf_get(
        CANONICAL_SPACE, None, suffix="mask", desc="brain", resolution=recipe.resolution
    )
    mov_img = _load(mov_t1w_path)
    mov = mov_img.get_fdata() * (np.asarray(_load(mov_mask_path).dataobj) > 0)
    fix = t1w_img.get_fdata() * (np.asarray(mask_img.dataobj) > 0)
    sg, mg = t1w_img.affine, mov_img.affine

    com = transform_centers_of_mass(fix, sg, mov, mg)
    affreg = AffineRegistration(
        metric=MutualInformationMetric(nbins=32),
        level_iters=_AFFINE_LEVEL_ITERS,
        sigmas=_AFFINE_SIGMAS,
        factors=_AFFINE_FACTORS,
        verbosity=0,
    )
    rigid = affreg.optimize(
        fix,
        mov,
        RigidTransform3D(),
        None,
        static_grid2world=sg,
        moving_grid2world=mg,
        starting_affine=com.affine,
    )
    affine = affreg.optimize(
        fix,
        mov,
        AffineTransform3D(),
        None,
        static_grid2world=sg,
        moving_grid2world=mg,
        starting_affine=rigid.affine,
    )
    sdr = SymmetricDiffeomorphicRegistration(CCMetric(3), level_iters=_SYN_LEVEL_ITERS)
    mapping = sdr.optimize(
        fix, mov, static_grid2world=sg, moving_grid2world=mg, prealign=affine.affine
    )

    fix_mask = np.asarray(mask_img.dataobj) > 0
    warped_t1w = mapping.transform(
        mov,
        interpolation="linear",
        image_world2grid=np.linalg.inv(mg),
        out_shape=t1w_img.shape,
        out_grid2world=sg,
    )
    identity_t1w = np.asarray(
        image.resample_to_img(
            nb.nifti1.Nifti1Image(mov, mg),
            t1w_img,
            interpolation="linear",
            force_resample=True,
            copy_header=True,
        ).dataobj
    )
    reference = fix[fix_mask]
    r_warp = float(np.corrcoef(warped_t1w[fix_mask], reference)[0, 1])
    r_identity = float(np.corrcoef(identity_t1w[fix_mask], reference)[0, 1])
    if r_warp <= r_identity:
        raise RoiUnavailableError(
            f"registration did not improve on identity alignment "
            f"(r_warp={r_warp:.4f} <= r_identity={r_identity:.4f})"
        )

    import dipy

    warped_labels = mapping.transform(
        np.asarray(canonical_img.dataobj).astype(np.int16),
        interpolation="nearest",
        image_world2grid=np.linalg.inv(canonical_img.affine),
        out_shape=t1w_img.shape,
        out_grid2world=sg,
    ).astype(np.int16)
    registration = {
        "engine": f"dipy {dipy.__version__} affine(MI)+SyN(CC) on masked T1w",
        "affine_level_iters": _AFFINE_LEVEL_ITERS,
        "syn_level_iters": _SYN_LEVEL_ITERS,
        "moving": {
            mov_t1w_path.name: _sha256(mov_t1w_path),
            mov_mask_path.name: _sha256(mov_mask_path),
        },
        "r_identity": round(r_identity, 4),
        "r_warp": round(r_warp, 4),
    }
    return warped_labels, registration


def _cleanup_warped(
    arr: npt.NDArray[np.bool_], name: str
) -> tuple[npt.NDArray[np.bool_], dict[str, int]]:
    """Repair nearest-neighbour warp raggedness; fail if repair is too large."""
    before = int(arr.sum())
    if before == 0:
        raise RoiUnavailableError(f"landmark {name} vanished during warping")
    closed = ndimage.binary_closing(arr, ndimage.generate_binary_structure(3, 1))
    labeled, n = ndimage.label(closed)
    if n > 1:
        counts = np.bincount(labeled.ravel())[1:]
        closed = labeled == (int(counts.argmax()) + 1)
    after = int(closed.sum())
    if abs(after - before) > _CLEANUP_MAX_CHANGE * before:
        raise RoiUnavailableError(
            f"cleanup changed {name} by {abs(after - before)} of {before} voxels "
            f"(> {_CLEANUP_MAX_CHANGE:.0%}); the warp looks broken"
        )
    return closed, {"voxels_before": before, "voxels_after": after}


# --------------------------------------------------------------------------- #
# Cuts, paths, hashing
# --------------------------------------------------------------------------- #
def _cuts_from_mask(mask_img: nb.nifti1.Nifti1Image) -> dict[str, list[float]]:
    """Display cuts (mm) at fixed fractions of the brain-mask bounding box."""
    mask = np.asarray(mask_img.dataobj) > 0
    idx = np.argwhere(mask)
    corners = np.array(np.meshgrid(*zip(idx.min(0), idx.max(0)))).T.reshape(-1, 3)
    world = affines.apply_affine(mask_img.affine, corners)
    lo, hi = world.min(0), world.max(0)
    return {
        axis: [
            float(round(lo[i] + f * (hi[i] - lo[i]), 1)) for f in CUT_FRACTIONS[axis]
        ]
        for i, axis in enumerate("xyz")
    }


def _artifact_paths(
    space: str, cohort: str | None, cache_dir: Path
) -> tuple[Path, Path]:
    cohort_part = f"_cohort-{cohort}" if cohort else ""
    stem = f"tpl-{space}{cohort_part}_desc-dirtv{ROI_ALGORITHM_VERSION}_dseg"
    return cache_dir / f"{stem}.nii.gz", cache_dir / f"{stem}.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_nifti(img: nb.nifti1.Nifti1Image, dst: Path) -> None:
    with tempfile.NamedTemporaryFile(
        dir=dst.parent, suffix=".nii.gz", delete=False
    ) as tmp:
        pass
    nb.save(img, tmp.name)
    os.replace(tmp.name, dst)


def _atomic_write_text(text: str, dst: Path) -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", dir=dst.parent, suffix=".json", delete=False
    ) as tmp:
        tmp.write(text)
    os.replace(tmp.name, dst)
