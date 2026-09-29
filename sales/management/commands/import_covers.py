"""Import how many people the restaurant served each day, from the POS export."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from sales.importers.tickets import (
    TicketExportError,
    read_covers_from_workbook,
    read_daily_covers,
)
from sales.models import DailyCovers
from tenants.utils import resolve_restaurant


class Command(BaseCommand):
    help = (
        "Read the bill-level sales export and store guests and accounts per "
        "operating day (the POS day runs 06:00 to 06:00)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="The sales report export")
        parser.add_argument("--restaurant", help="Restaurant slug")
        parser.add_argument(
            "--workbook",
            action="store_true",
            help="Read --file as the master workbook's 'Datos totales' sheet "
                 "instead of the bill-level export (brings in the history).",
        )

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"File not found: {path}")
        restaurant = resolve_restaurant(options.get("restaurant"))

        read = read_covers_from_workbook if options["workbook"] else read_daily_covers
        try:
            days = read(path)
        except TicketExportError as exc:
            raise CommandError(str(exc)) from exc

        created = updated = 0
        for day in days:
            _, was_created = DailyCovers.objects.update_or_create(
                restaurant=restaurant,
                date=day.date,
                defaults={"guests": day.guests, "accounts": day.accounts},
            )
            created += was_created
            updated += not was_created

        guests = sum(d.guests for d in days)
        accounts = sum(d.accounts for d in days)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(days)} day(s) for {restaurant.name}: {created} added, "
                f"{updated} updated. {guests} people over {accounts} bills "
                f"({days[0].date} to {days[-1].date})."
            )
        )
