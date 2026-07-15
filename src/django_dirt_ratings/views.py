import abc
import json
import logging

from celery import result
from celery.exceptions import TimeoutError
from django import http, shortcuts, urls, views
from django.views.generic import edit

from django_dirt_ratings import (
    exceptions,
    formatters,
    forms,
    models,
    selectors,
    services,
    tasks,
)

MASK_VIEW = "mask"
SPATIAL_NORMALIZATION_VIEW = "spatial_normalization"
SURFACE_LOCALIZATION_VIEW = "surface_localization"
FMAP_COREGISTRATION_VIEW = "fmap_coregistration"
DTIFIT_VIEW = "dtifit"
RATE_PARTIAL = "rate_partial"
CLICK_PARTIAL = "click_partial"


IMG_TASK = "img_task"
TASK_TIMEOUT_SEC = 30


class RatePartial(views.View):
    template_name = f"{RATE_PARTIAL}.html"

    def get(self, request: http.HttpRequest) -> http.HttpResponse:
        img_task = request.session.get(IMG_TASK)
        if img_task is None:
            raise http.Http404("no img_task found")

        # This is a sync view on purpose: AsyncResult.get() blocks until the
        # prefetched result is ready. Under ASGI it runs in a thread pool, so
        # the wait (usually instant, since the task ran while the reviewer
        # annotated the previous image) never blocks the event loop.
        try:
            # ApplicationError is how the task reports "no image left to
            # rate"; it is re-raised locally by AsyncResult.get.
            payload = result.AsyncResult(img_task).get(timeout=TASK_TIMEOUT_SEC)
            image = selectors.image_get(image_id=payload["id"])
        except (TimeoutError, exceptions.ApplicationError, exceptions.NotFound):
            return http.HttpResponse(
                "There has been an issue. Please return to the homepage."
            )

        # Prefetch the next image while the reviewer works on this one.
        next_task = tasks.run_db_query_async.delay(step=image.step, last_pk=image.pk)
        request.session[IMG_TASK] = next_task.id
        request.session["image_id"] = image.pk
        return shortcuts.render(
            request,
            self.template_name,
            {
                "img_type": models.Step(image.step).image_type,
                "image": formatters.image_to_base64(image.img),
                "grid_cols": models.Step(image.step).grid_cols,
            },
        )


class ClickPartial(RatePartial):
    template_name = f"{CLICK_PARTIAL}.html"


class RateView(abc.ABC, edit.CreateView):
    template_name = "rate.html"
    form_class = forms.RatingForm

    @property
    @abc.abstractmethod
    def step(self) -> models.Step:
        raise NotImplementedError

    def get_success_url(self) -> str:
        return urls.reverse(RATE_PARTIAL)

    def get(self, request: http.HttpRequest, *args, **kwargs):
        logging.info("getting first img")
        img_task = tasks.run_db_query_async.delay(step=self.step)

        logging.info(f"updating session with {img_task=}")
        request.session[IMG_TASK] = img_task.id

        return super().get(request, *args, **kwargs)

    def _get_image_and_session(
        self, request: http.HttpRequest
    ) -> tuple[models.Image, models.Session]:
        """Resolve the image/session the browser session points at, or 404."""
        try:
            image = selectors.image_get(image_id=request.session.get("image_id"))
            session = selectors.session_get(
                session_id=request.session.get("session_id")
            )
        except exceptions.NotFound:
            raise http.Http404("No active rating session")
        return image, session

    def post(self, request: http.HttpRequest, *args, **kwargs) -> http.HttpResponse:
        form = self.get_form()
        if not form.is_valid():
            self.object = None
            return self.form_invalid(form)

        image, session = self._get_image_and_session(request)
        services.rating_create(
            image=image,
            session=session,
            rating=form.cleaned_data["rating"],
            source_data_issue=form.cleaned_data["source_data_issue"],
            comments=form.cleaned_data["comments"],
        )
        return http.HttpResponseRedirect(self.get_success_url())


class ClickView(RateView):
    template_name = "click.html"
    form_class = forms.ClickForm

    def get_success_url(self) -> str:
        return urls.reverse(CLICK_PARTIAL)

    def post(self, request: http.HttpRequest, *args, **kwargs) -> http.HttpResponse:
        form = self.get_form()
        if not form.is_valid():
            self.object = None
            return self.form_invalid(form)

        image, session = self._get_image_and_session(request)
        cells_raw = request.POST.get("cells")
        cells: list[list[int]] = json.loads(cells_raw) if cells_raw else []
        services.annotation_create(
            image=image,
            session=session,
            grid_cols=int(request.POST["grid_cols"]),
            grid_rows=int(request.POST["grid_rows"]),
            cells=[(col, row, rating) for col, row, rating in cells],
            source_data_issue=form.cleaned_data["source_data_issue"],
            comments=form.cleaned_data["comments"],
        )
        return http.HttpResponseRedirect(self.get_success_url())


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
        session = services.session_create(
            step=form.cleaned_data["step"],
            user=self.request.headers.get("X-Tapis-Username"),
        )
        self.request.session["session_id"] = session.pk
        self.request.session["step"] = session.step
        return http.HttpResponseRedirect(self.get_success_url())
