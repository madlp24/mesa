"""Forms for the self-service report upload (US25; multi-file US31)."""
from pathlib import Path

from django import forms
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext_lazy as _

ALLOWED_EXTENSIONS = {".pdf", ".xlsx"}
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB per file


class MultipleFileInput(forms.ClearableFileInput):
    """A file input that accepts several files at once (``multiple``)."""

    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """A ``FileField`` whose ``clean`` validates and returns a list of files."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"accept": ".pdf,.xlsx"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(item, initial) for item in data]
        return [single(data, initial)]


def _validate_report(upload) -> None:
    """Reject an upload that is not a supported, reasonably-sized report."""
    extension = Path(upload.name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise forms.ValidationError(
            _("Unsupported file type '%(ext)s'. Upload a .pdf or .xlsx report."),
            params={"ext": extension or upload.name},
        )
    if upload.size > MAX_UPLOAD_BYTES:
        raise forms.ValidationError(
            _("'%(name)s' is too large (%(size)s). The limit is %(limit)s per file."),
            params={
                "name": upload.name,
                "size": filesizeformat(upload.size),
                "limit": filesizeformat(MAX_UPLOAD_BYTES),
            },
        )


class ReportUploadForm(forms.Form):
    report = MultipleFileField(
        label=_("Soft Restaurant reports (.pdf or .xlsx) — one or several"),
    )

    def clean_report(self):
        uploads = self.cleaned_data["report"]
        for upload in uploads:
            _validate_report(upload)
        return uploads
