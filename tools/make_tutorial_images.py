"""Generate the spatial-normalization tutorial images (dev-time).

Renders good and deliberately-broken examples with the *real* renderer from the
bundled sample data, overlays the app's 28-column click grid (same geometry and
colors as ``static/ratings/clicks.js``), and — for each broken example — also
writes a "marked" variant with the cells a careful rater would paint.

Marked cells follow the rating rule itself, computed geometrically — the
escaping anatomy, never the band: the subject's *brain edge* (boundary of its
perturbed brain mask) falling outside the outline band, and *internal
structures* escaping their ROIs (the subject starts well-normalized, so each
structure sits where its template ROI is; the ROI moved by the perturbation is
where the structure now is, and — after eroding by a visibility tolerance —
any remainder outside the unmoved ROI group is marked). The "unsure" case is
simply a smaller perturbation, so only a few cells violate. Figure pixel
coordinates come from a self-calibration render: the good volume with two
bright in-plane dots at known world coordinates.

Failure modes are simulated by resampling the T1w *and its brain mask* through
the same world-space perturbation (translation / rotation / scale) on the
unchanged grid, i.e. the subject's anatomy moves relative to the template
landmarks, exactly like a failed normalization.

Outputs (commit these): docs/assets/tutorial/spatial_normalization/*.avif
Re-run whenever the spatial-normalization rendering style changes.

Run:  pixi run -e dev python tools/make_tutorial_images.py
"""

from __future__ import annotations

import io
import math
import sys
import tempfile
from pathlib import Path

import nibabel as nb
import numpy as np
from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dirt.settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "tutorial-images-not-a-secret")
django.setup()

from django_dirt_ratings.management.ingest import render, rois
from django_dirt_ratings.models import DisplayMode

ANAT = (
    REPO / "data/ds000228-fmriprep/sub-pixar001/anat/"
    "sub-pixar001_space-MNI152NLin2009cAsym_res-2_desc-preproc_T1w.nii.gz"
)
MASK = (
    REPO / "data/ds000228-fmriprep/sub-pixar001/anat/"
    "sub-pixar001_space-MNI152NLin2009cAsym_res-2_desc-brain_mask.nii.gz"
)
OUT_DIR = REPO / "docs" / "assets" / "tutorial" / "spatial_normalization"

# Grid geometry and colors, mirroring static/ratings/clicks.js.
GRID_COLS = 28
GRID_LINE = (128, 128, 128, 77)  # rgba(128,128,128,0.30)
FILL_UNSURE = (243, 156, 18, 115)  # rgba(243,156,18,0.45)
FILL_FAIL = (231, 76, 60, 140)  # rgba(231,76,60,0.55)

CUT = 1  # the middle display cut, same for every case

# Fixed world-space fiducial corners: nilearn frames each figure from the data
# bounding box, so every case gets two invisible (near-black, single-voxel)
# markers at the same coordinates, pinning an identical field of view across
# renders — one pixel calibration per view then applies to every case.
_FIDUCIALS_MM = ((-88.0, -120.0, -70.0), (88.0, 80.0, 88.0))

# For each display mode: the indices of the world axes shown horizontally and
# vertically in the figure.
_DISPLAY_AXES = {DisplayMode.X: (1, 2), DisplayMode.Y: (0, 2), DisplayMode.Z: (0, 1)}

# A cell needs at least this many violating points (edge or internal) before
# it is painted — filters single-voxel discretization noise.
_MIN_POINTS_PER_CELL = 2


def _translation(dx: float, dy: float, dz: float) -> np.ndarray:
    p = np.eye(4)
    p[:3, 3] = (dx, dy, dz)
    return p


def _rotation_x(degrees: float) -> np.ndarray:
    a = math.radians(degrees)
    p = np.eye(4)
    p[1:3, 1:3] = [[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]]
    return p


def _scale(factor: float) -> np.ndarray:
    return np.diag([factor, factor, factor, 1.0])


CASES: dict[str, tuple[np.ndarray, DisplayMode, tuple[int, int, int, int] | None]] = {
    # name: (world perturbation, view to show, paint fill or None)
    "good": (np.eye(4), DisplayMode.Z, None),
    "bad_translation": (_translation(0.0, 10.0, 0.0), DisplayMode.Z, FILL_FAIL),
    "bad_rotation": (_rotation_x(8.0), DisplayMode.X, FILL_FAIL),
    "bad_scale": (_scale(1.15), DisplayMode.Z, FILL_FAIL),
    "unsure_subtle": (_translation(0.0, 5.0, 0.0), DisplayMode.Z, FILL_UNSURE),
}


