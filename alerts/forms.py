from django import forms
from django.utils.translation import gettext_lazy as _

from .models import AlertSettings


class AlertSettingsForm(forms.ModelForm):
    class Meta:
        model = AlertSettings
        fields = ["cadence", "baseline", "cost_rise", "margin_drop", "abrupt_change", "min_weekly_sales"]
        widgets = {
            "cadence": forms.RadioSelect(attrs={"class": "form-check-input"}),
            "baseline": forms.RadioSelect(attrs={"class": "form-check-input"}),
        }
        labels = {
            "cadence": _("Period watched"),
            "baseline": _("Compared with"),
            "cost_rise": _("Cost rise or price drop (%)"),
            "margin_drop": _("Margin points lost"),
            "abrupt_change": _("Abrupt change (%)"),
            "min_weekly_sales": _("Leave out products selling less than, a week"),
        }
        help_texts = {
            "cost_rise": _("A product whose cost per portion rose, or whose price fell, at least this much."),
            "margin_drop": _("A product whose margin shrank at least this many points."),
            "abrupt_change": _("One day, or one supplier purchase, that jumps at least this much against the usual level."),
            "min_weekly_sales": _("Keeps small sellers out of the list. In pesos."),
        }
