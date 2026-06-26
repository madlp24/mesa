"""Forms for the self-service report upload (US25)."""
from pathlib import Path

from django import forms
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext_lazy as _

ALLOWED_EXTENSIONS = {".pdf", ".xlsx"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


class ReportUploadForm(forms.Form):
    report = forms.FileField(
        label=_("Soft Restaurant report (.pdf or .xlsx)"),
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf,.xlsx"}),
    )

    def clean_report(self):
        upload = self.cleaned_data["report"]
        extension = Path(upload.name).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise forms.ValidationError(
                _("Unsupported file type '%(ext)s'. Upload a .pdf or .xlsx report."),
                params={"ext": extension or upload.name},
            )
        if upload.size > MAX_UPLOAD_BYTES:
            raise forms.ValidationError(
                _("File is too large (%(size)s). The limit is %(limit)s."),
                params={
                    "size": filesizeformat(upload.size),
                    "limit": filesizeformat(MAX_UPLOAD_BYTES),
                },
            )
        return upload
