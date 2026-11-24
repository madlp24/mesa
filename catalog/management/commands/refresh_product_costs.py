"""Bring every product's cost and price up to its newest sale (US47).

Imports keep the catalog current from now on, but the products already in the
database still carry the figures from the day each first appeared. This runs
the same refresh over the whole catalog once, and can be re-run at any time:
it only ever moves a product to its newest sale day.
"""
from django.core.management.base import BaseCommand

from catalog.pricing import refresh_product_prices
from tenants.utils import resolve_restaurant


class Command(BaseCommand):
    help = "Point each product's cost and sale price at its newest sale day."

    def add_arguments(self, parser):
        parser.add_argument("--restaurant", required=True, help="Restaurant slug")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing anything",
        )
        parser.add_argument(
            "--limit", type=int, default=30,
            help="How many changed products to list (default: 30)",
        )

    def handle(self, *args, **options):
        restaurant = resolve_restaurant(options["restaurant"])
        dry_run = options["dry_run"]
        changes = refresh_product_prices(restaurant, dry_run=dry_run)

        for change in changes[: options["limit"]]:
            parts = []
            if change.cost_moved:
                parts.append(f"cost {change.old_cost:,.2f} -> {change.new_cost:,.2f}")
            if change.price_moved:
                parts.append(
                    f"price {change.old_price:,.2f} -> {change.new_price:,.2f}"
                )
            self.stdout.write(f"  {change.name}: {'; '.join(parts)}")
        if len(changes) > options["limit"]:
            self.stdout.write(f"  ... and {len(changes) - options['limit']} more")

        costs = sum(1 for c in changes if c.cost_moved)
        prices = sum(1 for c in changes if c.price_moved)
        verb = "would change" if dry_run else "changed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(changes)} product(s) {verb}: {costs} cost(s), {prices} price(s)"
            )
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: nothing was written."))
