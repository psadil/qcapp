from typing import ClassVar

from django import forms

from django_dirt_ratings import models, plan

Textarea = forms.Textarea(attrs={"class": "form-control"})
CheckboxInput = forms.CheckboxInput(attrs={"class": "form-check-input"})


class RatingForm(forms.ModelForm):
    class Meta:
        model = models.Rating
        fields = ("rating", "source_data_issue", "comments")
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "rating": forms.RadioSelect(attrs={"class": "btn-check"}),
            "comments": Textarea,
            "source_data_issue": CheckboxInput,
        }


class IndexForm(forms.ModelForm):
    class Meta:
        model = models.Session
        fields = ("step",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Offer only the steps the active review plan includes (all steps if no
        # plan restricts them), keeping any blank option.
        reviewable = {str(s.value) for s in plan.active().reviewable_steps}
        if reviewable:
            self.fields["step"].choices = [
                c
                for c in self.fields["step"].choices
                if c[0] in ("", None) or str(c[0]) in reviewable
            ]


class ClickForm(forms.ModelForm):
    class Meta:
        model = models.Annotation
        fields = ("source_data_issue", "comments")
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "comments": Textarea,
            "source_data_issue": CheckboxInput,
        }
