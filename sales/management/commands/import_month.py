"""Import a folder of daily reports, skipping the traps real folders contain."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from sales.importers.pdf_daily import parse_daily_totals, read_period
from sales.services import run_import
from tenants.utils import resolve_restaurant


def _fullness(path: Path) -> float:
    """How much of a day a report accounts for, used to break a tie.

    Two files can carry the same date when one is a partial cut ("por una
    cuenta", "HORA EXACTA"). The complete day always totals at least as much as
    a slice of it, so the larger total is the one to keep.
    """
    totals = parse_daily_totals(path)
    if totals is None:
        return -1.0
    return float(totals.venta_bar + totals.venta_cocina)


class Command(BaseCommand):
    help = (
        "Import every daily report in a folder. Aggregates (a month printed in "
        "the daily layout) are skipped, and when a date has several files the "
        "fullest one wins."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dir", required=True, help="Folder of .pdf reports")
        parser.add_argument("--restaurant", help="Restaurant slug")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be imported without touching the database.",
        )

    def handle(self, *args, **options):
        folder = Path(options["dir"])
        if not folder.is_dir():
            raise CommandError(f"Not a folder: {folder}")
        restaurant = resolve_restaurant(options.get("restaurant"))

        chosen: dict = {}
        skipped: list[tuple[str, str]] = []
        for pdf in sorted(folder.glob("*.pdf")):
            period = read_period(pdf)
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
                continue
            # Same date twice: keep the fuller report, skip the slice.
            if _fullness(pdf) > _fullness(rival):
                chosen[day] = pdf
                skipped.append((rival.name, f"partial report for {day}"))
            else:
                skipped.append((pdf.name, f"partial report for {day}"))

        if not chosen:
            raise CommandError(f"No daily reports found in {folder}")

        self.stdout.write(
            f"{len(chosen)} day(s) to import, {len(skipped)} file(s) skipped."
        )
        for name, why in skipped:
            self.stdout.write(self.style.WARNING(f"  skipped {name}: {why}"))
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS("Dry run: nothing was imported."))
            return

        sales = items = duplicates = 0
        for day in sorted(chosen):
            pdf = chosen[day]
            batch = run_import(
                pdf, restaurant, filename=pdf.name, source="cli"
            )
            sales += batch.sales_created
            items += batch.items_created
            duplicates += batch.skipped_duplicate
        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {len(chosen)} day(s) into {restaurant.name}: "
                f"{sales} sales, {items} items, {duplicates} skipped as duplicate."
            )
        )
