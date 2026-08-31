"""Generate the labeled landmark reference figures (dev-time).

Two outputs, both drawn by one ``panel`` routine so what a rater sees beside a
subject image and what the tutorial teaches are the same picture:

- **In-app reference stills**, one per ``(space, display, cut)``, committed under
  ``src/django_dirt_ratings/static/ratings/reference/``. The rating page shows
  the still matching the subject slice on screen: same space, same cut, same
  frame — "this is what it should look like".
- **The tutorial montage**, ``docs/assets/tutorial/spatial_normalization/
  roi_montage.avif``: three orthogonal views of the canonical template that
  between them name every landmark band.

Panels are drawn through the app's own renderer
(``render.spatial_normalization_figure``) over the space's TemplateFlow T1w,
skull-stripped exactly as a subject's is, so the reference differs from a
subject image only in whose brain is underneath. The frame is pinned to the
landmark bounding box (see ``render._roi_bounds``), which is what makes the two
comparable at all.

Every band visible in a slice is labeled: a rater must never meet a colored
region the reference does not name. Labels are placed at the structure, then
de-overlapped and clamped inside the frame in pixel space.

Outputs are committed. Re-run whenever the landmark ROIs, the palette, or the
spatial-normalization rendering style changes.

Run:  pixi run -e dev reference-images
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dirt.settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "reference-images-not-a-secret")
django.setup()

from matplotlib import patheffects
from matplotlib import pyplot as plt
from nilearn import image as nl_image
from scipy import ndimage

from django_dirt_ratings.management.ingest import loading, render, rois
from django_dirt_ratings.models import DisplayMode

STATIC_DIR = REPO / "src" / "django_dirt_ratings" / "static" / "ratings" / "reference"
MONTAGE = (
    REPO / "docs" / "assets" / "tutorial" / "spatial_normalization" / "roi_montage.avif"
)

# Rendered larger than the 640x480 subject stills: these are static assets a
# browser caches once, and the extra pixels keep the drawn labels crisp on a
# high-density display. The frame — and so the geometry — is identical.
DPI = 150

# The world axes shown horizontally and vertically for each display mode, and
# the axis being cut. Mirrors nilearn's CutAxes.draw_2d.
_IN_PLANE = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}
_CUT_AXIS = {"x": 0, "y": 1, "z": 2}

# A display group needs at least this many in-plane voxels before it is worth
# naming: below it, all that shows is a speck of a structure the slice clips.
_MIN_VOXELS = 25

_LABEL_KWARGS = {"fontsize": 10, "fontweight": "bold", "ha": "center", "va": "center"}
# Keep labels off the frame edge by this fraction of the panel.
_INSET = 0.015

# The montage's three views: one of each orientation, together naming every
# band. Checked before it is built, so a change to the ROIs fails loudly rather
# than quietly dropping a structure from the tutorial.
_MONTAGE_VIEWS = (("x", 2), ("y", 0), ("z", 1))
_GAP = 24
_RULE = "#444444"


def _template(space: str, cohort: str | None):
    """The space's own T1w, skull-stripped the way a subject's is."""
    t1w = rois._tf_get(space, cohort, suffix="T1w", desc=None, resolution=1)
    mask = rois._tf_get(space, cohort, suffix="mask", desc="brain", resolution=1)
    stripped = render._skull_strip(
        loading.load_nifti(str(t1w)), loading.load_nifti(str(mask))
    )
    return nl_image.reorder_img(stripped, resample="continuous")


def _slice_groups(grouped, affine, axis: str, coord: float) -> dict[int, np.ndarray]:
    """World (h, v) coordinates of each display group's biggest blob in a slice.

    Biggest *connected* blob, not every voxel: a bilateral structure (both
    hippocampi, both calcarine sulci) would otherwise be labeled at the midline
    between its two halves, pointing at neither.
    """
    cut_axis = _CUT_AXIS[axis]
    k = round((coord - affine[cut_axis, 3]) / affine[cut_axis, cut_axis])
    plane = np.take(grouped, k, axis=cut_axis)
    h_axis, v_axis = _IN_PLANE[axis]
    in_plane = [ax for ax in range(3) if ax != cut_axis]

    found: dict[int, np.ndarray] = {}
    for group in np.unique(plane):
        if group == 0:
            continue
        blobs, _ = ndimage.label(plane == group)
        sizes = np.bincount(blobs.ravel())[1:]
        rows, cols = np.nonzero(blobs == np.argmax(sizes) + 1)
        if rows.size < _MIN_VOXELS:
            continue
        ijk = np.ones((4, rows.size))
        ijk[cut_axis] = k
        ijk[in_plane[0]] = rows
        ijk[in_plane[1]] = cols
        world = affine @ ijk
        found[int(group)] = np.vstack([world[h_axis], world[v_axis]])
    return found


def _anchor(group: int, points: np.ndarray, bounds) -> tuple[float, float]:
    """Where a group's label wants to sit, in world coordinates.

    The median of a compact blob is inside it. The brain band is a ring, whose
    median is the middle of the brain — nowhere near the band — so it is
    anchored on the band itself, at the point beside the brain that is furthest
    from the frame edges.
    """
    h, v = points
    if group != rois.DISPLAY_GROUPS[rois.LABELS["brain_band"]]:
        return float(np.median(h)), float(np.median(v))
    h0, h1, v0, v1 = bounds
    clearance = np.minimum(
        np.minimum(h - h0, h1 - h) / (h1 - h0), np.minimum(v - v0, v1 - v) / (v1 - v0)
    )
    best = int(np.argmax(clearance))
    return float(h[best]), float(v[best])


def _place(ax, texts: list, inset_px: tuple[float, float]) -> None:
    """Nudge drawn labels apart, then inside the frame — in pixel space.

    Pixel space because that is where legibility lives: text extents are known
    only after drawing, and an overlap of two millimetres means nothing while an
    overlap of two pixels is what the reader sees. Labels are never dropped, so
    every visible band keeps its name.
    """
    figure = ax.get_figure()
    figure.canvas.draw()  # text extents exist only once rendered
    renderer = figure.canvas.get_renderer()
    frame = ax.get_window_extent()
    inset_x, inset_y = inset_px

    placed: list = []
    for text in texts:
        for _ in range(24):
            box = text.get_window_extent(renderer)
            overlaps = [other for other in placed if box.overlaps(other)]
            if not overlaps:
                break
            drop = max(other.y0 for other in overlaps) - box.y1 - 2.0
            _shift(ax, text, 0.0, drop)
        box = text.get_window_extent(renderer)
        dx = max(0.0, frame.x0 + inset_x - box.x0) - max(
            0.0, box.x1 - (frame.x1 - inset_x)
        )
        dy = max(0.0, frame.y0 + inset_y - box.y0) - max(
            0.0, box.y1 - (frame.y1 - inset_y)
        )
        _shift(ax, text, dx, dy)
        placed.append(text.get_window_extent(renderer))


def _shift(ax, text, dx: float, dy: float) -> None:
    """Move a text by a pixel offset, keeping it positioned in data coordinates."""
    if dx == 0.0 and dy == 0.0:
        return
    x, y = ax.transData.transform(text.get_position())
    text.set_position(ax.transData.inverted().transform((x + dx, y + dy)))


def panel(artifact, space: str, axis: str, cut: int, dpi: int = DPI) -> Image.Image:
    """One labeled reference slice, as an RGB image."""
    display = DisplayMode[axis.upper()]
    coord = rois.load_cuts(artifact.meta)[axis][cut]
    roi_nii = render._roi_img(str(artifact.dseg))
    bounds = render._roi_bounds(str(artifact.dseg))[axis]

    figure, slicer = render.spatial_normalization_figure(
        _template(space, None), roi_nii, coord, display, bounds
    )
    ax = next(iter(slicer.axes.values())).ax
    groups = _slice_groups(
        np.asanyarray(roi_nii.dataobj).astype(np.uint8), roi_nii.affine, axis, coord
    )
    texts = []
    # Largest first: the biggest structure gets the spot it wants, and the
    # smaller ones move around it.
    for group in sorted(groups, key=lambda g: -groups[g].shape[1]):
        h, v = _anchor(group, groups[group], bounds)
        text = ax.text(
            h,
            v,
            rois.DISPLAY_NAMES[group - 1],
            color=rois.DISPLAY_COLORS[group - 1],
            zorder=10,
            **_LABEL_KWARGS,
        )
        text.set_path_effects([patheffects.withStroke(linewidth=2.4, foreground="k")])
        texts.append(text)
    frame = ax.get_window_extent()
    _place(ax, texts, (_INSET * frame.width, _INSET * frame.height))

    print(f"  {axis}={coord:g}: {', '.join(t.get_text() for t in texts)}")
    with io.BytesIO() as buffer:
        figure.savefig(buffer, backend="Agg", format="png", dpi=dpi)
        plt.close(figure)
        return Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")


def save_avif(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, quality=100, subsampling="4:4:4", speed=6)


def stills(space: str) -> dict[tuple[str, int], Image.Image]:
    """Every reference still for a space, written under the app's static dir."""
    artifact = rois.ensure_rois(space)
    cuts = rois.load_cuts(artifact.meta)
    print(f"{space}:")
    rendered = {}
    for axis, coords in cuts.items():
        for cut in range(len(coords)):
            img = panel(artifact, space, axis, cut)
            save_avif(img, STATIC_DIR / f"tpl-{space}" / f"{axis}-{cut}.avif")
            rendered[(axis, cut)] = img
    return rendered


