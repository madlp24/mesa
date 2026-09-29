"""Decide which files in a folder of POS reports are a day's report.

A real folder of exports is messier than it looks, and both the sales importer
and the workbook updater have to agree on what a day is. The rules, each earned
from the 2026 folders:

* the POS prints a **whole month** in the same layout as a day -- importing it
  alongside the days counts the month twice;
* a date can appear **twice**, once as a partial cut ("HORA EXACTA", "por una
  cuenta"). The complete day always totals at least as much as a slice of it,
  so the fuller report wins;
* macOS leaves a **metadata twin** (``._name.pdf``) next to each file on a FAT
  drive, and a file can simply be corrupt. Neither should cost the month.
"""
from __future__ import annotations

import datetime
import logging
from pathlib import Path

from .pdf_daily import parse_daily_totals, read_period

logger = logging.getLogger(__name__)


def _fullness(path: Path) -> float:
    """How much of a day a report accounts for, used to break a tie."""
    try:
        totals = parse_daily_totals(path)
    except Exception:  # unreadable: it cannot outrank anything
        return -1.0
    if totals is None:
        return -1.0
    return float(totals.venta_bar + totals.venta_cocina)


def select_daily_reports(
    folder: Path,
) -> tuple[dict[datetime.date, Path], list[tuple[str, str]]]:
    """Return ``{date: report}`` for the folder, plus ``(name, reason)`` skips."""
    chosen: dict[datetime.date, Path] = {}
    skipped: list[tuple[str, str]] = []

    for pdf in sorted(Path(folder).glob("*.pdf")):
        if pdf.name.startswith("._"):
            continue  # macOS metadata twin, never a report
        try:
            period = read_period(pdf)
        except Exception as exc:
            skipped.append((pdf.name, f"unreadable ({type(exc).__name__})"))
            continue
        if period is None:
            skipped.append((pdf.name, "no period printed"))
            continue

        day, span = period
        if span > 1:
            skipped.append((pdf.name, f"covers {span} days -- an aggregate"))
            continue

        rival = chosen.get(day)
        if rival is None:
            chosen[day] = pdf
        elif _fullness(pdf) > _fullness(rival):
            chosen[day] = pdf
            skipped.append((rival.name, f"partial report for {day}"))
        else:
            skipped.append((pdf.name, f"partial report for {day}"))

    return chosen, skipped
