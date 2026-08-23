from typing import TYPE_CHECKING

from django.db import models
from django.utils import timezone

if TYPE_CHECKING:
    # Stub-only (django-stubs): the type of a reverse FK accessor. Declaring the
    # accessors below as plain annotations gives them types without the mypy
    # plugin; Django ignores un-assigned annotations, so no field is created.
    from django.db.models.fields.related_descriptors import RelatedManager

DEFAULT_GRID_COLS = 28
"""Default number of columns in the annotation grid (see ``Step.grid_cols``)."""


class Step(models.IntegerChoices):
    MASK = 0
    SPATIAL_NORMALIZATION = 1
    SURFACE_LOCALIZATION = 2
    FMAP_COREGISTRATION = 3
    DTIFIT = 4

    @property
    def image_type(self) -> str:
        """MIME subtype of the figures stored for this step.

        Every step stores AVIF: a single frame for the static views
        (mask, spatial normalization, surface localization) and an animation for
        the multi-frame views (fmap coregistration, dtifit).
        """
        return "avif"

    @property
    def related_name(self) -> str:
        """Related query name from Image to this step's submission model."""
        match self:
            case Step.MASK | Step.SPATIAL_NORMALIZATION | Step.SURFACE_LOCALIZATION:
                return "annotation"
            case _:
                return "rating"

    @property
    def grid_cols(self) -> int:
        """Columns in the annotation grid overlaid on this step's images.

        Rows are derived on the client from the image aspect ratio and
        recorded per-submission on ``Annotation``.
        """
        return DEFAULT_GRID_COLS

    @property
    def cli_name(self) -> str:
        """The step's CLI/plan token (matches its ``StepSpec`` name).

        Canonical, web-safe name↔Step mapping so the review plan (``plan.py``)
        and forms can resolve step tokens without importing the ingest registry
        (which pulls in the neuro stack).
        """
        match self:
            case Step.MASK:
                return "masks"
            case Step.SPATIAL_NORMALIZATION:
                return "spatial_normalization"
            case Step.SURFACE_LOCALIZATION:
                return "surface_localization"
            case Step.FMAP_COREGISTRATION:
                return "fmap_coregistration"
            case Step.DTIFIT:
                return "dtifit"
        raise AssertionError(f"unhandled step {self!r}")

    @classmethod
    def from_cli_name(cls, name: str) -> "Step":
        """The Step for a CLI/plan token; raises ``ValueError`` if unknown."""
        for step in cls:
            if step.cli_name == name:
                return step
        raise ValueError(f"unknown step {name!r}")


class Ratings(models.IntegerChoices):
    PASS = 0
    UNSURE = 1
    FAIL = 2


class DisplayMode(models.IntegerChoices):
    X = 0
    Y = 1
    Z = 2


class ReviewStrategy(models.TextChoices):
    """How the next image to review is chosen (see ``ordering.py``).

    ``TextChoices`` (str-valued, with ``.choices``/``.values``) so the same enum
    serves both the review-plan TOML validation and the ``Session.strategy`` field.
    """

    # fewest reviews first (the default)
    BREADTH_FIRST = "breadth_first"
    # breadth backbone, most-atypical re-ranked within a review-depth band
    ANOMALY_FIRST = "anomaly_first"
    # anomaly_first restricted to under-reviewed images (a failure hunt)
    TRIAGE = "triage"


class MetricDirection(models.TextChoices):
    """Which values of a measure are "atypical" (drive ``Image.priority``)."""

    TWO_SIDED = "two_sided"  # atypical either way is suspect (e.g. mask volume)
    HIGHER_WORSE = "higher_worse"  # larger is more suspect (e.g. motion fd_mean)
    LOWER_WORSE = "lower_worse"  # smaller is more suspect (e.g. snr, cnr)


