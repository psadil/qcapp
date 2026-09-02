"""The image-ingest API: how rendered units get from a render machine onto a
deployment, and how review results come back out.

A unit — one measured file with its 9-15 rendered views — is pushed as one
multipart request carrying two *file* parts: its metadata as JSON and its
images as a tar. Both parts are files on purpose: ``DATA_UPLOAD_MAX_MEMORY_SIZE``
is calculated excluding file upload data, so the payload travels without
weakening the 2.5 MB guard on the login form and the rating POST. A push
either lands or is retried, and retries are idempotent on the unit's
``image_meta`` identities.

Everything is authenticated (HTTP Basic against an account in the ``ingest``
group) and inert unless ``settings.INGEST_ENABLED`` is on. Thin, like
``views.py``: parse, hand to a service, return a schema.
"""

import ninja
import orjson
import pydantic
from django import http
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core import exceptions as django_exceptions
from ninja import File, Schema, UploadedFile, parser, renderers
from ninja.security import HttpBasicAuth

from django_dirt_ratings import (
    exceptions,
    models,
    plan,
    prioritizing,
    selectors,
    services,
    storage,
    transfer,
)

#: Membership in this stock auth Group is what grants image ingest. A group
#: rather than `is_staff`, which would additionally open /admin/, and rather
#: than a bespoke token model, which would bypass django-axes entirely.
INGEST_GROUP = "ingest"


class IngestAuth(HttpBasicAuth):
    """HTTP Basic against an ordinary Django account in the ingest group.

    Going through ``django.contrib.auth.authenticate`` is the point: it puts
    ``AxesStandaloneBackend`` in front of the password check, so a wrong
    password here counts towards the same (address, username) lockout as a
    wrong password on the login form. A bearer token would have had no
    throttling at all.

    The account is deliberately neither staff nor superuser, so what a leaked
    push password buys is image ingest and the reviewing UI — not /admin/, and
    not the ability to rewrite or delete anyone's reviews.
    """

    def authenticate(
        self, request: http.HttpRequest, username: str, password: str
    ) -> User | None:
        if not settings.INGEST_ENABLED:
            return None
        user = authenticate(request, username=username, password=password)
        if not isinstance(user, User):
            return None
        if not user.groups.filter(name=INGEST_GROUP).exists():
            return None
        return user


class ORJSONParser(parser.Parser):
    def parse_body(self, request):
        return orjson.loads(request.body)


class ORJSONRenderer(renderers.BaseRenderer):
    media_type = "application/json"

    def render(self, request, data, *, response_status):
        return orjson.dumps(data)


# API instance
api = ninja.NinjaAPI(
    title="dirt ingest",
    version="2.0.0",
    auth=IngestAuth(),
    renderer=ORJSONRenderer(),
    parser=ORJSONParser(),
    # No browsable docs in production; the schema is enough to read the
    # contract from (docs-gen renders it into the documentation site).
    docs_url=None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)


# Exception handlers: every error leaves the API as {"message": ..., "extra": {...}}
@api.exception_handler(exceptions.NotFound)
def not_found(request: http.HttpRequest, exc: exceptions.NotFound):
    return api.create_response(
        request, {"message": exc.message, "extra": exc.extra}, status=404
    )


@api.exception_handler(exceptions.PushRejected)
def push_rejected(request: http.HttpRequest, exc: exceptions.PushRejected):
    return api.create_response(
        request, {"message": exc.message, "extra": exc.extra}, status=409
    )


@api.exception_handler(exceptions.PushTooLarge)
def push_too_large(request: http.HttpRequest, exc: exceptions.PushTooLarge):
    return api.create_response(
        request, {"message": exc.message, "extra": exc.extra}, status=413
    )


@api.exception_handler(transfer.RejectedImage)
def rejected_image(request: http.HttpRequest, exc: transfer.RejectedImage):
    return api.create_response(request, {"message": str(exc), "extra": {}}, status=415)


@api.exception_handler(plan.PlanError)
def plan_error(request: http.HttpRequest, exc: plan.PlanError):
    return api.create_response(request, {"message": str(exc), "extra": {}}, status=422)


