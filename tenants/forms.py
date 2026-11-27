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
    """Rename the restaurant, and hold its AutoFacturas token.

    The token is write-only in the UI: the field renders empty even when one is
    stored, and an empty submission keeps whatever is there. Printing a bearer
    token back into a page is how it ends up in a screenshot.
    """

    autofacturas_token = forms.CharField(
        required=False,
        label=_("AutoFacturas token"),
        help_text=_("Leave empty to keep the current one."),
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off"}),
    )

    class Meta:
        model = Restaurant
        fields = [
            "name", "autofacturas_token", "minimum_quote_margin",
            "target_cost_pct", "price_rise_cap", "menu_price_step",
        ]
        labels = {"name": _("Restaurant name")}


    minimum_quote_margin = forms.DecimalField(
        required=False, min_value=0, max_value=100,
        label=_("Minimum quote margin (%)"),
        help_text=_("Quotes under this margin are flagged."),
    )

    target_cost_pct = forms.DecimalField(
        required=False, min_value=1, max_value=100,
        label=_("Target food cost (%)"),
        help_text=_("Cost over the price without consumption tax, for menu families Mesa has no suggestion for. Each family's target is on the menu families page."),
    )
    price_rise_cap = forms.DecimalField(
        required=False, min_value=0, max_value=50,
        label=_("Largest price rise per change (%)"),
        help_text=_("Menu engineering never suggests raising a price by more than this at once."),
    )
    menu_price_step = forms.IntegerField(
        required=False, min_value=1,
        label=_("Round menu prices to"),
        help_text=_("Suggested prices are rounded to this amount, e.g. 1000."),
    )

    def clean_target_cost_pct(self):
        typed = self.cleaned_data.get("target_cost_pct")
        return self.instance.target_cost_pct if typed is None else typed

    def clean_price_rise_cap(self):
        typed = self.cleaned_data.get("price_rise_cap")
        return self.instance.price_rise_cap if typed is None else typed

    def clean_menu_price_step(self):
        typed = self.cleaned_data.get("menu_price_step")
        return self.instance.menu_price_step if typed is None else typed

    def clean_minimum_quote_margin(self):
        typed = self.cleaned_data.get("minimum_quote_margin")
        return self.instance.minimum_quote_margin if typed is None else typed

    def clean_autofacturas_token(self):
        typed = (self.cleaned_data.get("autofacturas_token") or "").strip()
        return typed or self.instance.autofacturas_token
