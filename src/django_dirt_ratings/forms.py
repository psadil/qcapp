from typing import ClassVar, cast

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from django_dirt_ratings import models, plan

# Bootstrap styles form controls by class, not by element, so a widget rendered
# as a bare `{{ field }}` comes out as an unstyled browser default. Declaring
# the class on the widget is what keeps it out of the templates: `{{ field }}`
# then renders correctly wherever it appears. `rows` overrides Django's default
# of 10 — a comment box, not an essay.
Textarea = forms.Textarea(attrs={"class": "form-control", "rows": 2})
CheckboxInput = forms.CheckboxInput(attrs={"class": "form-check-input"})
Select = forms.Select(attrs={"class": "form-select"})


class RatingForm(forms.ModelForm):
    class Meta:
        model = models.Rating
        fields = ("rating", "source_data_issue", "comments")
        widgets: ClassVar[dict[str, forms.Widget]] = {
            "rating": forms.RadioSelect(attrs={"class": "btn-check"}),
            "comments": Textarea,
            "source_data_issue": CheckboxInput,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Drop the auto-added blank choice: it renders as a pre-checked
        # '---------' radio, which satisfies the native required-group check
        # and lets a ratingless submission through to the server.
        rating_field = self.fields["rating"]
        if not isinstance(rating_field, forms.ChoiceField):  # IntegerField w/ choices
            raise TypeError(
                f"expected a ChoiceField for rating, got {type(rating_field)}"
            )
        choices = cast("list[tuple[object, str]]", rating_field.choices)
        rating_field.choices = [c for c in choices if c[0] not in ("", None)]


class IndexForm(forms.ModelForm):
    class Meta:
        model = models.Session
        fields = ("step",)
        widgets: ClassVar[dict[str, forms.Widget]] = {"step": Select}

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


class LoginForm(AuthenticationForm):
    """Django's login form, with Bootstrap-shaped controls.

    ``LoginView`` renders each field as a bare ``{{ field }}``, and a template
    has no way to add a widget attribute — so without this the login page shows
    raw browser inputs, laid out inline beside their labels. Applied to every
    field rather than named ones so the form keeps the attributes Django sets
    itself (the username autofocus, the password autocomplete hint).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
