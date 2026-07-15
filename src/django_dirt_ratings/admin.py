from django.contrib import admin
from django.utils.html import format_html

from . import formatters, models


class ImageAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "file1",
        "step",
        "display",
        "slice",
        "image_preview",
        "created_at",
    ]
    list_filter = ["step", "display"]
    search_fields = ["file1", "file2"]
    readonly_fields = ["image_full"]

    @admin.display(description="Preview")
    def image_preview(self, obj: models.Image) -> str:
        if not obj.img:
            return "-"
        return format_html(
            '<img src="data:image/{};base64,{}" '
            'style="max-height:60px; max-width:120px;" />',
            models.Step(obj.step).image_type,
            formatters.image_to_base64(obj.img),
        )

    @admin.display(description="Image")
    def image_full(self, obj: models.Image) -> str:
        if not obj.img:
            return "-"
        return format_html(
            '<img src="data:image/{};base64,{}" style="max-width:100%;" />',
            models.Step(obj.step).image_type,
            formatters.image_to_base64(obj.img),
        )


class RatingAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "image",
        "session",
        "rating",
        "source_data_issue",
        "created_at",
    ]


admin.site.register(models.Image, ImageAdmin)
admin.site.register(models.Rating, RatingAdmin)
admin.site.register([models.Session, models.Annotation])
