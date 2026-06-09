import abc
import logging

from celery.exceptions import TimeoutError
from django import http, shortcuts, urls, views
from django.views.generic import edit

from django_dirt_ratings import forms, models, selectors, services, tasks

MASK_VIEW = "mask"
SPATIAL_NORMALIZATION_VIEW = "spatial_normalization"
SURFACE_LOCALIZATION_VIEW = "surface_localization"
FMAP_COREGISTRATION_VIEW = "fmap_coregistration"
DTIFIT_VIEW = "dtifit"
RATE_PARTIAL = "rate_partial"
CLICK_PARTIAL = "click_partial"


IMG_TASK = "img_task"


class RatePartial(views.View):
    template_name = f"{RATE_PARTIAL}.html"

    async def get(self, request: http.HttpRequest) -> http.HttpResponse:
        try:
            img = await selectors.get_img_id(request)
        except (TimeoutError, ValueError):
            return http.HttpResponse(
                "There has been an issue. Please return to the homepage."
            )

        logging.info("starting img_next task")
        img_task = tasks.run_db_query_async.delay(step=img.step, last_pk=img.id)
        await request.session.aset(IMG_TASK, img_task.id)
        await request.session.aset("image_id", img.id)
        logging.info(f"rendering {img.id}")
        return shortcuts.render(
            request,
            self.template_name,
            {"img_type": img.img_type, "image": img.img_decoded},
        )


class ClickPartial(RatePartial):
    template_name = f"{CLICK_PARTIAL}.html"


class RateView(abc.ABC, edit.CreateView):
    template_name = "rate.html"
    form_class = forms.RatingForm
    success_url: str = f"/{RATE_PARTIAL}/"

    @property
    @abc.abstractmethod
    def step(self) -> models.Step:
        raise NotImplementedError

    def get(self, request: http.HttpRequest, *args, **kwargs):
        logging.info("getting first img")
        img_task = tasks.run_db_query_async.delay(step=self.step)

        logging.info(f"updating session with {img_task=}")
        request.session[IMG_TASK] = img_task.id

        return super().get(request, *args, **kwargs)

    def post(self, request: http.HttpRequest, *args, **kwargs) -> http.HttpResponse:
        form = self.get_form()
        if form.is_valid():
            instance = form.save(commit=False)
            services.rating_create(instance=instance, request=request)
            return http.HttpResponseRedirect(self.success_url)

        raise http.Http404("Submitted invalid rating")


class ClickView(RateView):
    template_name = "click.html"
    form_class = forms.ClickForm
    success_url = f"/{CLICK_PARTIAL}/"

    def post(self, request: http.HttpRequest, *args, **kwargs) -> http.HttpResponse:
        form = self.get_form()
        if form.is_valid():
            instance = form.save(commit=False)
            services.clicked_coordinate_create(instance=instance, request=request)
            return http.HttpResponseRedirect(self.success_url)

        raise http.Http404("Submitted invalid click")


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
        form.instance.user = self.request.headers.get("X-Tapis-Username")
        session = form.save()
        self.request.session["session_id"] = session.pk
        self.request.session["step"] = session.step
        return super().form_valid(form)
