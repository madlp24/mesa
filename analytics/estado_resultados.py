"""Read the accountant's "ESTADO DE RESULTADOS" PDF and map it onto the owner's
``Estados de Resultados`` sheet (US43).

The statement (UNO 8.5, level 08) prints PUC accounts down the page and up to
four monthly columns across it, one column per month. Two things make it awkward
to read:

* The money columns are right-aligned and a row prints only the months it has
  movement in, so ``510506 SUELDOS 3,501,810.00 3,501,810.00`` may well be
  March and June. Amounts are therefore assigned to a month by their **x
  position**, not by their order on the line.
* Subtotal lines are drawn in bold by overprinting the text twice with a small
  offset, so every glyph comes out duplicated (``11,,000000``). Taking every
  other character restores the value; these lines are what we reconcile against.

The sheet is deliberately *not* a copy of the statement: several accounts land on
one line (``APORTES SOCIALES`` gathers the four aportes plus gastos medicos,
``OTROS`` gathers what is left of DIVERSOS) and the totals are the workbook's own
formulas. :data:`ROW_ACCOUNTS` is that correspondence, and
:func:`reconcile` proves it loses nothing by rebuilding the statement's own
printed subtotals from the mapped rows.

Income is printed as a credit (``...CR``); it is stored negative here and
flipped back for the rows the sheet keeps positive (see :data:`CREDIT_ROWS`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pdfplumber

SHEET = "Estados de Resultados"

# Right edge of each monthly money column, in PDF points. The trailing "CR" of a
# credit pushes the edge ~9pt further right, hence the slack.
_COLUMN_EDGES = (310, 406, 502, 598)

_MONEY = re.compile(r"^-?[\d,]+\.\d{2}(CR)?$")
_ACCOUNT = re.compile(r"^\d{2,10}$")
_PERIOD = re.compile(r"NETOS DESDE (\d{4})/(\d{2})")

# Sheet row -> the statement accounts that feed it. A short code stands for
# every account under it ("5105" is the whole GASTOS DE PERSONAL group).
ROW_ACCOUNTS: dict[int, tuple[str, ...]] = {
    3: ("41401501",),    # VENTAS / COMIDA
    4: ("41401595",),    # VENTAS / BEBIDAS
    5: ("417535",),      # NOTAS CREDITO (devoluciones en venta)
    6: ("417536",),      # DESCUENTOS (cortesias y descuentos)
    10: ("61401501",),   # COSTO DE VENTA / ALIMENTOS
    11: ("61401502",),   # COSTO DE VENTA / BEBIDAS
    12: ("6",),          # TOTAL COSTO DE VENTAS: the statement's COSTOS total,
                         # which also carries bajas, desperdicios y traspasos.
    14: ("42",),         # INGRESOS NO OPERACIONALES
    # --- gasto administrativo (grupo 51) ---
    19: ("5105",),       # SALARIO ADMINISTRATIVO
    20: ("5115",),       # IMPUESTOS
    21: ("5140",),       # GASTOS LEGALES
    22: ("5145",),       # MANTENIMIENTO Y REPARACION
    23: ("5160",),       # DEPRECIACIONES
    24: ("5165",),       # AMORTIZACIONES
    25: ("5195",),       # DIVERSOS
    # --- gasto de venta, personal (grupo 5205) ---
    29: ("520506",),     # SUELDOS
    30: ("520515",),     # HORAS EXTRAS Y RECARGOS
    31: ("520548",),     # BONIFICACIONES
    32: ("520524",),     # INCAPACIDADES
    33: ("520527",),     # AUX. TRANSPORTE
    34: ("520530",),     # CESANTIAS
    35: ("520533",),     # INTERESES CESANTIAS
    36: ("520536",),     # PRIMA DE SERVICIOS
    37: ("520539",),     # VACACIONES
    38: ("520545",),     # AUXILIOS
    39: ("520551",),     # DOTACION Y SUMINISTRO
    40: ("520560",),     # INDEMNIZACIONES LABORALES
    41: ("520563",),     # CAPACITACIONES AL PERSONAL
    42: ("520568", "520569", "520570", "520572", "520584"),  # APORTES SOCIALES
    # --- gasto de venta, resto ---
    45: ("5215",),       # IMPUESTOS
    46: ("5220",),       # ARRENDAMIENTOS
    47: ("5225",),       # CONTRIBUCIONES
    48: ("5210",),       # HONORARIOS
    49: ("5230",),       # SEGUROS
    50: ("523506",),     # VIGILANCIA
    51: ("523507",),     # LAVANDERIA
    52: ("523508",),     # VALET PARKING
    53: ("523510",),     # TEMPORALES
    54: ("523511",),     # TEMPORALES NO DEDUCIBLES
    55: ("523520",),     # PROCESAMIENTO ELECTRONICO
    56: ("523525",),     # ACUEDUCTO Y ALCANTARILLADO
    57: ("523530",),     # ENERGIA ELECTRICA
    58: ("523535",),     # TELEFONO
    59: ("523536",),     # INTERNET
    60: ("523550",),     # TRANSPORTE
    61: ("523555",),     # GAS
    62: ("523560",),     # PUBLICIDAD Y PROPAGANDA
    63: ("523595",),     # Otros (servicios)
    65: ("5245",),       # MANTENIMIENTO Y REPARACIONES
    66: ("5260",),       # DEPRECIACIONES
    67: ("5265",),       # AMORTIZACIONES
    68: ("529525",),     # ELEMENTOS DE ASEO
    69: ("529530",),     # PAPELERIA
    70: ("529535",),     # COMBUSTIBLES
    71: ("529545",),     # TAXIS Y BUSES
    72: ("529546",),     # ENVASES Y EMPAQUES
    73: ("529547",),     # COMIDA EMPLEADOS
    74: ("529551",),     # MATERIA PRIMA PARA PRUEBAS
    75: ("529552",),     # SUMINISTROS, SERVILLETAS
    76: ("529554",),     # DECORACION, FLORES, VELAS
    77: ("529553",),     # REPOSICION DE MENAJE
    78: ("529557",),     # CAMBIO SENCILLO
    79: ("529556",),     # PAN CORTESIA
    80: ("529558", "529595", "529596"),  # OTROS (diversos)
    # --- no operacionales (grupo 53) ---
    86: ("5305",),       # FINANCIEROS
    87: ("5315", "5395"),  # GASTOS DIVERSOS
}

# Rows the workbook computes itself; the updater replicates their formulas
# instead of writing a number.
FORMULA_ROWS = frozenset({7, 13, 16, 27, 43, 64, 81, 83, 89, 92, 94, 96})

# Rows the sheet keeps positive although the statement prints them as credits.
CREDIT_ROWS = frozenset({3, 4, 14})

# The workbook's subtotals, as {row: (label, rows it adds up)}. Each one must
# match the statement's own printed subtotal for the same set of accounts.
_SUBTOTALS: dict[int, tuple[str, tuple[int, ...]]] = {
    27: ("TOTAL GASTO ADMINISTRATIVO", tuple(range(19, 26))),
    43: ("SALARIOS", tuple(range(29, 43))),
    64: ("SERVICIOS", tuple(range(50, 64))),
    81: ("GASTOS DIVERSOS", tuple(range(68, 81))),
    89: ("GASTOS NO OPERACIONALES", (86, 87)),
}


class StatementError(Exception):
    """The statement cannot be read, or it does not add up to its own totals."""


@dataclass
class Statement:
    """One statement PDF: the months it covers and every account's amounts."""

    months: list[str] = field(default_factory=list)
    amounts: dict[tuple[str, str], Decimal] = field(default_factory=dict)
    descriptions: dict[str, str] = field(default_factory=dict)
    subtotals: dict[tuple[str, str], Decimal] = field(default_factory=dict)

    @property
    def leaf_accounts(self) -> set[str]:
        """Accounts with no children: the group lines carry no amounts."""
        return {
            a for a in self.descriptions
            if not any(b != a and b.startswith(a) for b in self.descriptions)
        }

    def row_value(self, row: int, month: str) -> Decimal:
        """What row ``row`` of the sheet is worth in ``month``."""
        codes = ROW_ACCOUNTS[row]
        total = sum(
            (
                self.amounts.get((account, month), Decimal(0))
                for account in self.leaf_accounts
                if account.startswith(codes)
            ),
            Decimal(0),
        )
        return -total if row in CREDIT_ROWS else total

    def tracked(self, row: int) -> bool:
        """Whether the accountant books anything at all on this row's accounts."""
        return any(a.startswith(ROW_ACCOUNTS[row]) for a in self.leaf_accounts)


