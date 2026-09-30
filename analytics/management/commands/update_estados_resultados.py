"""Fill the 'Estados de Resultados' sheet from the accountant's statements (US43).

Each statement PDF carries up to four monthly columns; pass one --pdf per file.
The mapped rows are reconciled against the statement's own printed subtotals
before anything is written, so a layout change is caught instead of silently
producing a wrong P&L. Writes a copy; never touches the original.
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.estado_resultados import (
    StatementError,
    merge,
    read_statement,
    reconcile,
    subtotal_preview,
)
from analytics.unified_excel import UnifiedUpdateError, update_estados_resultados


class Command(BaseCommand):
    help = (
        "Fill 'Estados de Resultados' from one or more 'ESTADO DE RESULTADOS' "
        "PDFs. Writes a copy '<name> (Mesa Estados de Resultados).xlsx'."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the master .xlsx")
        parser.add_argument(
            "--pdf",
            required=True,
            action="append",
            help="A statement PDF. Repeat for several files.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Write even when the statement does not add up to its own totals.",
        )

    def handle(self, *args, **options):
        statements = []
        for raw in options["pdf"]:
            pdf = Path(raw)
            if not pdf.is_file():
                raise CommandError(f"Not a file: {pdf}")
            try:
                statements.append(read_statement(pdf))
            except StatementError as exc:
                raise CommandError(str(exc)) from exc
        statement = merge(statements)

        problems = reconcile(statement)
        for problem in problems:
            self.stdout.write(self.style.ERROR(f"  {problem}"))
        if problems and not options["force"]:
            raise CommandError(
                f"{len(problems)} descuadre(s) contra el informe; nada fue escrito. "
                "Revisa el mapeo de cuentas (ROW_ACCOUNTS) o usa --force."
            )

        try:
            summary = update_estados_resultados(Path(options["file"]), statement)
        except UnifiedUpdateError as exc:
            raise CommandError(str(exc)) from exc

        for warning in summary["warnings"]:
            self.stdout.write(self.style.WARNING(f"WARNING: {warning}"))

        preview = subtotal_preview(statement)
        for row, per_month in sorted(preview.items()):
            values = " ".join(f"{per_month[m]:>14,.0f}" for m in statement.months)
            self.stdout.write(f"  fila {row:>3}: {values}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated copy written to {summary['copy']}\n"
                f"{len(summary['written'])} month(s) added, "
                f"{len(summary['overwritten'])} overwritten, "
                f"{len(statement.leaf_accounts)} accounts read"
            )
        )
        if summary["written"]:
            self.stdout.write("Added: " + ", ".join(summary["written"]))
        if summary["overwritten"]:
            self.stdout.write("Overwritten: " + ", ".join(summary["overwritten"]))
