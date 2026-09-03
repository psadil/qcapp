"""
URL configuration for dirt project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from django_dirt_ratings import forms, views

urlpatterns = [
    path("", include("django_dirt_ratings.urls")),
    path("admin/", admin.site.urls),
    # Login and logout only, rather than include("django.contrib.auth.urls"):
    # raters are issued a password by `manage create_rater` and never set their
    # own, so nothing routes password_change or password_reset (which would
    # render to anonymous visitors and 500 on submit — no mail backend exists).
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(authentication_form=forms.LoginForm),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Rendered QC images are subject-derived, so media requires login and is
    # served by Django itself (works with DEBUG off; fine at this tool's scale).
    path("media/<path:path>", views.media_file, name="media"),
]
