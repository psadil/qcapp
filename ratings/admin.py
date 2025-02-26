from django.contrib import admin

from . import models

admin.site.register([models.Mask, models.MaskRating, models.Rating, models.Layout])
