from django.urls import path

from . import views

urlpatterns = [
    path("", views.LayoutView.as_view(), name="index"),
    path(f"{views.MASK_VIEW}/", views.RateMask.as_view(), name=views.MASK_VIEW),
    path(
        f"{views.SPATIAL_NORMALIZATION_VIEW}/",
        views.RateSpatialNormalization.as_view(),
        name=views.SPATIAL_NORMALIZATION_VIEW,
    ),
    path(
        f"{views.SURFACE_LOCALIZATION_VIEW}/",
        views.RateSurfaceLocalization.as_view(),
        name=views.SURFACE_LOCALIZATION_VIEW,
    ),
    path(
        f"{views.FMAP_COREGISTRATION_VIEW}/",
        views.RateFMapCoregistration.as_view(),
        name=views.FMAP_COREGISTRATION_VIEW,
    ),
    path(
        f"{views.DTIFIT_VIEW}/",
        views.RateDTIFIT.as_view(),
        name=views.DTIFIT_VIEW,
    ),
]
