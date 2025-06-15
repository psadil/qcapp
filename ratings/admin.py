from django.contrib import admin

from . import models

admin.site.register([models.Image, models.Rating, models.Session])
