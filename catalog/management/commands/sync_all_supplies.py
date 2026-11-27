"""Sync supply costs for every restaurant that has an AutoFacturas token (US54).

Meant to run once a day from the scheduler, so supplier prices reach Mesa
without anyone pressing a button and the price history keeps every purchase.
A restaurant whose connector fails is reported and the rest carry on.
"""
from django.core.management.base import BaseCommand

from catalog.supplies import SupplyCostError, sync_costs
from tenants.models import Restaurant


class Command(BaseCommand):
    help = "Fetch AutoFacturas supply costs for every restaurant with a token."

    def handle(self, *args, **options):
        restaurants = Restaurant.objects.exclude(autofacturas_token="")
        done = failed = 0
        for restaurant in restaurants:
            try:
                summary = sync_costs(restaurant)
            except SupplyCostError as exc:
                failed += 1
                self.stderr.write(f"{restaurant.slug}: {exc}")
                continue
            done += 1
            self.stdout.write(
                f"{restaurant.slug}: {summary.supplies_seen} supplies, "
                f"{len(summary.recosted)} recipe cost(s) moved"
            )
        self.stdout.write(self.style.SUCCESS(f"{done} synced, {failed} failed"))
