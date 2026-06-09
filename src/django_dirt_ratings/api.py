import base64

import ninja
import orjson
from django import http, shortcuts
from ninja import Schema, parser, renderers

from django_dirt_ratings import models


class ORJSONParser(parser.Parser):
    def parse_body(self, request):
        return orjson.loads(request.body)


class ORJSONRenderer(renderers.BaseRenderer):
    media_type = "application/json"

    def render(self, request, data, *, response_status):
        return orjson.dumps(data)


# API instance
api = ninja.NinjaAPI(
    title="QC App Ratings API",
    version="1.0.0",
    renderer=ORJSONRenderer(),
    parser=ORJSONParser(),
)


class ImageSchema(ninja.ModelSchema):
    img: str

    class Meta:
        model = models.Image
        fields = ["id", "slice", "file1", "file2", "display", "step", "created", "img"]
        fields_optional = ["created", "slice", "file2", "display", "step"]


class ImageResponseSchema(ninja.ModelSchema):
    img: str

    class Meta:
        model = models.Image
        fields = ["id", "created"]


class DeleteResponseSchema(Schema):
    success: bool
    message: str


class StepFilter(ninja.FilterSchema):
    name: models.Step | None = None


class RatingSchema(ninja.ModelSchema):
    session_user: str | None = ninja.Field(None, alias="session.user")
    image_id: int = ninja.Field(..., alias="image.id")

    class Meta:
        model = models.Rating
        fields = ["id", "rating", "source_data_issue", "created"]


# Endpoints
@api.post("/image/", response=ImageResponseSchema)
def create_image(request: http.HttpRequest, payload: ImageSchema):
    """Create a single image"""
    image = models.Image.objects.create(**payload.dict())
    return {"id": image.pk, "created": image.created}


@api.delete("/image/{int:image_id}/", response=DeleteResponseSchema)
def delete_image(request: http.HttpRequest, image_id: int):
    """Delete a single image by ID"""
    image = shortcuts.get_object_or_404(models.Image, id=image_id)
    image.delete()
    return {"success": True, "message": f"Image {image_id} deleted successfully"}


@api.get("/images/", response=list[ImageSchema])
def list_images(
    request: http.HttpRequest,
    filters: StepFilter = ninja.Query(...),  # type: ignore
    limit: int = 100,
):
    """List images with optional filtering by step"""
    images = filters.filter(models.Image.objects.all())[:limit]

    return [
        {
            "id": image.pk,
            "slice": image.slice,
            "file1": image.file1,
            "file2": image.file2,
            "display": image.display,
            "step": image.step,
            "created": image.created,
            "img": base64.b64encode(image.img).decode(),
        }
        for image in images
    ]


@api.get("/image/{int:image_id}/", response=ImageSchema)
def get_image(request: http.HttpRequest, image_id: int):
    """Get a single image by ID"""
    image = shortcuts.get_object_or_404(models.Image, id=image_id)
    return {
        "id": image.pk,
        "slice": image.slice,
        "file1": image.file1,
        "file2": image.file2,
        "display": image.display,
        "step": image.step,
        "created": image.created,
        "img": base64.b64encode(image.img).decode(),
    }


@api.get("/ratings/", response=list[RatingSchema])
def list_ratings(request: http.HttpRequest):
    """List all ratings"""
    return (
        models.Rating.objects
        .all()
        .select_related("session", "image")
        .values(
            "id",
            "session_id",
            "session__user",
            "image_id",
            "rating",
            "source_data_issue",
            "created",
        )
    )
