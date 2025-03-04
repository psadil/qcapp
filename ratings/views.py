import logging
import random
import typing

import polars as pl
from django import http, shortcuts, urls, views
from django.db import models as dm
from django.views.generic import edit

from . import forms, models

RATE_MASK_VIEW = "rate_mask"


# note: not a FormView because the (dynamic) image cannot be placed in form
class RateMask(views.View):
    form_class = forms.RatingForm
    template_name = "rate_image.html"

    def get(
        self,
        request: http.HttpRequest,
        *args,
        mask_id: int,
        display_id: int,
        img_id: int,
        **kwargs,
    ) -> http.HttpResponse:
        form = self.form_class()
        mask = shortcuts.get_object_or_404(models.Mask, pk=mask_id)
        return shortcuts.render(
            request,
            self.template_name,
            {
                "form": form,
                "image": mask.get_image(
                    img_id=img_id, display_mode=models.DisplayMode(display_id)
                ),
            },
        )

    def post(
        self, request: http.HttpRequest, *args, mask_id: int, img_id: int, **kwargs
    ) -> http.HttpResponse | http.HttpResponsePermanentRedirect | None:
        form = self.form_class(request.POST)
        if form.is_valid():
            rating = form.save()
            mask = shortcuts.get_object_or_404(models.Mask, pk=mask_id)
            models.MaskRating.objects.create(rating=rating, img_id=img_id, mask=mask)
            next_mask = self.get_next_mask(layout=mask.layout)
            return _redirect_to_mask_randomly(next_mask)
        raise http.Http404("Submitted invalid rating")

    def get_next_mask(self, layout: models.Layout) -> models.Mask:
        return _get_mask_with_fewest_ratings(layout=layout)


class LayoutView(edit.FormView):
    template_name = "index.html"
    form_class = forms.IndexForm
    form: forms.IndexForm | None = None

    def get_layout(self) -> models.Layout:
        if self.form is None:
            raise http.Http404("Trying to advance with invalid form")
        return models.Layout.objects.get(src=self.form.cleaned_data["src"])

    def get_success_url(self):
        layout = self.get_layout()
        mask = _get_create_masks_from_layout(layout)
        return urls.reverse(
            RATE_MASK_VIEW, kwargs=_redirect_to_mask_randomly_kwargs(mask)
        )

    def form_valid(self, form: forms.IndexForm):
        # we only want the layout to be in the database once
        self.form = form
        try:
            self.get_layout()
        except models.Layout.DoesNotExist:
            form.save()
        return super().form_valid(form)


def _get_mask_with_fewest_ratings(layout: models.Layout) -> models.Mask:
    masks_in_layout = (
        models.Mask.objects.filter(layout=layout)
        .select_related("maskrating")
        .values("id")
        .annotate(n_ratings=dm.Count("maskrating__rating"))
        .order_by("n_ratings")
    )
    if len(masks_in_layout) == 0:
        raise http.Http404("No masks in layout")

    return shortcuts.get_object_or_404(models.Mask, pk=masks_in_layout[0].get("id"))


def _redirect_to_mask_randomly_kwargs(mask: models.Mask) -> dict[str, typing.Any]:
    return {
        "mask_id": mask.pk,
        "img_id": mask.get_random_img_id(),
        "display_id": models.DisplayMode.get_random(),
    }


def _redirect_to_mask_randomly(
    mask: models.Mask,
) -> http.HttpResponse | http.HttpResponsePermanentRedirect:
    return shortcuts.redirect(RATE_MASK_VIEW, **_redirect_to_mask_randomly_kwargs(mask))


def _get_create_masks_from_layout(layout: models.Layout) -> models.Mask:
    logging.info("Reading dababase")
    # bids_layout = ancpbids.BIDSLayout(layout.src)
    # bids_layout = bids.BIDSLayout(database_path=layout.src, validate=False)
    logging.info("Getting anatomical files")
    # anats: list[str] = bids_layout.get(
    #     suffix="T1w", extension=".nii.gz", return_type="files"
    # )
    # if Path(layout.src).is_dir():
    masks: list[str] = (
        pl.read_database_uri(
            r"SELECT path FROM files WHERE path LIKE '%anat%desc-brain_mask.nii.gz'",
            uri=f"sqlite://{layout.src}/layout_index.sqlite",
        )
        .to_series()
        .to_list()
    )
    # else:
    #     bids_layout = ancpbids.BIDSLayout(layout.src)
    #     masks: list[str] = bids_layout.get(
    #         suffix="mask", extension=".nii.gz", return_type="files"
    #     )  # type: ignore
    # masks_existing = bids_layout.get(
    #     desc="brain", extension=".nii.gz", return_type="files"
    # )
    # masks_matched = [x.replace("preproc_T1w", "brain_mask") for x in anats]
    mask_objects = []
    # logging.info("Confirming masks exist")
    # for mask, anat in zip(masks_matched, anats):
    #     if mask not in masks_existing:
    #         continue
    #     m, _ = models.Mask.objects.get_or_create(layout=layout, file=anat, mask=mask)
    #     mask_objects.append(m)
    anats = [x.replace("desc-brain_mask", "T1w") for x in masks]
    logging.info("Adding masks to db")
    for mask, anat in zip(masks, anats):
        m, _ = models.Mask.objects.get_or_create(layout=layout, file=anat, mask=mask)

        mask_objects.append(m)
    logging.info("Making first mask figure")

    return random.choice(mask_objects)


# def index(
#     request: http.HttpRequest,
# ) -> http.HttpResponse | http.HttpResponsePermanentRedirect:
#     if request.method == "POST":
#         form = forms.IndexForm(request.POST)
#         if form.is_valid():
#             src = form.cleaned_data["src"]
#             layout, _ = models.Layout.objects.get_or_create(src=src)
#             mask = _get_create_masks_from_layout(layout)
#             return _redirect_to_mask_randomly(mask)
#     else:
#         form = forms.IndexForm()

#     return shortcuts.render(request, "index.html", {"form": form})


# def rate_mask(
#     request: http.HttpRequest, mask_id: int, display_id: int, img_id: int
# ) -> http.HttpResponse | http.HttpResponsePermanentRedirect:
#     mask = shortcuts.get_object_or_404(models.Mask, pk=mask_id)

#     if request.method == "POST":
#         form = forms.RatingForm(request.POST)
#         if form.is_valid():
#             mask_rating = models.MaskRating.objects.create(
#                 rating=form.cleaned_data["rating"], img_id=img_id, mask=mask
#             )
#             next_mask = mask_rating.mask.get_random_mask_from_layout(mask.layout)
#             return _redirect_to_mask_randomly(next_mask)
#     else:
#         form = forms.RatingForm()

#     return shortcuts.render(
#         request,
#         "rate_image.html",
#         {
#             "form": form,
#             "image": mask.get_image(
#                 img_id=img_id, display_mode=models.DisplayMode(display_id)
#             ),
#         },
#     )