def _undouble(text: str) -> str:
    """Undo the overprint that makes bold text come out with doubled glyphs."""
    return text[::2] if len(text) > 1 and text[::2] == text[1::2] else text


def _column_of(x1: float) -> int | None:
    for index, edge in enumerate(_COLUMN_EDGES):
        if x1 <= edge:
            return index
    return None


def _lines(page) -> list[list[dict]]:
    """The page's words grouped into lines, each sorted left to right."""
    grouped: dict[int, list[dict]] = {}
    for word in page.extract_words():
        grouped.setdefault(round(word["top"]), []).append(word)
    return [sorted(grouped[top], key=lambda w: w["x0"]) for top in sorted(grouped)]


def _amount(text: str) -> Decimal:
    credit = text.endswith("CR")
    value = Decimal(text.removesuffix("CR").replace(",", ""))
    return -value if credit else value


def read_statement(path: Path) -> Statement:
    """Parse one "ESTADO DE RESULTADOS" PDF."""
    statement = Statement()
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for words in _lines(page):
                text = " ".join(_undouble(w["text"]) for w in words)
                if not statement.months:
                    statement.months = [
                        f"{year}-{month}" for year, month in _PERIOD.findall(text)
                    ]
                if not statement.months:
                    continue
                _read_line(statement, words)

    if not statement.months:
        raise StatementError(f"{path.name}: no 'NETOS DESDE YYYY/MM' header found")
    if not statement.amounts:
        raise StatementError(f"{path.name}: no account lines found")
    return statement


