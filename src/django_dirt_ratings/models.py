from django.contrib.gis.db import models as gm
from django.db import models
from django.utils import timezone

GEOMETRY_SRID = -1
"""Annotations store canvas pixel coordinates, not geographic ones.

SpatiaLite's "undefined" srid is -1; srid 0 cannot be used because GEOS
treats 0 as "no srid set" and Django then emits invalid SQL.
"""


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
    """A clicked point on an image, in canvas pixel coordinates.

    A null geometry records a submission with no clicked points, i.e. an
    image where the rater found nothing to mark but may have left flags or
    comments.
    """

    geometry = gm.GeometryField(
        srid=GEOMETRY_SRID, spatial_index=False, null=True, blank=True
    )


class Rating(FromRequest):
    rating = models.IntegerField(choices=Ratings.choices, verbose_name="")
