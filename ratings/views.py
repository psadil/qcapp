import abc
import base64
import logging
import zlib

from django import http, shortcuts, urls, views
from django.db import models as dm
from django.views.generic import edit

from . import forms, models

MASK_VIEW = "mask"
SPATIAL_NORMALIZATION_VIEW = "spatial_normalization"
SURFACE_LOCALIZATION_VIEW = "surface_localization"
FMAP_COREGISTRATION_VIEW = "fmap_coregistration"
DTIFIT_VIEW = "dtifit"


# note: not a FormView because the (dynamic) image cannot be placed in form
class RateView(abc.ABC, views.View):
    template_name = "rate_image.html"
    form_class = forms.RatingForm
    main_template = "main.html"
    related = "rating"
    key = "source_data_issue"
    img_type = "png"

    @property
    @abc.abstractmethod
    def step(self) -> models.Step:
        raise NotImplementedError

    async def _get(self, request: http.HttpRequest, template: str) -> http.HttpResponse:
        logging.info("setting next")
        img = await _get_mask_with_fewest_ratings(
            self.step, related=self.related, key=self.key
        )
        await request.session.aset("image_id", img.pk)  # type: ignore
        logging.info("rendering")
        logging.info(img.pk)
        if img.compressed:
            data = zlib.decompress(img.img)
        else:
            data = img.img
        return shortcuts.render(
            request,
            template,
            {
                "form": self.form_class(),
                "image": f"data:image/{self.img_type};base64,{base64.b64encode(data).decode()}",
            },
        )

    async def get_main(self, request: http.HttpRequest) -> http.HttpResponse:
        return await self._get(request=request, template=self.main_template)

    async def get(self, request: http.HttpRequest) -> http.HttpResponse:
        return await self._get(request=request, template=self.template_name)

    async def post(self, request: http.HttpRequest) -> http.HttpResponse:
        form = self.form_class(request.POST)
        if form.is_valid():
            logging.info("saving rating")

            # rating = sync.sync_to_async(form.save)()

            await self.form_class.Meta.model.from_request_form(
                request=request, form=form
            )

            return await self.get_main(request)

        raise http.Http404("Submitted invalid rating")


class ClickView(RateView):
    template_name = "click.html"
    main_template = "click_canvas.html"
    form_class = forms.ClickForm
    related = "clickedcoordinate"


class RateMask(ClickView):
    @property
    def step(self) -> models.Step:
        return models.Step.MASK


class RateSpatialNormalization(ClickView):
    @property
    def step(self) -> models.Step:
        return models.Step.SPATIAL_NORMALIZATION


class RateSurfaceLocalization(ClickView):
    @property
    def step(self) -> models.Step:
        return models.Step.SURFACE_LOCALIZATION


class RateFMapCoregistration(RateView):
    @property
    def step(self) -> models.Step:
        return models.Step.FMAP_COREGISTRATION


class RateDTIFIT(RateView):
    img_type = "gif"

    @property
    def step(self) -> models.Step:
        return models.Step.DTIFIT


class LayoutView(edit.FormView):
    template_name = "index.html"
    form_class = forms.IndexForm

    def get_success_url(self):
        match self.request.session.get("step"):
            case models.Step.MASK:
                return urls.reverse(f"{MASK_VIEW}")
            case models.Step.SPATIAL_NORMALIZATION:
                return urls.reverse(f"{SPATIAL_NORMALIZATION_VIEW}")
            case models.Step.SURFACE_LOCALIZATION:
                return urls.reverse(f"{SURFACE_LOCALIZATION_VIEW}")
            case models.Step.FMAP_COREGISTRATION:
                return urls.reverse(f"{FMAP_COREGISTRATION_VIEW}")
            case models.Step.DTIFIT:
                return urls.reverse(f"{DTIFIT_VIEW}")
            case _:
                raise http.Http404("Unknown step")

    def form_valid(self, form: forms.IndexForm):
        form.instance.user = self.request.COOKIES.get("X-Tapis-Username")
        session = form.save()
        self.request.session["session_id"] = session.pk
        self.request.session["step"] = session.step
        return super().form_valid(form)


# @require_POST
# def save_points(request):
#     image_id = int(request.POST.get("image_id"))
#     points_json = request.POST.get("points")
#     points = json.loads(points_json)

#     # Get image
#     image = Image.objects.get(id=image_id)

#     # Save all points to database
#     new_points = []
#     for point in points:
#         click_point = ClickPoint.objects.create(
#             image=image, x_coordinate=point["x"], y_coordinate=point["y"]
#         )
#         new_points.append(click_point)

#     # Return confirmation
#     return http.HttpResponse(f"<div>{len(new_points)} points saved successfully!</div>")


async def _get_mask_with_fewest_ratings(
    step: models.Step, related: str, key: str
) -> models.Image:
    masks_in_layout = await (
        models.Image.objects.filter(step=step.value)
        .select_related(related)
        .values("id")
        .annotate(n_ratings=dm.Count(f"{related}__{key}"))
        .order_by("n_ratings")
        .afirst()
    )
    if masks_in_layout is None:
        raise http.Http404("No masks in layout")

    return await models.Image.objects.aget(pk=masks_in_layout.get("id"))
