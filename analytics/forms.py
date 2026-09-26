"""Forms for the analytics pages (workbook update, US36)."""
from pathlib import Path

from django import forms
from django.template.defaultfilters import filesizeformat
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .exports import MONTHS_ES

MAX_WORKBOOK_BYTES = 20 * 1024 * 1024  # 20 MB
_FIRST_YEAR = 2022


def _year_choices() -> list[tuple[int, str]]:
    """Every year the workbook could plausibly cover, newest first."""
    this_year = timezone.localdate().year
    return [(y, str(y)) for y in range(this_year + 1, _FIRST_YEAR - 1, -1)]


class WorkbookUpdateForm(forms.Form):
    """The master workbook plus the month whose column should be filled."""

    workbook = forms.FileField(
        label=_("Your master workbook (.xlsx)"),
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx"}),
    )
    year = forms.TypedChoiceField(
        label=_("Year"),
        coerce=int,
        choices=_year_choices,
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    month = forms.TypedChoiceField(
        label=_("Month"),
        coerce=int,
        choices=[(i, name) for i, name in enumerate(MONTHS_ES, start=1)],
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def clean_workbook(self):
        upload = self.cleaned_data["workbook"]
        if Path(upload.name).suffix.lower() != ".xlsx":
            raise forms.ValidationError(
                _("That is not an .xlsx workbook. Upload your master analysis file.")
            )
        if upload.size > MAX_WORKBOOK_BYTES:
            raise forms.ValidationError(
                _("The file is too large (%(size)s). The limit is %(limit)s."),
                params={
                    "size": filesizeformat(upload.size),
                    "limit": filesizeformat(MAX_WORKBOOK_BYTES),
                },
            )
        return upload
