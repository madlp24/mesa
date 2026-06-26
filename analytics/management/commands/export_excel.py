"""Export real data to Excel from the database.

``matrix`` -> the "Productos vendidos" units-per-month matrix.
``report`` -> the analysis report (per product / per category + rankings).
"""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from analytics.exports import (
    build_analysis_workbook,
    build_productos_vendidos_workbook,
)
from tenants.utils import resolve_restaurant


class Command(BaseCommand):
    help = "Export real data to an .xlsx file (Productos-Vendidos matrix or analysis report)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            choices=["matrix", "report"],
            default="matrix",
            help="matrix = Productos-Vendidos units matrix; report = analysis report.",
        )
        parser.add_argument("--output", required=True, help="Destination .xlsx path.")
        parser.add_argument(
            "--restaurant", help="Restaurant slug (optional if there is only one)."
        )
        parser.add_argument("--start", help="Report only: window start (YYYY-MM-DD).")
        parser.add_argument("--end", help="Report only: window end (YYYY-MM-DD).")

    def handle(self, *args, **options):
        output = Path(options["output"])
        if output.suffix.lower() != ".xlsx":
            raise CommandError("--output must end in .xlsx")

        restaurant = resolve_restaurant(options.get("restaurant"))
        if options["type"] == "matrix":
            workbook = build_productos_vendidos_workbook(restaurant)
        else:
            start = parse_date(options["start"]) if options.get("start") else None
            end = parse_date(options["end"]) if options.get("end") else None
            workbook = build_analysis_workbook(restaurant, start, end)

        output.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(output)
        self.stdout.write(self.style.SUCCESS(f"Wrote {options['type']} export to {output}"))
