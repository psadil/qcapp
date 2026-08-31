"""Static landmark reference figures, resolved for a served image.

The rating page shows, beside each subject slice, the same cut of the template
it was normalized to, with every landmark band drawn and named. Those figures
are per space — not per subject — so they are rendered once by
``tools/make_reference_images.py`` and committed as static assets rather than
stored per image: the web process carries only Django, and could not draw them.

Which spaces have figures is spelled out here rather than probed off the disk,
so a missing asset is a failing test (see ``tests/ingest/test_reference.py``)
instead of a silently blank panel. It mirrors the equally deliberate list of
spaces DIRT can build ROIs for (``management.ingest.rois._RECIPES``), which this
module cannot import — that pulls in the neuro stack.
"""

from django.templatetags import static

from django_dirt_ratings import models

SPACES = frozenset({"MNI152NLin2009cAsym", "MNI152NLin6Asym"})
"""Template spaces with committed reference figures."""

STEPS = frozenset({models.Step.SPATIAL_NORMALIZATION})
"""Steps whose figures carry landmark bands, and so have a reference.

Other steps are rendered in a template space too, but with no landmarks on
them — a landmark key beside one would explain marks that are not there.
"""


def static_path(
    *,
    space: str | None,
    cohort: str | None,
    display: int,
    slice: int | None,
) -> str | None:
    """The static-file path of the reference figure for one served image.

    ``None`` — no panel — whenever the pairing cannot be made exactly: an image
    whose space was never recorded, a space with no committed figures, or a
    single-image step with no cut. A rater is shown the right reference or no
    reference; never a neighbouring slice's.
    """
    if space is None or space not in SPACES or slice is None:
        return None
    cohort_part = f"_cohort-{cohort}" if cohort else ""
    axis = models.DisplayMode(display).name.lower()
    return f"ratings/reference/tpl-{space}{cohort_part}/{axis}-{slice}.avif"


def reference_url(
    *,
    space: str | None,
    cohort: str | None,
    display: int,
    slice: int | None,
) -> str | None:
    """The URL of the reference figure for one served image, or ``None``."""
    path = static_path(space=space, cohort=cohort, display=display, slice=slice)
    return static.static(path) if path else None
