"""Update the owner's real "Análisis unificado" workbook (US30).

The owner keeps a master workbook whose ``Productos vendidos`` sheet is a units
matrix with a **two-row header**: one row of years and, below it, one row of
month names (``Enero``..``Diciembre``), repeated per year. Rows are
``Grupo / Clave / Producto`` and each cell is the raw POS ``CANTIDAD`` for that
month (grams for cuts sold by weight, units for fixed portions) -- exactly what
Mesa already stores, so no conversion is needed.

:func:`update_productos_vendidos` fills the column for one ``(year, month)`` with
Mesa's per-product units for that period. Products are matched to existing rows
by NAME (the same fusion logic as the importer, US22) because POS claves are
unreliable and the historical spreadsheet names drift from the POS names; the
historical clave is never overwritten. Unmatched products are appended as new
rows. The result is written to a COPY -- the original is never modified.

Scope (agreed): only the ``Productos vendidos`` sheet. The ``Datos totales``
sheet (N/O/S/T from the PDF footer) is a separate story.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from catalog.identity import names_match, normalize_name

from .exports import MONTHS_ES, PRODUCTOS_VENDIDOS_SHEET, _matrix_data

_GROUP_COL = 1
_CLAVE_COL = 2
_NAME_COL = 3
_FIRST_MONTH_COL = 4


class UnifiedUpdateError(Exception):
    """The workbook cannot be updated (missing file, wrong layout, ...)."""


def _norm_clave(value) -> str:
    """Compare claves ignoring leading zeros (``"03028"`` == ``3028``)."""
    if value is None:
        return ""
    text = str(value).strip()
    return text.lstrip("0") or "0"


def _norm_month(value) -> str:
    return str(value).strip().capitalize() if value is not None else ""


def _locate_header(ws) -> tuple[int, int]:
    """Return ``(year_row, month_row)`` for the two-row header.

    The month row is the one whose first cell reads ``Grupo``; the year row sits
    directly above it. Raises when the layout is not recognized.
    """
    for row in range(1, 11):
        if str(ws.cell(row=row, column=_GROUP_COL).value or "").strip().lower() == "grupo":
            if row < 2:
                raise UnifiedUpdateError("No year row above the 'Grupo' header row.")
            return row - 1, row
    raise UnifiedUpdateError(
        f'Could not find the "Grupo/Clave/Producto" header in '
        f'"{PRODUCTOS_VENDIDOS_SHEET}".'
    )


def _find_month_column(ws, year_row: int, month_row: int, year: int, month: int) -> int:
    """Column index for ``(year, month)``, appending a new one if absent."""
    target_name = MONTHS_ES[month - 1]
    for col in range(_FIRST_MONTH_COL, ws.max_column + 1):
        cell_year = ws.cell(row=year_row, column=col).value
        cell_month = _norm_month(ws.cell(row=month_row, column=col).value)
        if str(cell_year).strip() == str(year) and cell_month == target_name:
            return col
    # Not in the grid: append a fresh two-row-header column at the end.
    col = ws.max_column + 1
    ws.cell(row=year_row, column=col, value=year)
    ws.cell(row=month_row, column=col, value=target_name)
    return col


def _existing_rows(ws, data_start: int) -> list[dict]:
    rows = []
    for r in range(data_start, ws.max_row + 1):
        name = ws.cell(row=r, column=_NAME_COL).value
        if name is None or str(name).strip() == "":
            continue
        rows.append(
            {
                "row": r,
                "norm": normalize_name(str(name)),
                "clave": _norm_clave(ws.cell(row=r, column=_CLAVE_COL).value),
            }
        )
    return rows


def _find_row(existing: list[dict], norm: str, clave: str) -> dict | None:
    """Match a product against existing rows: exact-normalized, then fusion."""
    for row in existing:
        if row["norm"] == norm:
            return row
    for row in existing:
        if names_match(norm, row["norm"], same_clave=(clave != "" and clave == row["clave"])):
            return row
    return None


def _detect_warnings(path: Path, workbook) -> list[str]:
    warnings = []
    lock = path.parent / f"~${path.name}"
    if lock.exists():
        warnings.append(
            f"'{path.name}' looks open in Excel (lock file {lock.name}); close it "
            "so the copy reflects the latest saved state."
        )
    if any(getattr(sheet, "_charts", None) for sheet in workbook.worksheets):
        warnings.append("workbook has charts; openpyxl does not preserve them.")
    if path.suffix.lower() == ".xlsm":
        warnings.append("workbook may contain macros; openpyxl does not preserve them.")
    return warnings


def update_productos_vendidos(
    path, restaurant, year: int, month: int
) -> dict:
    """Fill the ``(year, month)`` column of the units matrix in a copy of ``path``.

    Returns a summary with ``copy`` (written path), ``column`` (label like
    ``"AP / Marzo 2025"``), ``matched``/``appended`` counts, ``appended_names``
    (for review of possible name-drift mismatches) and ``warnings``.
    """
    if not 1 <= month <= 12:
        raise UnifiedUpdateError(f"Month out of range: {month}")
    path = Path(path)
    if not path.exists():
        raise UnifiedUpdateError(f"File not found: {path}")

    workbook = load_workbook(path)  # keep formulas (data_only=False)
    if PRODUCTOS_VENDIDOS_SHEET not in workbook.sheetnames:
        raise UnifiedUpdateError(
            f'Sheet "{PRODUCTOS_VENDIDOS_SHEET}" not found in {path.name}.'
        )
    ws = workbook[PRODUCTOS_VENDIDOS_SHEET]
    warnings = _detect_warnings(path, workbook)

    year_row, month_row = _locate_header(ws)
    data_start = month_row + 1
    col = _find_month_column(ws, year_row, month_row, year, month)

    _, products = _matrix_data(restaurant)
    period = (year, month)
    to_write = [p for p in products.values() if p["quantities"].get(period)]

    existing = _existing_rows(ws, data_start)
    matched = 0
    appended_names: list[str] = []
    append_at = ws.max_row + 1
    for product in sorted(to_write, key=lambda p: (p["grupo"] or "", p["name"])):
        norm = normalize_name(product["name"])
        clave = _norm_clave(product["clave"])
        match = _find_row(existing, norm, clave)
        if match is None:
            target = append_at
            append_at += 1
            ws.cell(row=target, column=_GROUP_COL, value=product["grupo"])
            ws.cell(row=target, column=_CLAVE_COL, value=product["clave"])
            ws.cell(row=target, column=_NAME_COL, value=product["name"])
            existing.append({"row": target, "norm": norm, "clave": clave})
            appended_names.append(product["name"])
        else:
            target = match["row"]
            ws.cell(row=target, column=_GROUP_COL, value=product["grupo"])  # refresh group
            matched += 1
        ws.cell(row=target, column=col, value=product["quantities"][period])

    from openpyxl.utils import get_column_letter

    copy = path.with_name(f"{path.stem} (Mesa {MONTHS_ES[month - 1]} {year}){path.suffix}")
    workbook.save(copy)
    return {
        "copy": copy,
        "column": f"{get_column_letter(col)} / {MONTHS_ES[month - 1]} {year}",
        "matched": matched,
        "appended": len(appended_names),
        "appended_names": appended_names,
        "warnings": warnings,
    }
