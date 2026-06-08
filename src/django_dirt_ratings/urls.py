from django.urls import path

from django_dirt_ratings import views
from django_dirt_ratings.api import api

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
    path(f"{views.DTIFIT_VIEW}/", views.RateDTIFIT.as_view(), name=views.DTIFIT_VIEW),
    path(
        f"{views.RATE_PARTIAL}/", views.RatePartial.as_view(), name=views.RATE_PARTIAL
    ),
    path(
        f"{views.CLICK_PARTIAL}/",
        views.ClickPartial.as_view(),
        name=views.CLICK_PARTIAL,
    ),
    # API endpoints
    path("api/", api.urls),
]
