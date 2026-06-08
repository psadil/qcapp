from django import forms

from django_dirt_ratings import models

Textarea = forms.Textarea(attrs={"class": "form-control"})
CheckboxInput = forms.CheckboxInput(attrs={"class": "form-check-input"})


class RatingForm(forms.ModelForm):
    class Meta:
        model = models.Rating
        fields = ["rating", "source_data_issue", "comments"]
        widgets = {
            "rating": forms.RadioSelect(attrs={"class": "btn-check"}),
            "comments": Textarea,
            "source_data_issue": CheckboxInput,
        }


class IndexForm(forms.ModelForm):
    class Meta:
        model = models.Session
        fields = ["step"]


class ClickForm(forms.ModelForm):
    class Meta:
        model = models.ClickedCoordinate
        fields = ["source_data_issue", "comments"]
        widgets = {"comments": Textarea, "source_data_issue": CheckboxInput}
