"""The committed reference figures must keep up with the ROI recipes.

``reference.py`` lives in the web layer and cannot import the ingest stack, so
the spaces it serves figures for are written out by hand. This is what keeps
that list honest — and catches a space gaining an ROI recipe without anyone
running ``pixi run -e dev reference-images``.
"""

import pytest
from django.contrib.staticfiles import finders

from django_dirt_ratings import models, reference
from django_dirt_ratings.management.ingest import rois

SLICES = [
    (space, display, cut)
    for space in sorted(reference.SPACES)
    for display in models.DisplayMode
    for cut in range(len(rois.CUT_FRACTIONS["x"]))
]


def _path(space: str, display: models.DisplayMode, cut: int) -> str:
    """The static path for one figure, refusing to proceed without one."""
    path = reference.static_path(
        space=space, cohort=None, display=int(display), slice=cut
    )
    if path is None:
        raise AssertionError(f"{space} is in reference.SPACES but resolves no figure")
    return path


def test_every_space_with_a_recipe_has_reference_figures():
    assert reference.SPACES == frozenset(rois._RECIPES)


@pytest.mark.parametrize(
    "space, display, cut",
    SLICES,
    ids=[f"{s}-{d.name.lower()}{c}" for s, d, c in SLICES],
)
def test_the_figure_a_served_image_asks_for_is_committed(space, display, cut):
    path = _path(space, display, cut)

    assert finders.find(path) is not None


def test_a_space_without_figures_gets_none():
    assert (
        reference.static_path(space="MNI152NLin6Sym", cohort=None, display=0, slice=0)
        is None
    )


def test_an_image_with_no_cut_gets_none():
    assert (
        reference.static_path(
            space=rois.CANONICAL_SPACE, cohort=None, display=0, slice=None
        )
        is None
    )
