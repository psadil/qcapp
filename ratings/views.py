import abc
import json
import logging
from pathlib import Path

import polars as pl
import pydantic
from asgiref import sync
from django import http, shortcuts, urls, views
from django.db import models as dm
from django.views.generic import edit

from . import forms, models

MASK_VIEW = "mask"
ANAT_VIEW = "anat"
SURFACE_LOCALIZATION_VIEW = "surface_localization"
FMAP_COREGISTRATION_VIEW = "fmap_coregistration"

RATE_MASK_VIEW = f"rate_{MASK_VIEW}"
RATE_ANAT_VIEW = f"rate_{ANAT_VIEW}"
RATE_SURFACE_LOCALIZATION_VIEW = f"rate_{SURFACE_LOCALIZATION_VIEW}"
RATE_FMAP_COREGISTRATION_VIEW = f"rate_{FMAP_COREGISTRATION_VIEW}"


class LayoutCache(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(arbitrary_types_allowed=True)

    layout: models.Layout | None = None


layout_cache = LayoutCache()


class StepView(abc.ABC, views.View):
    template_name = "main.html"

    @abc.abstractmethod
    async def get_kwargs(self) -> dict:
        raise NotImplementedError

    async def get(self, request: http.HttpRequest) -> http.HttpResponse:
        logging.info("serving image")
        result = shortcuts.render(request, self.template_name, await self.get_kwargs())
        return result


# note: not a FormView because the (dynamic) image cannot be placed in form
class RateView(abc.ABC, views.View):
    form_class = forms.RatingForm
    template_name = "rate_image.html"

    @property
    @abc.abstractmethod
    def step_view(self) -> type[StepView]:
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def rating_model(self) -> type[models.BaseRating]:
        raise NotImplementedError

    async def get(self, request: http.HttpRequest) -> http.HttpResponse:
        image_kwargs = await self.step_view().get_kwargs()
        logging.info("rendering")
        return shortcuts.render(
            request, self.template_name, {"form": self.form_class(), **image_kwargs}
        )

    async def post(self, request: http.HttpRequest) -> http.HttpResponse:
        form = self.form_class(request.POST)
        if form.is_valid():
            logging.info("saving rating")

            rating = sync.sync_to_async(form.save)()

            await self.rating_model.from_request_rating(
                rating=await rating, request=request
            )
            return http.HttpResponse("ok")

        raise http.Http404("Submitted invalid rating")


class MaskView(StepView):
    async def get_kwargs(self) -> dict:
        logging.info("setting next")
        display_id = models.DisplayMode.get_random()
        if layout_cache.layout is None:
            raise http.Http404("Layout not set?")
        mask = await _get_mask_with_fewest_ratings(layout=layout_cache.layout)

        img_id = mask.get_random_img_id()
        image = mask.get_image(
            img_id=img_id, display_mode=models.DisplayMode(display_id)
        )

        return {
            "image": await image,
            "get_dst": MASK_VIEW,
            "post_dst": RATE_MASK_VIEW,
            "extra": json.dumps(
                {"mask_id": mask.pk, "img_id": img_id, "display_id": display_id}
            ),
        }


class AnatView(StepView):
    async def get_kwargs(self) -> dict:
        logging.info("setting next")
        if layout_cache.layout is None:
            raise http.Http404("Layout not set?")
        anat = await _get_anat_with_fewest_ratings(layout=layout_cache.layout)

        img_id = models.SpatialNormalizationView.get_random()
        image = anat.get_image(view=models.SpatialNormalizationView(img_id))

        return {
            "image": await image,
            "get_dst": ANAT_VIEW,
            "post_dst": RATE_ANAT_VIEW,
            "extra": json.dumps({"file_id": anat.pk, "img_id": img_id}),
        }


class SurfaceLocalizationView(StepView):
    async def get_kwargs(self) -> dict:
        logging.info("setting next")
        display_id = models.DisplayMode.get_random()
        if layout_cache.layout is None:
            raise http.Http404("Layout not set?")
        surface = await _get_surface_localization_with_fewest_ratings(
            layout=layout_cache.layout
        )

        img_id = surface.get_random_img_id()
        image = surface.get_image(
            img_id=img_id, display_mode=models.DisplayMode(display_id)
        )

        return {
            "image": await image,
            "get_dst": SURFACE_LOCALIZATION_VIEW,
            "post_dst": RATE_SURFACE_LOCALIZATION_VIEW,
            "extra": json.dumps(
                {
                    "surface_localization_id": surface.pk,
                    "img_id": img_id,
                    "display_id": display_id,
                }
            ),
        }


class FMapCoregistrationView(StepView):
    async def get_kwargs(self) -> dict:
        logging.info("setting next")
        display_id = models.DisplayMode.get_random()
        if layout_cache.layout is None:
            raise http.Http404("Layout not set?")
        fmap_coregistration = await _get_fmap_coregistration_with_fewest_ratings(
            layout=layout_cache.layout
        )

        img_id = fmap_coregistration.get_random_img_id(axis=display_id)
        image = fmap_coregistration.get_image(
            img_id=img_id, display_mode=models.DisplayMode(display_id)
        )

        return {
            "image": await image,
            "get_dst": FMAP_COREGISTRATION_VIEW,
            "post_dst": RATE_FMAP_COREGISTRATION_VIEW,
            "extra": json.dumps(
                {
                    "fmap_coregistration_id": fmap_coregistration.pk,
                    "img_id": img_id,
                    "display_id": display_id,
                }
            ),
        }


class RateMask(RateView):
    @property
    def step_view(self) -> type[MaskView]:
        return MaskView

    @property
    def rating_model(self) -> type[models.MaskRating]:
        return models.MaskRating


class RateAnat(RateView):
    @property
    def step_view(self) -> type[AnatView]:
        return AnatView

    @property
    def rating_model(self) -> type[models.SpatialNormalizationRating]:
        return models.SpatialNormalizationRating


class RateSurfaceLocalization(RateView):
    @property
    def step_view(self) -> type[SurfaceLocalizationView]:
        return SurfaceLocalizationView

    @property
    def rating_model(self) -> type[models.SurfaceLocalizationRating]:
        return models.SurfaceLocalizationRating


class RateFMapCoregistration(RateView):
    @property
    def step_view(self) -> type[FMapCoregistrationView]:
        return FMapCoregistrationView

    @property
    def rating_model(self) -> type[models.FMapCoregistrationRating]:
        return models.FMapCoregistrationRating


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
        if self.form is None:
            raise http.Http404("Trying to advance with invalid form")
        match self.form.cleaned_data.get("step"):
            case 0:
                _create_masks_from_layout(layout)
                return urls.reverse(f"{RATE_MASK_VIEW}")
            case 1:
                _create_anats_from_layout(layout)
                return urls.reverse(f"{RATE_ANAT_VIEW}")
            case 2:
                _create_surface_localizations_from_layout(layout)
                return urls.reverse(f"{RATE_SURFACE_LOCALIZATION_VIEW}")
            case 3:
                _create_fmap_coregistrations_from_layout(layout)
                return urls.reverse(f"{RATE_FMAP_COREGISTRATION_VIEW}")
            case _:
                raise http.Http404("Unknown step")

    def form_valid(self, form: forms.IndexForm):
        # we only want the layout to be in the database once
        self.form = form
        logging.info("here 1")
        try:
            logging.info("checking if layout exists")
            self.get_layout()
        except models.Layout.DoesNotExist:
            logging.info("layout does not exist")
            form.save()
        layout_cache.layout = self.get_layout()
        return super().form_valid(form)


async def _get_surface_localization_with_fewest_ratings(
    layout: models.Layout,
) -> models.SurfaceLocalization:
    masks_in_layout = await (
        models.SurfaceLocalization.objects.filter(layout_id=layout.pk)
        .select_related("surfacelocalizationrating")
        .filter(~dm.Q(surfacelocalizationrating__rating=models.Ratings.NOT_INFORMATIVE))
        .values("id")
        .annotate(n_ratings=dm.Count("surfacelocalizationrating__rating"))
        .order_by("n_ratings")
        .afirst()
    )
    if masks_in_layout is None:
        raise http.Http404("No masks in layout")

    return await models.SurfaceLocalization.objects.aget(pk=masks_in_layout.get("id"))


async def _get_mask_with_fewest_ratings(layout: models.Layout) -> models.Mask:
    masks_in_layout = await (
        models.Mask.objects.filter(layout_id=layout.pk)
        .select_related("maskrating")
        .filter(~dm.Q(maskrating__rating=models.Ratings.NOT_INFORMATIVE))
        .values("id")
        .annotate(n_ratings=dm.Count("maskrating__rating"))
        .order_by("n_ratings")
        .afirst()
    )
    if masks_in_layout is None:
        raise http.Http404("No masks in layout")

    return await models.Mask.objects.aget(pk=masks_in_layout.get("id"))


async def _get_anat_with_fewest_ratings(
    layout: models.Layout,
) -> models.SpatialNormalization:
    files_in_layout = await (
        models.SpatialNormalization.objects.filter(layout=layout)
        .select_related("spatialnormalizationrating")
        .filter(
            ~dm.Q(spatialnormalizationrating__rating=models.Ratings.NOT_INFORMATIVE)
        )
        .values("id")
        .annotate(n_ratings=dm.Count("spatialnormalizationrating__rating"))
        .order_by("n_ratings")
        .afirst()
    )
    if files_in_layout is None:
        msg = f"No anats in layout {layout}"
        raise http.Http404(msg)

    return await models.SpatialNormalization.objects.aget(pk=files_in_layout.get("id"))


async def _get_fmap_coregistration_with_fewest_ratings(
    layout: models.Layout,
) -> models.FMapCoregistration:
    masks_in_layout = await (
        models.FMapCoregistration.objects.filter(layout_id=layout.pk)
        .select_related("fmapcoregistrationrating")
        .filter(~dm.Q(fmapcoregistrationrating__rating=models.Ratings.NOT_INFORMATIVE))
        .values("id")
        .annotate(n_ratings=dm.Count("fmapcoregistrationrating__rating"))
        .order_by("n_ratings")
        .afirst()
    )
    if masks_in_layout is None:
        raise http.Http404("No fmapcoregistrations in layout")

    return await models.FMapCoregistration.objects.aget(pk=masks_in_layout.get("id"))


def _create_masks_from_layout(layout: models.Layout):
    logging.info("Getting anatomical files")
    masks: list[str] = (
        pl.read_database_uri(
            r"SELECT path FROM files WHERE path LIKE '%anat%desc-brain_mask.nii.gz'",
            uri=f"sqlite://{layout.src}/layout_index.sqlite",
        )
        .to_series()
        .to_list()
    )

    anats = [x.replace("desc-brain_mask", "T1w") for x in masks]
    logging.info("Adding masks to db")
    for mask, anat in zip(masks, anats):
        models.Mask.objects.get_or_create(
            layout=layout_cache.layout, mask=mask, file=anat
        )

    logging.info("Finished adding masks")


def _create_anats_from_layout(layout: models.Layout):
    logging.info("Getting anatomical files")
    anats: list[str] = (
        pl.read_database_uri(
            r"SELECT path FROM files WHERE path LIKE '%anat%MNI152NLin2009cAsym_desc-preproc_T1w.nii.gz'",
            uri=f"sqlite://{layout.src}/layout_index.sqlite",
        )
        .to_series()
        .to_list()
    )

    logging.info("Adding anats to db")
    for anat in anats:
        models.SpatialNormalization.objects.get_or_create(
            layout=layout_cache.layout, file=anat
        )
    logging.info("Finished adding anats")


def _create_surface_localizations_from_layout(layout: models.Layout):
    mris = [s / "mri" for s in Path(layout.src).glob("sub*")]

    logging.info("Adding ribbons to db")
    for mri in mris:
        models.SurfaceLocalization.objects.get_or_create(
            layout=layout_cache.layout,
            anat=mri / "brain.mgz",
            ribbon=mri / "ribbon.mgz",
        )
    logging.info("Finished adding ribbons")


def _create_fmap_coregistrations_from_layout(layout: models.Layout):
    logging.info("Getting files")
    masks: list[str] = (
        pl.read_database_uri(
            r"SELECT path FROM files WHERE path LIKE '%func%desc-brain_mask.nii.gz' AND path NOT LIKE '%MNI%'",
            uri=f"sqlite://{layout.src}/layout_index.sqlite",
        )
        .to_series()
        .to_list()
    )
    logging.info(masks)
    anats: list[str] = []
    for mask in masks:
        fmaps = list(
            (Path(mask).parent.parent / "fmap").glob("*desc-epi_fieldmap.nii.gz")
        )
        logging.info(fmaps)
        if len(fmaps) == 0:
            raise http.Http404("No fmaps found")
        anats.append(str(fmaps[0]))

    logging.info("Adding masks to db")
    for mask, anat in zip(masks, anats):
        models.FMapCoregistration.objects.get_or_create(
            layout=layout_cache.layout, mask=mask, file=anat
        )

    logging.info("Finished adding masks")
