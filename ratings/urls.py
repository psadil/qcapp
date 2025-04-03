from django.urls import path

from . import views

urlpatterns = [
    path("", views.LayoutView.as_view(), name="index"),
    path(
        f"{views.RATE_MASK_VIEW}/",
        views.RateMask.as_view(),
        name=views.RATE_MASK_VIEW,
    ),
    path(f"{views.MASK_VIEW}/", views.MaskView.as_view(), name=views.MASK_VIEW),
    path(
        f"{views.RATE_ANAT_VIEW}/",
        views.RateAnat.as_view(),
        name=views.RATE_ANAT_VIEW,
    ),
    path(f"{views.ANAT_VIEW}/", views.AnatView.as_view(), name=views.ANAT_VIEW),
    path(
        f"{views.RATE_SURFACE_LOCALIZATION_VIEW}/",
        views.RateSurfaceLocalization.as_view(),
        name=views.RATE_SURFACE_LOCALIZATION_VIEW,
    ),
    path(
        f"{views.SURFACE_LOCALIZATION_VIEW}/",
        views.SurfaceLocalizationView.as_view(),
        name=views.SURFACE_LOCALIZATION_VIEW,
    ),
    path(
        f"{views.RATE_FMAP_COREGISTRATION_VIEW}/",
        views.RateFMapCoregistration.as_view(),
        name=views.RATE_FMAP_COREGISTRATION_VIEW,
    ),
    path(
        f"{views.FMAP_COREGISTRATION_VIEW}/",
        views.FMapCoregistrationView.as_view(),
        name=views.FMAP_COREGISTRATION_VIEW,
    ),
]
