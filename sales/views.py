"""Self-service web upload of Soft Restaurant reports (US25) + history (US28)."""
import logging
import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from sales.forms import ReportUploadForm
from sales.models import ImportBatch
from sales.services import run_import, undo_import

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

    context = {
        "form": form,
        "summary": summary,
        "imports": ImportBatch.objects.filter(restaurant=request.restaurant),
    }
    return render(request, "sales/upload.html", context)


def _import_upload(request: HttpRequest, upload) -> dict | None:
    """Run the importer for one uploaded file; return a summary or None on error."""
    extension = Path(upload.name).suffix.lower()
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as tmp:
            for chunk in upload.chunks():
                tmp.write(chunk)
            tmp_path = Path(tmp.name)
        batch = run_import(
            tmp_path, request.restaurant, filename=upload.name, source="web"
        )
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
        "filename": batch.filename,
        "new": batch.sales_created,
        "items": batch.items_created,
        "skipped_duplicate": batch.skipped_duplicate,
        "skipped_rows": batch.skipped_rows,
    }


@login_required
@require_POST
def undo_import_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Undo an import: delete the sales it created (scoped to my restaurant)."""
    batch = get_object_or_404(ImportBatch, pk=pk, restaurant=request.restaurant)
    deleted = undo_import(batch)
    messages.success(
        request,
        _("Import undone: %(count)d sales removed.") % {"count": deleted},
    )
    return redirect("sales:upload")
