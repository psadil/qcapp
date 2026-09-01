import base64

import ninja
import orjson
from django import http
from django.core import exceptions as django_exceptions
from ninja import Schema, parser, renderers

from django_dirt_ratings import exceptions, models, selectors, services


class ORJSONParser(parser.Parser):
    def parse_body(self, request):
        return orjson.loads(request.body)


class ORJSONRenderer(renderers.BaseRenderer):
    media_type = "application/json"

    def render(self, request, data, *, response_status):
        return orjson.dumps(data)


#: Membership in this stock auth Group is what grants image ingest. A group
#: rather than `is_staff`, which would additionally open /admin/, and rather
#: than a bespoke token model, which would bypass django-axes entirely.
INGEST_GROUP = "ingest"

# API instance
api = ninja.NinjaAPI(
    title="QC App Ratings API",
    version="1.0.0",
    renderer=ORJSONRenderer(),
    parser=ORJSONParser(),
)


# Exception handlers: every error leaves the API as {"message": ..., "extra": {...}}
@api.exception_handler(exceptions.NotFound)
def not_found(request: http.HttpRequest, exc: exceptions.NotFound):
    return api.create_response(
        request, {"message": exc.message, "extra": exc.extra}, status=404
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
class ImageInSchema(Schema):
    img: str  # base64-encoded image bytes
    file1: str
    display: models.DisplayMode
    step: models.Step
    slice: int | None = None
    file2: str | None = None


class ImageOutSchema(ninja.ModelSchema):
    url: str

    class Meta:
        model = models.Image
        fields = (
            "id",
            "slice",
            "file1",
            "file2",
            "display",
            "step",
            "digest",
            "created_at",
        )

    @staticmethod
    def resolve_url(obj: models.Image) -> str:
        return obj.img.url


class ImageCreatedSchema(ninja.ModelSchema):
    class Meta:
        model = models.Image
        fields = ("id", "created_at")


class DeleteResponseSchema(Schema):
    success: bool
    message: str


class RatingOutSchema(ninja.ModelSchema):
    session_user: str | None = ninja.Field(None, alias="session.user")
    image_id: int = ninja.Field(..., alias="image.id")

    class Meta:
        model = models.Rating
        fields = ("id", "rating", "source_data_issue", "created_at")


# Endpoints
@api.post("/image/", response=ImageCreatedSchema)
def create_image(request: http.HttpRequest, payload: ImageInSchema):
    """Create a single image"""
    return services.image_create(
        img=base64.b64decode(payload.img),
        file1=payload.file1,
        display=payload.display,
        step=payload.step,
        slice=payload.slice,
        file2=payload.file2,
    )


@api.delete("/image/{int:image_id}/", response=DeleteResponseSchema)
def delete_image(request: http.HttpRequest, image_id: int):
    """Delete a single image by ID"""
    image = selectors.image_get(image_id=image_id)
    services.image_delete(image=image)
    return {"success": True, "message": f"Image {image_id} deleted successfully"}


@api.get("/images/", response=list[ImageOutSchema])
def list_images(
    request: http.HttpRequest,
    step: models.Step | None = None,
    limit: int = 100,
):
    """List images with optional filtering by step"""
    return selectors.image_list(step=step, limit=limit)


@api.get("/image/{int:image_id}/", response=ImageOutSchema)
def get_image(request: http.HttpRequest, image_id: int):
    """Get a single image by ID"""
    return selectors.image_get(image_id=image_id)


@api.get("/ratings/", response=list[RatingOutSchema])
def list_ratings(request: http.HttpRequest):
    """List all ratings"""
    return selectors.rating_list()