@api.exception_handler(pydantic.ValidationError)
def payload_error(request: http.HttpRequest, exc: pydantic.ValidationError):
    # No context: a validator's ctx can carry the raising exception object,
    # which is not JSON. Location + message are what a client can act on.
    errors = exc.errors(include_url=False, include_context=False, include_input=False)
    return api.create_response(
        request,
        {"message": "Invalid payload", "extra": {"errors": errors}},
        status=422,
    )


@api.exception_handler(exceptions.ApplicationError)
def application_error(request: http.HttpRequest, exc: exceptions.ApplicationError):
    return api.create_response(
        request, {"message": exc.message, "extra": exc.extra}, status=400
    )


@api.exception_handler(django_exceptions.ValidationError)
def validation_error(request: http.HttpRequest, exc: django_exceptions.ValidationError):
    fields = exc.message_dict if hasattr(exc, "error_dict") else exc.messages
    return api.create_response(
        request,
        {"message": "Validation error", "extra": {"fields": fields}},
        status=400,
    )


# Schemas
class PlanSchema(Schema):
    name: str
    content_hash: str


class PlanInSchema(Schema):
    name: str
    toml: str


class UnitSummarySchema(Schema):
    file1: str
    unit_digest: str
    meta_digest: str


class ImageMetaSchema(Schema):
    display: models.DisplayMode
    slice: int | None = None
    digest: str = ninja.Field(pattern=rf"^[0-9a-f]{{{transfer.DIGEST_LENGTH}}}$")


class UnitPayload(Schema):
    """One measured file with its rendered views — the unit a push carries."""

    step: str
    file1: str
    file2: str | None = None
    entities: dict | None = None
    metrics: dict[str, float | None] = ninja.Field(default_factory=dict)
    # ReviewPlan.content_hash provenance; the plan must be pushed first.
    plan_hash: str | None = None
    images: list[ImageMetaSchema] = ninja.Field(min_length=1)

    @pydantic.field_validator("step")
    @classmethod
    def step_is_a_cli_name(cls, value: str) -> str:
        models.Step.from_cli_name(value)  # raises ValueError if unknown
        return value


class UnitResultSchema(Schema):
    step: str
    file1: str
    created: bool
    n_images: int
    unit_digest: str


class PrioritizeResultSchema(Schema):
    images_updated: int


class RatingOutSchema(ninja.ModelSchema):
    session_user: str | None = ninja.Field(None, alias="session.user")
    step: int = ninja.Field(..., alias="image.step")
    file1: str = ninja.Field(..., alias="image.file1")
    display: int = ninja.Field(..., alias="image.display")
    slice: int | None = ninja.Field(None, alias="image.slice")

    class Meta:
        model = models.Rating
        fields = ("id", "rating", "source_data_issue", "comments", "created_at")


class AnnotationCellSchema(Schema):
    col: int
    row: int
    rating: int


class AnnotationOutSchema(ninja.ModelSchema):
    session_user: str | None = ninja.Field(None, alias="session.user")
    step: int = ninja.Field(..., alias="image.step")
    file1: str = ninja.Field(..., alias="image.file1")
    display: int = ninja.Field(..., alias="image.display")
    slice: int | None = ninja.Field(None, alias="image.slice")
    cells: list[AnnotationCellSchema]

    class Meta:
        model = models.Annotation
        fields = (
            "id",
            "grid_cols",
            "grid_rows",
            "source_data_issue",
            "comments",
            "created_at",
        )

    @staticmethod
    def resolve_cells(obj: models.Annotation) -> list[dict]:
        return [
            {"col": cell.col, "row": cell.row, "rating": cell.rating}
            for cell in obj.cells.all()
        ]


# Endpoints
@api.get("/plan", response=PlanSchema | None)
def active_plan(request: http.HttpRequest):
    """The active review plan's identity, so a client can skip re-pushing it."""
    return plan.active_record()


@api.post("/plan", response=PlanSchema)
def apply_plan(request: http.HttpRequest, payload: PlanInSchema):
    """Validate, persist and activate a review plan (idempotent by content)."""
    plan.parse(payload.toml)
    return services.plan_apply(name=payload.name, text=payload.toml)


