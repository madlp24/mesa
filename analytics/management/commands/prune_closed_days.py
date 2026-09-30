"""Drop the closed days from 'Datos totales' (US44).

The restaurant does not open on ordinary Mondays, only on holiday ones, yet the
sheet carries an empty row for each of them. This removes the empty rows for one
weekday and re-points every surviving row's formulas at its own row. Writes a
copy; never touches the original.
"""
import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from analytics.unified_excel import UnifiedUpdateError, prune_closed_days

_WEEKDAYS = {
    "lunes": 0, "martes": 1, "miercoles": 2, "jueves": 3,
    "viernes": 4, "sabado": 5, "domingo": 6,
}


class Command(BaseCommand):
    help = (
        "Delete the empty 'Datos totales' rows for a weekday the restaurant "
        "does not open. Writes a copy '<name> (Mesa sin dias cerrados).xlsx'."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Path to the master .xlsx")
        parser.add_argument(
            "--through",
            help=(
                "Last day to consider, YYYY-MM-DD. Later rows are the sheet's "
                "own calendar skeleton, not closures. Default: today."
            ),
        )
        parser.add_argument(
            "--weekday",
            default="lunes",
            help=(
                "Weekday to prune (lunes..domingo), or 'todos' to prune every "
                "empty dated row. Default: lunes."
            ),
        )

    def handle(self, *args, **options):
        raw = options["weekday"].strip().lower()
        if raw in ("todos", "all"):
            weekday = None
        elif raw in _WEEKDAYS:
            weekday = _WEEKDAYS[raw]
        else:
            raise CommandError(
                f"Unknown weekday {raw!r}; use one of "
                f"{', '.join(_WEEKDAYS)} or 'todos'."
            )

        through = None
        if options["through"]:
            try:
                through = datetime.date.fromisoformat(options["through"])
            except ValueError as exc:
                raise CommandError(f"--through must be YYYY-MM-DD: {exc}") from exc

        try:
            summary = prune_closed_days(
                Path(options["file"]), weekday=weekday, through=through
            )
        except UnifiedUpdateError as exc:
            raise CommandError(str(exc)) from exc

        for warning in summary["warnings"]:
            self.stdout.write(self.style.WARNING(f"WARNING: {warning}"))

        deleted = summary["deleted"]
        self.stdout.write(
            self.style.SUCCESS(
                f"Updated copy written to {summary['copy']}\n"
                f"{len(deleted)} empty day(s) deleted, {summary['kept']} kept "
                f"(they had movement), {summary['formulas_repaired']} formulas "
                f"re-pointed"
            )
        )
        for day in deleted[:12]:
            self.stdout.write(f"  - {day}")
        if len(deleted) > 12:
            self.stdout.write(f"  ... and {len(deleted) - 12} more")
