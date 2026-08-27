from pathlib import Path

import pytest

from sales.importers import get_importer_for
from sales.importers.base import BaseImporter
from sales.importers.excel_historical import ExcelHistoricalImporter
from sales.importers.pdf_daily import PdfDailyImporter


def test_xlsx_resolves_to_excel_importer():
    importer = get_importer_for(Path("history.xlsx"))

    assert isinstance(importer, ExcelHistoricalImporter)
    assert isinstance(importer, BaseImporter)


def test_pdf_resolves_to_pdf_importer():
    importer = get_importer_for(Path("daily.pdf"))

    assert isinstance(importer, PdfDailyImporter)
    assert isinstance(importer, BaseImporter)


def test_extension_match_is_case_insensitive():
    assert isinstance(get_importer_for(Path("HISTORY.XLSX")), ExcelHistoricalImporter)


def test_unknown_extension_raises():
    with pytest.raises(ValueError, match="No importer registered"):
        get_importer_for(Path("report.csv"))


def test_autodiscovery_registered_both_importers_without_explicit_imports():
    # Importing the package alone (no per-module imports) must register both
    # formats via autodiscover().
    import importlib

    from sales import importers

    importlib.reload(importers)

    assert isinstance(importers.get_importer_for(Path("a.xlsx")), ExcelHistoricalImporter)
    assert isinstance(importers.get_importer_for(Path("a.pdf")), PdfDailyImporter)
