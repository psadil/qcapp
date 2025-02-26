from django.urls import path

from . import views

urlpatterns = [
    path("", views.LayoutView.as_view(), name="index"),
    path(
        f"{views.RATE_MASK_VIEW}/<int:display_id>/<int:mask_id>/<int:img_id>",
        views.RateMask.as_view(),
        name=views.RATE_MASK_VIEW,
    ),
]
