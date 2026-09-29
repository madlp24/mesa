"""One place decides what counts as a day's report (US39)."""
import datetime

import pytest
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas

from sales.importers.folder import select_daily_reports


def _report(path, *, start, end, venta="100,000.00"):
    lines = [
        f"PRODUCTOS VENDIDOS DEL {start} 06:00:00 AM AL {end} 06:00:00 AM",
        "GRUPO:COCTELES",
        "8100 NEGRONI $20,000.00 5.00 $100,000.00 $6,000.00 $0.00 $0.00 $0.00 $0.00",
        f"BEBIDAS: ${venta} (100%) 5 $30,000.00 $70,000.00",
        "ALIMENTOS: $0.00 (0%) 0 $0.00 $0.00",
    ]
    pdf = canvas.Canvas(str(path), pagesize=landscape(letter))
    pdf.setFont("Helvetica", 8)
    y = 560
    for line in lines:
        pdf.drawString(30, y, line)
        y -= 14
    pdf.save()
    return path


def test_an_aggregate_is_skipped_whatever_its_name(tmp_path):
    """The February file is an aggregate but its name never says "mes"."""
    _report(tmp_path / "dia.pdf", start="01/02/2026", end="02/02/2026")
    _report(tmp_path / "venta-costo Febrero 2026-SI.pdf",
            start="01/02/2026", end="01/03/2026")

    chosen, skipped = select_daily_reports(tmp_path)

    assert list(chosen) == [datetime.date(2026, 2, 1)]
    assert chosen[datetime.date(2026, 2, 1)].name == "dia.pdf"
    assert any("aggregate" in why for _, why in skipped)


def test_the_fuller_report_wins_a_repeated_date(tmp_path):
    _report(tmp_path / "a-partial.pdf", start="17/04/2026", end="18/04/2026",
            venta="1,000.00")
    _report(tmp_path / "z-full.pdf", start="17/04/2026", end="18/04/2026",
            venta="900,000.00")

    chosen, skipped = select_daily_reports(tmp_path)

    assert chosen[datetime.date(2026, 4, 17)].name == "z-full.pdf"
    assert any("partial" in why for _, why in skipped)


def test_metadata_twins_and_corrupt_files_do_not_stop_it(tmp_path):
    _report(tmp_path / "dia.pdf", start="01/02/2026", end="02/02/2026")
    (tmp_path / "._dia.pdf").write_bytes(b"\x00\x05\x16\x07")
    (tmp_path / "roto.pdf").write_bytes(b"nope")

    chosen, skipped = select_daily_reports(tmp_path)

    assert len(chosen) == 1
    assert any("unreadable" in why for _, why in skipped)
    assert not any(name.startswith("._") for name, _ in skipped)


@pytest.mark.parametrize("empty", [True])
def test_an_empty_folder_yields_nothing(tmp_path, empty):
    chosen, skipped = select_daily_reports(tmp_path)
    assert chosen == {} and skipped == []
