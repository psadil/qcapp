import abc
import json

from django import http, shortcuts, urls, views
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import static
from django.views.generic import edit

from django_dirt_ratings import (
    exceptions,
    forms,
    models,
    ordering,
    reference,
    selectors,
    services,
)

# An image URL contains the image's content digest, so the bytes behind one
# never change — a re-render mints new URLs. That makes them safely immutable,
# which matters: every step re-fetches a fresh partial per submission, and the
# reference panel repeats across images.
IMAGE_CACHE_CONTROL = "private, max-age=31536000, immutable"


class HtmxLoginRequiredMixin(LoginRequiredMixin):
    """Login gate that a partial request can survive.

    A plain redirect to the login page would be *followed* by htmx and swapped
    into the target element — a login form nested inside #main, with the
    submission lost. Answering an htmx request with HX-Redirect instead makes
    the browser perform a full-page navigation to the login page.
    """

    # supplied by the View the mixin is mixed into; annotated for the stubs
    request: http.HttpRequest

    def handle_no_permission(self):
        response = super().handle_no_permission()
        if self.request.headers.get("HX-Request") != "true":
            return response
        return http.HttpResponse(headers={"HX-Redirect": response.headers["Location"]})


@login_required
def media_file(request: http.HttpRequest, path: str) -> http.HttpResponseBase:
    """Serve one rendered image out of ``MEDIA_ROOT``. Login-required because
    these are subject-derived.

    HttpResponseBase, not HttpResponse: ``serve`` answers with a FileResponse
    for a hit and an HttpResponseNotModified for a conditional request, and
    only their common base covers both.
    """
    response = static.serve(request, path, document_root=settings.MEDIA_ROOT)
    response.headers["Cache-Control"] = IMAGE_CACHE_CONTROL
    return response


MASK_VIEW = "mask"
SPATIAL_NORMALIZATION_VIEW = "spatial_normalization"
SURFACE_LOCALIZATION_VIEW = "surface_localization"
FMAP_COREGISTRATION_VIEW = "fmap_coregistration"
T1W_COREGISTRATION_VIEW = "t1w_coregistration"
DTIFIT_VIEW = "dtifit"
RATE_PARTIAL = "rate_partial"
CLICK_PARTIAL = "click_partial"

# Steps with a rater walkthrough on the docs site (see DIRT_DOCS_URL).
TUTORIAL_PATHS: dict[models.Step, str] = {
    models.Step.SPATIAL_NORMALIZATION: "tutorials/rate-spatial-normalization.html",
}


def _tutorial_url(step: models.Step) -> str | None:
    path = TUTORIAL_PATHS.get(step)
    return f"{settings.DIRT_DOCS_URL}/{path}" if path else None


def _reference(image: models.Image) -> dict[str, str]:
    """Context for the landmark reference panel, or nothing at all.

    The space is looked up rather than derived from the filename: it is already
    recorded, per file, on :class:`models.MeasuredFile`. An image with no
    reference contributes no context keys, and the template omits the panel.
    """
    if models.Step(image.step) not in reference.STEPS:
        return {}
    entities = (
        selectors.measured_file_entities(step=image.step, file1=image.file1) or {}
    )
    space = entities.get("space")
    url = reference.reference_url(
        space=space,
        cohort=entities.get("cohort"),
        display=image.display,
        slice=image.slice,
    )
    if url is None or space is None:
        return {}
    return {"reference_url": url, "reference_space": str(space)}


def _upcoming_image_url(
    *,
    step: models.Step,
    strategy: ordering.OrderingStrategy,
    after: models.Image,
) -> str | None:
    """URL of the image the *next* request will serve, or ``None`` at the end of a step.

    Running now the exact seek that request will run predicts its answer rather
    than guessing it: the ordering is deterministic, and reviewing an image only
    ever sinks that one image — which this call excludes. The template offers the
    URL to the browser so the bytes are already cached when the swap lands.

    Strictly a hint, never a reservation: nothing here touches session state, and
    the image actually served is still chosen fresh by the request serving it. A
    second reviewer rating that image first costs one wasted download and a
    transition no slower than it was before the prefetch existed.
    """
    try:
        image = selectors.next_image(step=step, strategy=strategy, exclude=after.pk)
    except exceptions.ApplicationError:
        return None
    return image.img.url


