"""Forms for tenant signup and settings (US26)."""
from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Restaurant


class RestaurantSignupForm(forms.Form):
    """Extra signup field (allauth ACCOUNT_SIGNUP_FORM_CLASS).

    A restaurant is auto-created for every new user by a signal; here we rename
    it to the name the user chose at signup.
    """

    restaurant_name = forms.CharField(
        max_length=120,
        label=_("Restaurant name"),
        widget=forms.TextInput(attrs={"placeholder": _("e.g. La Parrilla")}),
    )

    def signup(self, request, user):
        name = self.cleaned_data["restaurant_name"].strip()
        membership = getattr(user, "membership", None)
        if name and membership:
            restaurant = membership.restaurant
            restaurant.name = name
            restaurant.slug = ""  # regenerate a slug from the chosen name
            restaurant.save()


class RestaurantSettingsForm(forms.ModelForm):
    class Meta:
        model = Restaurant
        fields = ["name"]
        labels = {"name": _("Restaurant name")}