@api.get("/units", response=list[UnitSummarySchema])
def unit_index(request: http.HttpRequest, step: str):
    """Per file, a digest of the step's stored images — the push skip set."""
    try:
        step_enum = models.Step.from_cli_name(step)
    except ValueError as e:
        raise exceptions.NotFound(str(e)) from e
    return selectors.unit_digests(step=int(step_enum))


@api.post("/units", response=UnitResultSchema)
def push_unit(
    request: http.HttpRequest,
    unit: File[UploadedFile],
    images: File[UploadedFile],
):
    """Take one unit: its metadata as JSON, its images as a tar.

    Order is images first, rows last — until the rows exist nothing names
    those files, so a push that dies partway leaves unreachable orphans (for
    ``manage prune_media``) rather than a unit whose page is a broken image.
    """
    if images.size and images.size > settings.INGEST_MAX_TAR_BYTES:
        raise exceptions.PushTooLarge(
            f"the images are over {settings.INGEST_MAX_TAR_BYTES} bytes"
        )
    payload = UnitPayload.model_validate_json(unit.read())
    if len(payload.images) > settings.INGEST_MAX_IMAGES:
        raise exceptions.PushTooLarge(
            f"more than {settings.INGEST_MAX_IMAGES} images in one unit"
        )
    step = models.Step.from_cli_name(payload.step)
    expected = {(int(m.display), m.slice): m.digest for m in payload.images}
    if len(expected) != len(payload.images):
        raise exceptions.PushRejected("two declared images share a (display, slice)")

    review_plan_id = None
    if payload.plan_hash is not None:
        review_plan_id = (
            models.ReviewPlan.objects.filter(content_hash=payload.plan_hash)
            .values_list("id", flat=True)
            .first()
        )
        if review_plan_id is None:
            raise exceptions.PushRejected(
                "this server does not hold the review plan the unit was rendered "
                "under — push the plan first",
                extra={"plan_hash": payload.plan_hash},
            )

    created = not models.Image.objects.filter(
        step=int(step), file1=payload.file1
    ).exists()

    images.seek(0)
    if images.file is None:  # unreachable for an uploaded part; narrows for ty
        raise transfer.RejectedImage("no images were uploaded")
    stored: set[tuple[int, int | None]] = set()
    for view, data in transfer.read_unit_tar(
        images.file,
        expected=expected,
        max_member_bytes=settings.INGEST_MAX_IMAGE_BYTES,
    ):
        display, cut = view
        storage.save(
            storage.image_name(
                step=int(step),
                file1=payload.file1,
                display=display,
                slice=cut,
                digest=expected[view],
            ),
            data,
        )
        stored.add(view)
    if stored != set(expected):
        raise transfer.RejectedImage("the upload is missing declared images")

    replaced = services.unit_upsert_rows(
        step=int(step),
        file1=payload.file1,
        file2=payload.file2,
        entities=payload.entities,
        values=payload.metrics,
        review_plan_id=review_plan_id,
        images=[
            {"display": display, "slice": cut, "digest": digest}
            for (display, cut), digest in expected.items()
        ],
    )
    for name in replaced:
        storage.delete(name)

    return {
        "step": payload.step,
        "file1": payload.file1,
        "created": created,
        "n_images": len(stored),
        "unit_digest": storage.unit_digest(
            (display, cut, digest) for (display, cut), digest in expected.items()
        ),
    }


@api.post("/prioritize", response=PrioritizeResultSchema)
def run_prioritize(request: http.HttpRequest):
    """Recompute Image.priority from the stored metrics (run once after a push)."""
    return {"images_updated": prioritizing.run()}


@api.get("/ratings", response=list[RatingOutSchema])
def list_ratings(request: http.HttpRequest):
    """Every rating, with the identity of the image it reviewed."""
    return selectors.rating_list()


@api.get("/annotations", response=list[AnnotationOutSchema])
def list_annotations(request: http.HttpRequest):
    """Every annotation with its marked cells, for analysis exports."""
    return selectors.annotation_list()
