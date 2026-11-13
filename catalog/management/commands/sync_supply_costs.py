"""Pull supply costs from AutoFacturas and re-cost the products (US45).

Reads ``GET /conector/costos`` for the restaurant's company, stores each insumo
as a ``Supply``, and rebuilds ``cost_price`` for every product that has a
recipe. ``--file`` replays a saved answer instead of calling the connector,
which is how this gets exercised without a token.
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.supplies import (
    DEFAULT_BASE_URL,
    DEFAULT_DAYS,
    SupplyCostError,
    recost_products,
    sync_costs,
    sync_supplies,
)
from tenants.utils import resolve_restaurant


class Command(BaseCommand):
    help = (
        "Fetch supply costs from AutoFacturas and re-cost the products whose "
        "recipe is complete."
    )

    def add_arguments(self, parser):
        parser.add_argument("--restaurant", required=True, help="Restaurant slug")
        parser.add_argument(
            "--base-url", default=DEFAULT_BASE_URL,
            help=f"AutoFacturas base URL (default: {DEFAULT_BASE_URL})",
        )
        parser.add_argument(
            "--days", type=int, default=DEFAULT_DAYS,
            help="Window for the weighted average cost (default: 90)",
        )
        parser.add_argument(
            "--file", help="Replay a saved connector answer instead of calling it"
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would change without writing anything",
        )

    def handle(self, *args, **options):
        restaurant = resolve_restaurant(options["restaurant"])

        payload = None
        if options["file"]:
            path = Path(options["file"])
            if not path.is_file():
                raise CommandError(f"Not a file: {path}")
            try:
                payload = json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                raise CommandError(f"{path} is not JSON: {exc}") from exc

        try:
            if options["dry_run"]:
                summary = self._dry_run(restaurant, payload, options)
            else:
                summary = sync_costs(
                    restaurant,
                    base_url=options["base_url"],
                    days=options["days"],
                    payload=payload,
                )
        except SupplyCostError as exc:
            raise CommandError(str(exc)) from exc

        self._report(summary, dry_run=options["dry_run"])

    def _dry_run(self, restaurant, payload, options):
        """Run the whole thing inside a transaction and roll it back."""
        from django.db import transaction

        from catalog.supplies import fetch_costs

        if payload is None:
            payload = fetch_costs(
                restaurant.autofacturas_token,
                base_url=options["base_url"],
                days=options["days"],
            )

        class _Rollback(Exception):
            pass

        holder = {}
        try:
            with transaction.atomic():
                summary = sync_supplies(restaurant, payload)
                holder["summary"] = recost_products(restaurant, summary)
                raise _Rollback
        except _Rollback:
            pass
        return holder["summary"]

    def _report(self, summary, *, dry_run: bool):
        if summary.company:
            self.stdout.write(
                f"{summary.company} - generated {summary.generated_at or 'n/a'} - "
                f"average over {summary.days} days - "
                f"taxes are cost: {'yes' if summary.taxes_are_cost else 'no'}"
            )
        self.stdout.write(
            f"{summary.supplies_seen} supplies: {summary.created} new, "
            f"{summary.updated} updated, {summary.unchanged} unchanged"
        )
        if summary.uncosted:
            self.stdout.write(
                self.style.WARNING(
                    f"{summary.uncosted} supplies came without a cost"
                )
            )

        for name, before, after in summary.recosted[:20]:
            arrow = self.style.SUCCESS("->")
            self.stdout.write(f"  {name}: {before:,.2f} {arrow} {after:,.2f}")
        if len(summary.recosted) > 20:
            self.stdout.write(f"  ... and {len(summary.recosted) - 20} more")

        for name, missing in summary.blocked:
            self.stdout.write(
                self.style.WARNING(
                    f"  {name}: recipe not costed, missing {', '.join(missing)}"
                )
            )

        verb = "would be re-costed" if dry_run else "re-costed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(summary.recosted)} product(s) {verb}, "
                f"{len(summary.blocked)} held back"
            )
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: nothing was written."))
