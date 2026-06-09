import base64

from django import shortcuts, urls
from django.contrib import admin
from django.utils.html import format_html

from . import models
from .selectors import img_type_for_step


class ImageAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "file1",
        "step",
        "display",
        "slice",
        "image_preview",
        "created",
    ]
    list_filter = ["step", "display"]
    search_fields = ["file1", "file2"]
    readonly_fields = ["image_full"]

    @admin.display(description="Preview")
    def image_preview(self, obj: models.Image) -> str:
        if not obj.img:
            return "-"
        img_type = img_type_for_step(obj.step)
        b64 = base64.b64encode(obj.img).decode()
        return format_html(
            '<img src="data:image/{};base64,{}" '
            'style="max-height:60px; max-width:120px;" />',
            img_type,
            b64,
        )

    @admin.display(description="Image")
    def image_full(self, obj: models.Image) -> str:
        if not obj.img:
            return "-"
        img_type = img_type_for_step(obj.step)
        b64 = base64.b64encode(obj.img).decode()
        return format_html(
            '<img src="data:image/{};base64,{}" style="max-width:100%;" />',
            img_type,
            b64,
        )


class RatingAdmin(admin.ModelAdmin):
    list_display = ["id", "image", "session", "rating", "source_data_issue", "created"]

    @admin.action(description="Download all ratings")
    def download_view(self, request):
        """Redirects to the API endpoint for downloading ratings"""
        # The default name for the NinjaAPI instance is "api-1.0.0"
        api_url = urls.reverse("api-1.0.0:list_ratings")
        return shortcuts.redirect(api_url)


admin.site.register(models.Image, ImageAdmin)
admin.site.register(models.Rating, RatingAdmin)
admin.site.register([models.Session, models.ClickedCoordinate])