def _set_voxels(data: np.ndarray, affine: np.ndarray, points_mm, value: float) -> None:
    for point in points_mm:
        ijk = np.round(np.linalg.inv(affine) @ np.array([*point, 1.0])).astype(int)[:3]
        i, j, k = np.clip(ijk, 0, np.array(data.shape) - 1)
        data[i, j, k] = value


def _perturbed(src: Path, perturbation: np.ndarray, order: int) -> np.ndarray:
    """The volume's content moved by ``perturbation`` on the unchanged grid.

    Resampling the content (rather than perturbing the affine) keeps every
    case on the identical axis-aligned grid — no reorder resampling, stable
    framing — and matches what a genuinely failed normalization looks like:
    a correctly-gridded file with misplaced anatomy.
    """
    from scipy import ndimage

    img = rois._load(src)
    data = np.asanyarray(img.dataobj).astype(np.float32)
    # output(ijk) = input at voxel A^-1 P^-1 A ijk => content moves by P.
    t = np.linalg.inv(img.affine) @ np.linalg.inv(perturbation) @ img.affine
    return ndimage.affine_transform(data, t[:3, :3], offset=t[:3, 3], order=order)


def _render(
    anat: np.ndarray, mask: np.ndarray, display: DisplayMode, workdir: Path
) -> Image.Image:
    template = rois._load(ANAT)
    artifact = rois.ensure_rois(rois.CANONICAL_SPACE)
    inputs = {"rois": str(artifact.dseg), "roi_meta": str(artifact.meta)}
    for role, data in (("anat", anat), ("mask", mask)):
        path = workdir / f"{role}.nii.gz"
        nb.nifti1.Nifti1Image(data, template.affine, template.header).to_filename(path)
        inputs[role] = str(path)
    blobs = render.render_spatial_normalization(
        inputs=inputs, cuts=[CUT], displays_=[display]
    )
    return Image.open(io.BytesIO(blobs[(display, CUT)])).convert("RGBA")


def render_case(
    perturbation: np.ndarray, display: DisplayMode, workdir: Path
) -> tuple[Image.Image, np.ndarray]:
    """Render one case; also return its perturbed brain mask for marking."""
    template = rois._load(ANAT)
    anat = _perturbed(ANAT, perturbation, order=1)
    mask = _perturbed(MASK, perturbation, order=0)
    _set_voxels(anat, template.affine, _FIDUCIALS_MM, 1.0)
    _set_voxels(mask, template.affine, _FIDUCIALS_MM, 1.0)
    return _render(anat, mask, display, workdir), mask


class PixelMap:
    """Linear world->figure-pixel mapping for one display mode."""

    def __init__(self, world: np.ndarray, pixel: np.ndarray):
        # world: 2x2 [[h1, v1], [h2, v2]]; pixel: 2x2 [[col1, row1], [col2, row2]]
        self.h_scale = (pixel[1, 0] - pixel[0, 0]) / (world[1, 0] - world[0, 0])
        self.h_off = pixel[0, 0] - self.h_scale * world[0, 0]
        self.v_scale = (pixel[1, 1] - pixel[0, 1]) / (world[1, 1] - world[0, 1])
        self.v_off = pixel[0, 1] - self.v_scale * world[0, 1]

    def __call__(self, h: float, v: float) -> tuple[float, float]:
        return self.h_scale * h + self.h_off, self.v_scale * v + self.v_off


def calibrate(
    display: DisplayMode, cut_mm: float, plain: Image.Image, workdir: Path
) -> PixelMap:
    """Solve the world->pixel mapping from two bright in-plane dots.

    Renders the good case again with the two fiducial corners moved into the
    displayed plane and made bright; the dots are the only difference from the
    plain good render, so their pixel centroids fall out of the image diff.
    """
    from scipy import ndimage

    h_axis, v_axis = _DISPLAY_AXES[display]
    dots = []
    for fiducial, inset in ((_FIDUCIALS_MM[0], 10.0), (_FIDUCIALS_MM[1], -10.0)):
        point = [0.0, 0.0, 0.0]
        # Inset from the field-of-view corners (which the fiducials define) so
        # neither dot is clipped at the figure border; both stay on background.
        point[h_axis] = fiducial[h_axis] + inset
        point[v_axis] = fiducial[v_axis] + inset
        point[3 - h_axis - v_axis] = cut_mm
        dots.append(tuple(point))

    template = rois._load(ANAT)
    anat = _perturbed(ANAT, np.eye(4), order=1)
    mask = _perturbed(MASK, np.eye(4), order=0)
    _set_voxels(anat, template.affine, _FIDUCIALS_MM, 1.0)
    _set_voxels(mask, template.affine, _FIDUCIALS_MM, 1.0)
    _set_voxels(anat, template.affine, dots, 1e6)  # clipped to vmax => bright
    _set_voxels(mask, template.affine, dots, 1.0)  # survive skull-stripping
    with_dots = _render(anat, mask, display, workdir)

    diff = np.abs(
        np.asarray(with_dots.convert("L"), dtype=np.float32)
        - np.asarray(plain.convert("L"), dtype=np.float32)
    )
    labeled, n = ndimage.label(diff > 25)
    if n < 2:
        raise RuntimeError(f"expected 2 calibration dots in the diff, found {n}")
    counts = np.bincount(labeled.ravel())[1:]
    keep = np.argsort(counts)[::-1][:2] + 1
    centroids = ndimage.center_of_mass(diff > 25, labeled, keep)  # (row, col) pairs
    # The dot with the smaller vertical world coordinate renders lower in the
    # figure (world v points up, pixel rows point down).
    by_row = sorted(centroids, key=lambda rc: rc[0], reverse=True)
    world = np.array([[d[h_axis], d[v_axis]] for d in dots])  # row 0: smaller v
    pixel = np.array([[rc[1], rc[0]] for rc in by_row])
    return PixelMap(world, pixel)


