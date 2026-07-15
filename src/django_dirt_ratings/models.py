from django.db import models
from django.utils import timezone

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
        """MIME subtype of the figures stored for this step."""
        match self:
            case Step.FMAP_COREGISTRATION | Step.DTIFIT:
                return "apng"
            case _:
                return "png"

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


class Ratings(models.IntegerChoices):
    PASS = 0
    UNSURE = 1
    FAIL = 2


class DisplayMode(models.IntegerChoices):
    X = 0
    Y = 1
    Z = 2


class BaseModel(models.Model):
    created_at = models.DateTimeField(db_index=True, default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Session(BaseModel):
    step = models.IntegerField(choices=Step.choices)
    user = models.TextField(default=None, null=True, blank=True)


class Image(BaseModel):
    img = models.BinaryField()
    slice = models.IntegerField(null=True, blank=True)
    file1 = models.TextField(max_length=512)
    file2 = models.TextField(max_length=512, null=True, blank=True)
    display = models.IntegerField(choices=DisplayMode.choices)
    step = models.IntegerField(choices=Step.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["slice", "file1", "display", "step"], name="image_meta"
            )
        ]


class FromRequest(BaseModel):
    """Abstract base for models submitted during a rating session."""

    class Meta:
        abstract = True

    image = models.ForeignKey(Image, on_delete=models.CASCADE)
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
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
        constraints = [
            models.UniqueConstraint(
                fields=["annotation", "col", "row"], name="annotation_cell"
            )
        ]


class Rating(FromRequest):
    rating = models.IntegerField(choices=Ratings.choices, verbose_name="")
