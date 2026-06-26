"""Self-service web upload of Soft Restaurant reports (US25)."""
import logging
import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from sales.forms import ReportUploadForm
from sales.importers import get_importer_for, persist

logger = logging.getLogger(__name__)


@login_required
def upload_report(request: HttpRequest) -> HttpResponse:
    """Upload a POS report and import it into the current restaurant."""
    summary = None
    form = ReportUploadForm()

    if request.method == "POST":
        form = ReportUploadForm(request.POST, request.FILES)
        if form.is_valid():
            summary = _import_upload(request, form.cleaned_data["report"])
            if summary is not None:
                form = ReportUploadForm()  # reset after a successful import

    return render(request, "sales/upload.html", {"form": form, "summary": summary})


def _import_upload(request: HttpRequest, upload) -> dict | None:
    """Run the importer for one uploaded file; return a summary or None on error."""
    extension = Path(upload.name).suffix.lower()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp_path = Path(tmp.name)
        importer = get_importer_for(tmp_path)
        canonical = importer.normalize(tmp_path)
        result = persist(canonical, request.restaurant)
    except Exception:
        logger.exception("Report upload failed for %s", upload.name)
        messages.error(
            request,
            _("We couldn't read that report. Make sure it is a Soft Restaurant "
              "'Productos Vendidos' export and try again."),
        )
        return None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    messages.success(request, _("Report imported successfully."))
    return {
        "filename": upload.name,
        "new": result["new"],
        "items": result["items"],
        "skipped_duplicate": result["skipped_duplicate"],
        "skipped_rows": getattr(importer, "skipped_rows", 0),
    }