# Visibility tolerances for the internal-anatomy proxies (mm): the moved
# structure is eroded by this much before testing containment, so only escapes
# a rater can actually see get marked. Sulcal ROIs are wide tolerance bands
# around a thin sulcus, hence the larger erosion.
_FILLED_TOL_MM = 2.0
_SULCAL_TOL_MM = 3.0
_FILLED_GROUPS = frozenset(
    rois.DISPLAY_GROUPS[rois.LABELS[name]]
    for name in ("left_lateral_ventricle", "left_hippocampus")
)


def _accumulate(
    points_world,
    pixmap: PixelMap,
    display: DisplayMode,
    size: tuple[int, int],
    counts: dict[tuple[int, int], int],
) -> None:
    h_axis, v_axis = _DISPLAY_AXES[display]
    cell_w, cell_h, rows = grid_geometry(size)
    for world in points_world:
        col_f, row_f = pixmap(world[h_axis], world[v_axis])
        col, row = int(col_f // cell_w), int(row_f // cell_h)
        if 0 <= col < GRID_COLS and 0 <= row < rows:
            counts[(col, row)] = counts.get((col, row), 0) + 1


def _slice_world_points(
    volume: np.ndarray, affine: np.ndarray, slice_axis: int, k: int
):
    """World coordinates of the true voxels of ``volume``'s displayed slice."""
    for a, b in np.argwhere(np.take(volume, k, axis=slice_axis)):
        ijk = [0, 0, 0]
        ijk[slice_axis] = k
        in_plane = [ax for ax in range(3) if ax != slice_axis]
        ijk[in_plane[0]], ijk[in_plane[1]] = a, b
        yield affine @ np.array([*ijk, 1.0])


def violation_cells(
    mask: np.ndarray,
    perturbation: np.ndarray,
    display: DisplayMode,
    cut_mm: float,
    pixmap: PixelMap,
    size: tuple[int, int],
) -> list[tuple[int, int]]:
    """Cells where anatomy escapes its ROI in the displayed slice.

    Two kinds of escaping anatomy are tested:

    - the subject's **brain edge** (boundary of its perturbed brain mask)
      falling outside the template's outline band;
    - **internal structures**: the subject starts well-normalized, so each
      structure sits where its template ROI is — the ROI region moved by the
      same perturbation is where the subject's structure now is. It is eroded
      by a visibility tolerance and any remainder outside the (unmoved) ROI
      group is a violation — e.g. a ventricle poking out of the orange.
    """
    from scipy import ndimage

    artifact = rois.ensure_rois(rois.CANONICAL_SPACE)
    dseg_img = rois._load(artifact.dseg)
    dseg = np.asarray(dseg_img.dataobj).astype(np.uint8)
    band = dseg == rois.LABELS["brain_band"]
    inv_dseg = np.linalg.inv(dseg_img.affine)

    template = rois._load(ANAT)
    affine = template.affine
    slice_axis = 3 - sum(_DISPLAY_AXES[display])
    counts: dict[tuple[int, int], int] = {}

    # Brain edge vs outline band.
    k = round((cut_mm - affine[slice_axis, 3]) / affine[slice_axis, slice_axis])
    mask2d = np.take(mask, k, axis=slice_axis) > 0
    boundary2d = mask2d ^ ndimage.binary_erosion(mask2d)
    boundary = np.zeros(mask.shape, dtype=bool)
    np.moveaxis(boundary, slice_axis, 0)[k] = boundary2d

    def outside_band(world) -> bool:
        # Skip the injected fiducial voxels — they are not anatomy.
        if any(np.allclose(world[:3], f, atol=2.0) for f in _FIDUCIALS_MM):
            return False
        r = np.round(inv_dseg @ world).astype(int)[:3]
        inside = all(0 <= r[ax] < band.shape[ax] for ax in range(3))
        return not (inside and band[r[0], r[1], r[2]])

    _accumulate(
        (
            w
            for w in _slice_world_points(boundary, affine, slice_axis, k)
            if outside_band(w)
        ),
        pixmap,
        display,
        size,
        counts,
    )

    # Internal structures vs their ROI groups, on the ROI grid.
    t = np.linalg.inv(dseg_img.affine) @ np.linalg.inv(perturbation) @ dseg_img.affine
    moved = ndimage.affine_transform(dseg, t[:3, :3], offset=t[:3, 3], order=0)
    k_roi = round(
        (cut_mm - dseg_img.affine[slice_axis, 3])
        / dseg_img.affine[slice_axis, slice_axis]
    )
    groups: dict[int, list[int]] = {}
    for label, group in rois.DISPLAY_GROUPS.items():
        if label != rois.LABELS["brain_band"]:
            groups.setdefault(group, []).append(label)
    for group, labels in groups.items():
        tol = _FILLED_TOL_MM if group in _FILLED_GROUPS else _SULCAL_TOL_MM
        proxy = ndimage.binary_erosion(
            np.isin(moved, labels), rois._ellipsoid(tol, (1.0, 1.0, 1.0))
        )
        violation = proxy & ~np.isin(dseg, labels)
        _accumulate(
            _slice_world_points(violation, dseg_img.affine, slice_axis, k_roi),
            pixmap,
            display,
            size,
            counts,
        )

    cells = {cell for cell, n in counts.items() if n >= _MIN_POINTS_PER_CELL}
    # Drop isolated single cells (a real violation spans neighboring cells;
    # lone marks are edge-discretization or subject-baseline wobble).
    return [
        (c, r)
        for c, r in cells
        if any(
            (c + dc, r + dr) in cells
            for dc in (-1, 0, 1)
            for dr in (-1, 0, 1)
            if (dc, dr) != (0, 0)
        )
    ]


def grid_geometry(size: tuple[int, int]) -> tuple[float, float, int]:
    """Cell width/height and row count, exactly as clicks.js computes them."""
    width, height = size
    cell_w = width / GRID_COLS
    rows = max(1, round(height / cell_w))
    return cell_w, height / rows, rows


def draw_grid(image: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cell_w, cell_h, rows = grid_geometry(image.size)
    for c in range(1, GRID_COLS):
        draw.line([(c * cell_w, 0), (c * cell_w, image.size[1])], fill=GRID_LINE)
    for r in range(1, rows):
        draw.line([(0, r * cell_h), (image.size[0], r * cell_h)], fill=GRID_LINE)
    return Image.alpha_composite(image, overlay)


def paint_cells(
    image: Image.Image, cells: list[tuple[int, int]], fill: tuple[int, int, int, int]
) -> Image.Image:
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    cell_w, cell_h, _ = grid_geometry(image.size)
    for c, r in cells:
        draw.rectangle(
            [c * cell_w, r * cell_h, (c + 1) * cell_w, (r + 1) * cell_h], fill=fill
        )
    return Image.alpha_composite(image, overlay)


def save_avif(image: Image.Image, path: Path) -> None:
    image.convert("RGB").save(path, quality=100, subsampling="4:4:4", speed=6)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    artifact = rois.ensure_rois(rois.CANONICAL_SPACE)
    cuts = rois.load_cuts(artifact.meta)

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        renders = {
            name: render_case(perturbation, display, workdir)
            for name, (perturbation, display, _) in CASES.items()
        }
        pixmaps: dict[DisplayMode, PixelMap] = {}
        for _, display, fill in CASES.values():
            if fill is not None and display not in pixmaps:
                cut_mm = cuts[display.name.lower()][CUT]
                plain, _ = (
                    renders["good"]
                    if display == CASES["good"][1]
                    else render_case(np.eye(4), display, workdir)
                )
                pixmaps[display] = calibrate(display, cut_mm, plain, workdir)

    for name, (perturbation, display, fill) in CASES.items():
        image, mask = renders[name]
        with_grid = draw_grid(image)
        save_avif(with_grid, OUT_DIR / f"{name}.avif")
        print(f"wrote {name}.avif")
        if fill is not None:
            cells = violation_cells(
                mask,
                perturbation,
                display,
                cuts[display.name.lower()][CUT],
                pixmaps[display],
                image.size,
            )
            marked = paint_cells(with_grid, cells, fill)
            save_avif(marked, OUT_DIR / f"{name}_marked.avif")
            print(f"wrote {name}_marked.avif ({len(cells)} cells)")


if __name__ == "__main__":
    main()
