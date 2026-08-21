from typing import ClassVar, cast

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
        step_field = self.fields["step"]
        if not isinstance(step_field, forms.ChoiceField):  # IntegerField w/ choices
            raise TypeError(f"expected a ChoiceField for step, got {type(step_field)}")
        reviewable = {str(s.value) for s in plan.active().reviewable_steps}
        if reviewable:
            # The stubs type the `.choices` getter as the whole assignable union;
            # Django normalizes on assignment, so reading back gives (value, label)
            # pairs — the cast states that.
            choices = cast("list[tuple[object, str]]", step_field.choices)
            step_field.choices = [
                c for c in choices if c[0] in ("", None) or str(c[0]) in reviewable
            ]


class ClickForm(forms.ModelForm):
    class Meta:
        model = models.Annotation
        fields = ("source_data_issue", "comments")
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "comments": Textarea,
            "source_data_issue": CheckboxInput,
        }