def _cropped(img: Image.Image) -> Image.Image:
    """The panel without its empty margin, keeping the drawn annotations."""
    box = img.convert("L").point(lambda v: 255 if v > 8 else 0).getbbox()
    return img if box is None else img.crop(box)


def montage(panels: dict[tuple[str, int], Image.Image]) -> None:
    """Stack the three tutorial views into one figure, one per orientation.

    Stacked rather than tiled side by side because the labels have to survive
    being scaled to the width of a documentation page: three panels in a row
    would each render a third as wide, and the names with them. Panels are
    cropped to their content first — unlike the in-app stills, which keep the
    renderer's exact frame so they overlay the subject image they sit beside.
    """
    chosen = [_cropped(panels[view]) for view in _MONTAGE_VIEWS]
    width = max(img.width for img in chosen)
    out = Image.new(
        "RGB",
        (width, sum(img.height for img in chosen) + _GAP * (len(chosen) - 1)),
        "black",
    )
    top = 0
    for index, img in enumerate(chosen):
        if index:
            # A hairline so three views on a black field read as three views.
            out.paste(_RULE, (0, top + _GAP // 2, width, top + _GAP // 2 + 1))
            top += _GAP
        out.paste(img, ((width - img.width) // 2, top))
        top += img.height
    save_avif(out, MONTAGE)


def _refuse_a_montage_that_skips_a_band(artifact) -> None:
    """The montage is the tutorial's only key: it has to name all of them."""
    roi_nii = render._roi_img(str(artifact.dseg))
    grouped = np.asanyarray(roi_nii.dataobj).astype(np.uint8)
    cuts = rois.load_cuts(artifact.meta)
    named: set[int] = set()
    for axis, cut in _MONTAGE_VIEWS:
        named |= set(_slice_groups(grouped, roi_nii.affine, axis, cuts[axis][cut]))
    missing = set(rois.DISPLAY_GROUPS.values()) - named
    if missing:
        raise SystemExit(
            "the montage views no longer name every landmark; missing "
            + ", ".join(sorted(rois.DISPLAY_NAMES[group - 1] for group in missing))
        )


def main() -> None:
    panels = {space: stills(space) for space in sorted(rois._RECIPES)}
    _refuse_a_montage_that_skips_a_band(rois.ensure_rois(rois.CANONICAL_SPACE))
    montage(panels[rois.CANONICAL_SPACE])
    print(f"wrote {MONTAGE.relative_to(REPO)}")
    print(
        f"wrote {len(list(STATIC_DIR.rglob('*.avif')))} stills "
        f"under {STATIC_DIR.relative_to(REPO)}"
    )


if __name__ == "__main__":
    main()
