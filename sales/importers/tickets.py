"""Read the bill-level POS export ("REPORTE DE VENTAS").

One row per bill: folio, closing time, people, items, food, drinks, subtotal,
discounts, tax. Mesa only takes the turnout from it -- how many people and how
many bills each day had -- because the money already comes from the
"Productos Vendidos" reports.

The **operating day** is what matters: the POS runs 06:00 to 06:00, so a bill
closed at 1am belongs to the night before. Grouping the real export that way put
3,116 bills into exactly the 235 days the daily reports cover.
"""
from __future__ import annotations

import datetime
import io
import re
from collections import defaultdict
from decimal import Decimal
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook

# "2/01/2026 2:24:20 p. m." -- Spanish am/pm, sometimes with non-breaking spaces.
_CLOSED_AT = re.compile(
    r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2}):(\d{2})\s*([ap])\.?\s*m\.?",
    re.IGNORECASE,
)
_HEADER = "NÚMERODEPERSONAS"
# The POS day starts at 06:00; anything earlier belongs to the previous day.
_DAY_STARTS_AT = datetime.timedelta(hours=6)


@dataclass(frozen=True)
class DayCovers:
    """One operating day: who came, and -- when known -- what they left.

    The money is optional: the bill-level export carries turnout only, while
    the owner's sheet carries both.
    """

    date: datetime.date
    guests: int
    accounts: int
    bar_sales: Decimal | None = None
    bar_cost: Decimal | None = None
    kitchen_sales: Decimal | None = None
    kitchen_cost: Decimal | None = None


class TicketExportError(ValueError):
    """The file is not the bill-level export Mesa expects."""


def parse_closed_at(raw) -> datetime.datetime | None:
    """Parse the POS closing stamp, or None when the cell is not one."""
    if isinstance(raw, datetime.datetime):
        return raw
    match = _CLOSED_AT.search(str(raw).replace(" ", " "))
    if not match:
        return None
    day, month, year, hour, minute, second, half = match.groups()
    hour = int(hour) % 12
    if half.lower() == "p":
        hour += 12
    return datetime.datetime(
        int(year), int(month), int(day), hour, int(minute), int(second)
    )


def operating_day(closed_at: datetime.datetime) -> datetime.date:
    """The day a bill belongs to, given the 06:00 cutoff."""
    return (closed_at - _DAY_STARTS_AT).date()


# Columns of the owner's "Datos totales" sheet: date, guests, accounts.
_SHEET = "Datos totales"
_DATE_COL, _GUESTS_COL, _ACCOUNTS_COL = 2, 6, 7
# N/O/S/T: bar sales, bar cost, kitchen sales, kitchen cost.
_MONEY_COLS = {"bar_sales": 14, "bar_cost": 15, "kitchen_sales": 19, "kitchen_cost": 20}


def read_covers_from_workbook(path: Path) -> list[DayCovers]:
    """Read turnout straight from the owner's master workbook.

    The bill-level export only reaches back as far as the POS keeps it, while
    the workbook carries the whole history by hand -- four years of it. Rows
    without a day's turnout are skipped rather than stored as zero, so an empty
    cell stays unknown instead of becoming "nobody came".
    """
    workbook = load_workbook(io.BytesIO(Path(path).read_bytes()), data_only=True)
    sheet = next(
        (workbook[n] for n in workbook.sheetnames if n.strip() == _SHEET), None
    )
    if sheet is None:
        raise TicketExportError(f'No "{_SHEET}" sheet in {Path(path).name}')

    days: list[DayCovers] = []
    for row in range(2, sheet.max_row + 1):
        when = sheet.cell(row=row, column=_DATE_COL).value
        guests = sheet.cell(row=row, column=_GUESTS_COL).value
        if not isinstance(when, datetime.datetime) or not isinstance(guests, (int, float)):
            continue
        if guests <= 0:
            continue
        accounts = sheet.cell(row=row, column=_ACCOUNTS_COL).value
        money = {}
        for field, col in _MONEY_COLS.items():
            value = sheet.cell(row=row, column=col).value
            money[field] = (
                Decimal(str(value)) if isinstance(value, (int, float)) else None
            )
        days.append(
            DayCovers(
                date=when.date(),
                guests=int(guests),
                accounts=int(accounts) if isinstance(accounts, (int, float)) else 0,
                **money,
            )
        )
    return days


def read_daily_covers(path: Path) -> list[DayCovers]:
    """Group the export's bills into operating days, newest rule applied.

    The file arrives named ``.XLS`` but is really an ``.xlsx``, so it is read
    from its bytes: openpyxl refuses by extension, not by content.
    """
    workbook = load_workbook(io.BytesIO(Path(path).read_bytes()), data_only=True)
    sheet = workbook[workbook.sheetnames[0]]

    header_row = closed_col = guests_col = None
    for row in range(1, min(sheet.max_row, 30) + 1):
        for col in range(1, min(sheet.max_column, 30) + 1):
            label = str(sheet.cell(row=row, column=col).value or "")
            if label.replace(" ", "").upper() == _HEADER:
                header_row, guests_col = row, col
                closed_col = col - 1  # CIERRE sits immediately before it
                break
        if header_row:
            break
    if header_row is None:
        raise TicketExportError(
            "No 'NÚMERODEPERSONAS' column found -- is this the sales report export?"
        )

    guests: dict[datetime.date, int] = defaultdict(int)
    accounts: dict[datetime.date, int] = defaultdict(int)
    for row in range(header_row + 1, sheet.max_row + 1):
        closed_at = parse_closed_at(sheet.cell(row=row, column=closed_col).value)
        if closed_at is None:
            continue
        day = operating_day(closed_at)
        guests[day] += int(sheet.cell(row=row, column=guests_col).value or 0)
        accounts[day] += 1

    return [
        DayCovers(date=day, guests=guests[day], accounts=accounts[day])
        for day in sorted(guests)
    ]