class BaseModel(models.Model):
    id: int  # the auto pk (django-stubs declares only `pk` without the plugin)
    created_at = models.DateTimeField(db_index=True, default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ReviewPlan(BaseModel):
    """A persisted ``dirt.toml`` review plan — the QC provenance for a dataset.

    Stored verbatim (``toml``) with a ``content_hash`` so re-applying an identical
    plan is idempotent. ``render`` stamps each :class:`Image` it produces with the
    active plan (the "pipeline facet": what was measured); a rating :class:`Session`
    copies the plan's serving facet (strategy/triage_depth) onto itself. Exactly one
    plan is ``is_active`` at a time.
    """

    name = models.TextField(default="", blank=True)
    content_hash = models.TextField(unique=True)
    toml = models.TextField()
    is_active = models.BooleanField(default=False)


class Session(BaseModel):
    step = models.IntegerField(choices=Step.choices)
    user = models.TextField(default=None, null=True, blank=True)
    # Serving facet of the active ReviewPlan, pinned at session start so editing the
    # plan mid-review never disturbs an in-flight session.
    strategy = models.TextField(
        choices=ReviewStrategy.choices, default=ReviewStrategy.BREADTH_FIRST
    )
    triage_depth = models.PositiveIntegerField(default=1)


class Image(BaseModel):
    img = models.BinaryField()
    slice = models.IntegerField(null=True, blank=True)
    file1 = models.TextField(max_length=512)
    file2 = models.TextField(max_length=512, null=True, blank=True)
    display = models.IntegerField(choices=DisplayMode.choices)
    step = models.IntegerField(choices=Step.choices)
    n_reviews = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Denormalized count of review submissions (Rating/Annotation rows) for "
            "this image, maintained by the services layer. Lets the review-ordering "
            "selector find the least-reviewed image with an index seek instead of an "
            "aggregate scan over every image of a step."
        ),
    )
    priority = models.FloatField(
        null=True,
        blank=True,
        help_text=(
            "Advisory ordering key for the anomaly_first/triage strategies, computed "
            "by `manage prioritize` as a robust within-subgroup modified z-score "
            "(MAD-based; |z| for two-sided measures). Larger = more atypical, "
            "surfaced earlier; 0.0 = typical (including a subgroup with no "
            "meaningful spread); NULL = no measure (sorts after scored images, i.e. "
            "breadth-first fallback). Only ever reorders — it never filters or hides "
            "an image."
        ),
    )
    raw_metrics = models.JSONField(
        null=True,
        blank=True,
        help_text=(
            "Measured values + rational-subgroup entities harvested at ingest, e.g. "
            "{'volume_mm3': 1.23e6, 'space': 'MNI152NLin2009cAsym'}. The source "
            "`manage prioritize` recomputes `priority` from."
        ),
    )
    review_plan = models.ForeignKey(
        "ReviewPlan",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        help_text="The plan under which this image was rendered and measured.",
    )
    review_plan_id: int | None

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=["slice", "file1", "display", "step"], name="image_meta"
            ),
        )
        indexes = (
            # Serves the breadth_first strategy: filter by step, order by
            # (n_reviews, id) — an index range seek returning one leaf entry.
            models.Index(fields=["step", "n_reviews", "id"], name="image_next"),
            # Serves anomaly_first/triage: order by (n_reviews, priority desc nulls
            # last, id). -priority matches F("priority").desc(nulls_last=True) so the
            # whole order is a covering forward scan — a single leaf seek, no sort.
            models.Index(
                fields=["step", "n_reviews", "-priority", "id"], name="image_priority"
            ),
        )


class FromRequest(BaseModel):
    """Abstract base for models submitted during a rating session."""

    class Meta:
        abstract = True

    image = models.ForeignKey(Image, on_delete=models.CASCADE)
    image_id: int
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    session_id: int
    source_data_issue = models.BooleanField(
        default=False,
        verbose_name="I suspect there might be a problem with the image quality",
    )
    comments = models.TextField(
        default="",
        help_text="Please only add additional comments if necessary.",
        blank=True,
    )


class Annotation(FromRequest):
    """One annotation submission: the grid used and the cells marked on it.

    A submission with no marked cells (zero related ``AnnotationCell`` rows)
    records an image where the rater found nothing to mark but may have left
    flags or comments.
    """

    grid_cols = models.IntegerField()
    grid_rows = models.IntegerField()
    cells: "RelatedManager[AnnotationCell]"


class AnnotationCell(models.Model):
    """A single grid cell a rater marked as a problem.

    ``rating`` reuses the whole-image ``Ratings`` vocabulary: a marked cell is
    UNSURE (rater not confident) or FAIL (confident problem); PASS is implied
    by a cell being left unmarked.
    """

    annotation = models.ForeignKey(
        Annotation, on_delete=models.CASCADE, related_name="cells"
    )
    col = models.IntegerField()
    row = models.IntegerField()
    rating = models.IntegerField(choices=Ratings.choices)

    class Meta:
        constraints = (
            models.UniqueConstraint(
                fields=["annotation", "col", "row"], name="annotation_cell"
            ),
        )


class Rating(FromRequest):
    rating = models.IntegerField(choices=Ratings.choices, verbose_name="")
