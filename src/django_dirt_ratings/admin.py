from django.contrib import admin
from django.utils.html import format_html

from . import models


class ImageAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "file1",
        "step",
        "display",
        "slice",
        "n_reviews",
        "priority",
        "image_preview",
        "created_at",
    )
    list_filter = ("step", "display", "review_plan")
    search_fields = ("file1", "file2")
    # Ordering outputs are researcher-facing transparency (never shown to raters):
    # the advisory priority the measures drive. The measures themselves are on the
    # file, under MeasuredFile.
    readonly_fields = ("image_full", "priority", "review_plan")

    @admin.display(description="Preview")
    def image_preview(self, obj: models.Image) -> str:
        if not obj.img:
            return "-"
        return format_html(
            '<img src="{}" style="max-height:60px; max-width:120px;" />',
            obj.img.url,
        )

    @admin.display(description="Image")
    def image_full(self, obj: models.Image) -> str:
        if not obj.img:
            return "-"
        return format_html(
            '<img src="{}" style="max-width:100%;" />',
            obj.img.url,
        )


class RatingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "image",
        "session",
        "rating",
        "source_data_issue",
        "created_at",
    )


class ReviewPlanAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active", "created_at")
    list_filter = ("is_active",)
    readonly_fields = ("content_hash", "toml", "created_at", "updated_at")


class MetricInline(admin.TabularInline):
    """This file's measurements, read-only — `render` is what writes them."""

    model = models.Metric
    extra = 0
    can_delete = False
    readonly_fields = ("name", "value")

    def has_add_permission(self, request, obj) -> bool:
        return False


class MeasuredFileAdmin(admin.ModelAdmin):
    list_display = ("id", "file1", "step", "review_plan", "updated_at")
    list_filter = ("step", "review_plan")
    search_fields = ("file1",)
    readonly_fields = ("step", "file1", "entities", "review_plan")
    inlines = (MetricInline,)


admin.site.register(models.Image, ImageAdmin)
admin.site.register(models.Rating, RatingAdmin)
admin.site.register(models.ReviewPlan, ReviewPlanAdmin)
admin.site.register(models.MeasuredFile, MeasuredFileAdmin)
admin.site.register([models.Session, models.Annotation])
