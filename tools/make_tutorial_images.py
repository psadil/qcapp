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
simply a smaller perturbation, so only a few cells violate.

Failure modes are simulated by resampling the T1w *and its brain mask* through
the same world-space perturbation (translation / rotation / scale) on the
unchanged grid, i.e. the subject's anatomy moves relative to the template
landmarks, exactly like a failed normalization.

Outputs (commit these): docs/assets/tutorial/spatial_normalization/*.avif
Re-run whenever the spatial-normalization rendering style changes.

Run:  pixi run -e dev tutorial-images
"""

from __future__ import annotations

import io
import math
import sys
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

from matplotlib import pyplot as plt
from nilearn import image as nl_image

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


def _figure(anat: np.ndarray, mask: np.ndarray, display: DisplayMode, cut_mm: float):
    """The renderer's own figure for one perturbed volume.

    Goes through ``render.spatial_normalization_figure`` rather than
    ``render_spatial_normalization``: the same drawing code, minus the load-from-
    disk wrapper, so the figure — and the axes whose transform maps world
    coordinates to pixels — is in hand. The two lines of prep the wrapper does
    around it are mirrored here; keep them in step.
    """
    template = rois._load(ANAT)
    artifact = rois.ensure_rois(rois.CANONICAL_SPACE)
    volumes = (
        nb.nifti1.Nifti1Image(data, template.affine, template.header)
        for data in (anat, mask)
    )
    file_nii = nl_image.reorder_img(
        render._skull_strip(*volumes), resample="continuous"
    )
    return render.spatial_normalization_figure(
        file_nii,
        render._roi_img(str(artifact.dseg)),
        cut_mm,
        display,
        render._roi_bounds(str(artifact.dseg))[display.name.lower()],
    )


def render_case(
    perturbation: np.ndarray, display: DisplayMode, cut_mm: float
) -> tuple[Image.Image, np.ndarray, PixelMap]:
    """Render one case; also return its perturbed brain mask and pixel map."""
    anat = _perturbed(ANAT, perturbation, order=1)
    mask = _perturbed(MASK, perturbation, order=0)
    figure, slicer = _figure(anat, mask, display, cut_mm)
    with io.BytesIO() as buffer:
        figure.savefig(buffer, backend="Agg", format="png")
        image = Image.open(io.BytesIO(buffer.getvalue())).convert("RGBA")
    pixmap = PixelMap(figure, next(iter(slicer.axes.values())).ax, image.size)
    plt.close(figure)
    return image, mask, pixmap


class PixelMap:
    """World -> figure-pixel mapping for one rendered panel.

    The renderer pins every figure's frame to the landmark bounding box, so the
    axes' own data transform *is* the mapping: exact, and free. (It used to be
    solved by rendering the volume twice with two bright dots at known world
    coordinates and recovering their centroids from the image diff. Pinning the
    frame made that unnecessary — and put the dots outside the field of view.)
    """

    def __init__(self, figure, ax, size: tuple[int, int]):
        figure.canvas.draw()  # the transform is only final once laid out
        # Data -> *figure fraction*, then out to the saved image's pixels.
        # Display pixels would be wrong: an interactive canvas renders at the
        # screen's device pixel ratio (2x here), while savefig writes at the
        # figure's own dpi — the map has to be free of both.
        self._transform = (ax.transData + figure.transFigure.inverted()).frozen()
        self._width, self._height = size

        # The frame is the whole of what was drawn, so its corners must land on
        # the image — a silent factor here would paint every marked cell in the
        # wrong place, which is not something the output announces.
        corners = [self(h, v) for h in ax.get_xlim() for v in ax.get_ylim()]
        if any(
            not (-1 <= col <= self._width + 1 and -1 <= row <= self._height + 1)
            for col, row in corners
        ):
            raise RuntimeError(
                f"world->pixel map puts the {self._width}x{self._height} frame's "
                f"corners at {[tuple(round(v, 1) for v in c) for c in corners]}"
            )

    def __call__(self, h: float, v: float) -> tuple[float, float]:
        fraction_x, fraction_y = self._transform.transform((h, v))
        # Matplotlib measures up from the bottom; image rows count down.
        return fraction_x * self._width, (1.0 - fraction_y) * self._height


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

    for name, (perturbation, display, fill) in CASES.items():
        cut_mm = cuts[display.name.lower()][CUT]
        image, mask, pixmap = render_case(perturbation, display, cut_mm)
        with_grid = draw_grid(image)
        save_avif(with_grid, OUT_DIR / f"{name}.avif")
        print(f"wrote {name}.avif")
        if fill is None:
            continue
        cells = violation_cells(mask, perturbation, display, cut_mm, pixmap, image.size)
        marked = paint_cells(with_grid, cells, fill)
        save_avif(marked, OUT_DIR / f"{name}_marked.avif")
        print(f"wrote {name}_marked.avif ({len(cells)} cells)")


if __name__ == "__main__":
    main()