def _next_image_response(
    request: http.HttpRequest,
    *,
    template_name: str,
    complete_template_name: str,
) -> http.HttpResponse:
    """Serve the next image for this browser session's step, and record it.

    Shared by the partial views (htmx's opening ``hx-get``) and by the submit
    POSTs, which answer with the next image directly. Redirecting there instead
    cost every submission a second round trip — cookie, auth query, template
    load — for a response the POST already had everything to render.
    """
    step = request.session.get("step")
    if step is None:
        raise http.Http404("no active rating session")

    # Serve the next image synchronously under the session's pinned strategy
    # (cached in the cookie at session start). Every strategy is a single index
    # seek; excluding the image just shown gives the next one in order.
    strategy = ordering.OrderingStrategy.build(
        request.session.get("strategy", models.ReviewStrategy.BREADTH_FIRST)
    )
    try:
        image = selectors.next_image(
            step=models.Step(step),
            strategy=strategy,
            exclude=request.session.get("image_id"),
        )
    except exceptions.ApplicationError:
        # No image left to serve — an empty step, or its only image was just shown.
        return shortcuts.render(request, complete_template_name)

    request.session["image_id"] = image.pk
    return shortcuts.render(
        request,
        template_name,
        {
            "image_url": image.img.url,
            "next_image_url": _upcoming_image_url(
                step=models.Step(step), strategy=strategy, after=image
            ),
            "grid_cols": models.Step(image.step).grid_cols,
            "tutorial_url": _tutorial_url(models.Step(image.step)),
            **_reference(image),
        },
    )


class RatePartial(HtmxLoginRequiredMixin, views.View):
    template_name = f"{RATE_PARTIAL}.html"
    complete_template_name = "review_complete.html"

    def get(self, request: http.HttpRequest) -> http.HttpResponse:
        return _next_image_response(
            request,
            template_name=self.template_name,
            complete_template_name=self.complete_template_name,
        )


class ClickPartial(RatePartial):
    template_name = f"{CLICK_PARTIAL}.html"
    complete_template_name = "click_complete.html"


class RateView(HtmxLoginRequiredMixin, abc.ABC, edit.CreateView):
    template_name = "rate.html"
    form_class = forms.RatingForm
    #: The partial a successful submission answers with. Naming the view class
    #: keeps the (template, complete-template) pair defined in one place.
    partial: type[RatePartial] = RatePartial

    @property
    @abc.abstractmethod
    def step(self) -> models.Step:
        raise NotImplementedError

    def next_image_response(self, request: http.HttpRequest) -> http.HttpResponse:
        """Answer a submission with the next image, rather than a redirect to it."""
        return _next_image_response(
            request,
            template_name=self.partial.template_name,
            complete_template_name=self.partial.complete_template_name,
        )

    def _get_image_and_session(
        self, request: http.HttpRequest
    ) -> tuple[models.Image, models.Session]:
        """Resolve the image/session the browser session points at, or 404."""
        image_id = request.session.get("image_id")
        session_id = request.session.get("session_id")
        if image_id is None or session_id is None:
            raise http.Http404("No active rating session")
        try:
            image = selectors.image_get(image_id=image_id)
            session = selectors.session_get(session_id=session_id)
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
        return self.next_image_response(request)


class ClickView(RateView):
    template_name = "click.html"
    form_class = forms.ClickForm
    partial = ClickPartial

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
        return self.next_image_response(request)


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


class RateT1wCoregistration(RateView):
    @property
    def step(self) -> models.Step:
        return models.Step.T1W_COREGISTRATION


class RateDTIFIT(RateView):
    @property
    def step(self) -> models.Step:
        return models.Step.DTIFIT


class LayoutView(LoginRequiredMixin, edit.FormView):
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
            case models.Step.T1W_COREGISTRATION:
                return urls.reverse(f"{T1W_COREGISTRATION_VIEW}")
            case models.Step.DTIFIT:
                return urls.reverse(f"{DTIFIT_VIEW}")
            case _:
                raise http.Http404("Unknown step")

    def form_valid(self, form: forms.IndexForm):
        session = services.session_create(
            step=form.cleaned_data["step"],
            user=self.request.user.get_username(),
        )
        self.request.session["session_id"] = session.pk
        self.request.session["step"] = session.step
        # Pin the serving strategy in the cookie so the partial loop needs no DB
        # read for it (mirrors how `step` is cached).
        self.request.session["strategy"] = session.strategy
        return http.HttpResponseRedirect(self.get_success_url())
