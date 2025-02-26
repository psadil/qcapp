# forms.py
from django import forms

from . import models


class RatingForm(forms.ModelForm):
    class Meta:
        model = models.Rating
        fields = ["rating"]
        widgets = {"rating": forms.RadioSelect}


class IndexForm(forms.ModelForm):
    class Meta:
        model = models.Layout
        fields = ["src"]