def _read_line(statement: Statement, words: list[dict]) -> None:
    """Record one line's amounts, whether it is an account or a subtotal."""
    head = _undouble(words[0]["text"])
    is_subtotal = head.startswith("*")
    if not is_subtotal and not _ACCOUNT.match(head):
        return

    label_parts: list[str] = []
    found: list[tuple[int, Decimal]] = []
    for word in words[1:]:
        plain = _undouble(word["text"])
        if _MONEY.match(plain):
            column = _column_of(word["x1"])
            if column is not None and column < len(statement.months):
                found.append((column, _amount(plain)))
        elif not found:
            label_parts.append(plain)

    if is_subtotal:
        key = f"{head} {' '.join(label_parts)}"
        target = statement.subtotals
    else:
        key = head
        statement.descriptions.setdefault(head, " ".join(label_parts))
        target = statement.amounts
    for column, amount in found:
        target[(key, statement.months[column])] = amount


def merge(statements: list[Statement]) -> Statement:
    """Join several statement files into one, months in order."""
    merged = Statement()
    for statement in statements:
        for month in statement.months:
            if month not in merged.months:
                merged.months.append(month)
        merged.amounts.update(statement.amounts)
        merged.descriptions.update(statement.descriptions)
        merged.subtotals.update(statement.subtotals)
    merged.months.sort()
    return merged


def unmapped_accounts(statement: Statement) -> list[tuple[str, str, Decimal]]:
    """Accounts with movement that no sheet row claims -- money we would drop.

    Group 6 is excluded: row 12 takes the whole COSTOS total, so its individual
    accounts are deliberately not mapped one by one.
    """
    claimed = {
        account
        for row, codes in ROW_ACCOUNTS.items()
        if row != 12
        for account in statement.leaf_accounts
        if account.startswith(codes)
    }
    orphans = []
    for account in sorted(statement.leaf_accounts - claimed):
        if account.startswith("6"):
            continue
        total = sum(
            (statement.amounts.get((account, m), Decimal(0)) for m in statement.months),
            Decimal(0),
        )
        if total:
            orphans.append((account, statement.descriptions[account], total))
    return orphans


def double_mapped_accounts() -> list[str]:
    """Accounts that two sheet rows both claim -- money we would count twice."""
    seen: dict[str, int] = {}
    clashes = []
    for row, codes in ROW_ACCOUNTS.items():
        if row == 12:
            continue
        for code in codes:
            for other, other_row in list(seen.items()):
                if code.startswith(other) or other.startswith(code):
                    clashes.append(f"{code} (fila {row}) vs {other} (fila {other_row})")
            seen[code] = row
    return clashes


def reconcile(statement: Statement) -> list[str]:
    """Rebuild the statement's printed subtotals from the mapped rows.

    Returns a list of human-readable mismatches; empty means the sheet's own
    formulas will reproduce the accountant's numbers exactly.
    """
    problems = [f"cuenta contada dos veces: {c}" for c in double_mapped_accounts()]
    for account, description, total in unmapped_accounts(statement):
        problems.append(
            f"cuenta sin fila en el Excel: {account} {description} ({total:,.2f})"
        )

    # Top-level totals, keyed by the statement's own labels.
    grand = {
        12: ("** COSTOS", ("6",)),
        7: ("**** OPERACIONALES", ("41",)),
    }
    for row, (label, codes) in grand.items():
        for month in statement.months:
            printed = statement.subtotals.get((label, month))
            if printed is None:
                continue
            got = sum(
                (
                    statement.amounts.get((a, month), Decimal(0))
                    for a in statement.leaf_accounts
                    if a.startswith(codes)
                ),
                Decimal(0),
            )
            if row in CREDIT_ROWS or codes == ("41",):
                got = -got
                printed = -printed
            if got != printed:
                problems.append(
                    f"{month} fila {row}: {got:,.2f} != informe {printed:,.2f}"
                )

    # "* GASTOS" must equal everything we mapped out of groups 51, 52 and 53.
    expense_rows = [
        r for r in ROW_ACCOUNTS if r >= 19 and r not in FORMULA_ROWS
    ]
    for month in statement.months:
        printed = statement.subtotals.get(("** GASTOS", month))
        if printed is None:
            continue
        got = sum((statement.row_value(r, month) for r in expense_rows), Decimal(0))
        if got != printed:
            problems.append(
                f"{month} TOTAL GASTOS: {got:,.2f} != informe {printed:,.2f}"
            )
    return problems


def subtotal_preview(statement: Statement) -> dict[int, dict[str, Decimal]]:
    """What the sheet's formula rows will come out to, for the command's report."""
    preview: dict[int, dict[str, Decimal]] = {}
    for row, (_label, members) in _SUBTOTALS.items():
        preview[row] = {
            month: sum(
                (statement.row_value(r, month) for r in members if r in ROW_ACCOUNTS),
                Decimal(0),
            )
            for month in statement.months
        }
    return preview
