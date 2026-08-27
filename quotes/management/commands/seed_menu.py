"""Build the quoting menu from a restaurant's own catalog.

Every active product becomes a menu item priced tax-inclusive and mapped back to
the product it came from, so quotes know their cost from the first run. Names and
descriptions are then edited in the UI: the POS calls a dish ``CROQUETAS DE LOMO
AHUMADO *4U`` and a client should not have to read that.
"""
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from catalog.models import Product
from quotes.models import TAX_RATE, Course, MenuItem
from tenants.models import Restaurant

#: Category name fragments mapped to the course they belong to. Checked in order.
COURSE_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("POSTRE", "DESSERT"), Course.DESSERTS),
    (("ENSALADA", "SALAD", "ENTRADA", "STARTER"), Course.STARTERS),
    (("CORTE", "CARNE", "FUERTE", "ESPECIAL", "STEAK", "MAIN"), Course.MAINS),
    (("ACOMPA", "ADICION", "PAN", "SIDE"), Course.SIDES),
    (("COCTEL", "VINO", "DESTILADO", "CERVEZA", "SANGRIA", "WINE", "BEER"), Course.ALCOHOL),
    (("LIMONADA", "SODA", "AGUA", "BEBIDA", "CAFE", "WATER", "SOFT"), Course.SOFT),
]

#: How many guests one unit serves, by category fragment. Everything else is 1.
SERVING_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("X BOTELLA", "BOTTLE"), "3"),
    (("ACOMPA", "ENSALADA", "SIDE", "SALAD"), "4"),
]

#: Cuts sold by the gram in the POS. Quoting 20 units of a per-gram product means
#: 20 grams of wagyu, so these become one-kilo items instead.
GRAM_MARKERS = ("* GR", "*GR", " X GR", "POR GR", "/GR")
GRAMS_PER_KILO = Decimal(1000)
GRAMS_PER_GUEST = Decimal(280)


def is_priced_by_gram(product_name: str) -> bool:
    upper = product_name.upper()
    return any(marker in upper for marker in GRAM_MARKERS)


def course_for(category_name: str) -> str:
    upper = category_name.upper()
    for fragments, course in COURSE_HINTS:
        if any(f in upper for f in fragments):
            return course
    return Course.OTHER


def servings_for(category_name: str) -> Decimal:
    upper = category_name.upper()
    for fragments, servings in SERVING_HINTS:
        if any(f in upper for f in fragments):
            return Decimal(servings)
    return Decimal(1)


def quoted_price(sale_price: Decimal) -> Decimal:
    """POS prices are net of tax; quotes show them with the tax inside."""
    gross = Decimal(sale_price) * (Decimal(1) + TAX_RATE)
    return gross.quantize(Decimal(100), rounding=ROUND_HALF_UP)


class Command(BaseCommand):
    help = "Create quoting menu items from a restaurant's catalog products."

    def add_arguments(self, parser):
        parser.add_argument("--restaurant", type=int, required=True, help="Restaurant id")
        parser.add_argument(
            "--descriptions",
            type=str,
            default="",
            help="Optional JSON file mapping product name -> {name, description}",
        )
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Refresh price and mapping on menu items that already exist",
        )

    def handle(self, *args, **options):
        try:
            restaurant = Restaurant.objects.get(pk=options["restaurant"])
        except Restaurant.DoesNotExist as exc:
            raise CommandError(f"No restaurant with id {options['restaurant']}") from exc

        overrides = self._load_overrides(options["descriptions"])
        products = Product.objects.filter(restaurant=restaurant, is_active=True).select_related(
            "category"
        )

        created = updated = skipped = 0
        for product in products:
            if product.sale_price is None or product.sale_price <= 0:
                skipped += 1
                continue

            override = overrides.get(product.name.strip().upper(), {})
            by_gram = is_priced_by_gram(product.name)

            defaults = {
                "description": override.get("description", ""),
                "course": course_for(product.category.name),
                "price": quoted_price(product.sale_price),
                "servings": servings_for(product.category.name),
                "product": product,
                "product_units": Decimal(1),
            }
            name = override.get("name") or product.name.strip().title()

            if by_gram:
                # One kilo, which is how events are quoted and how a cut is ordered.
                defaults["price"] = quoted_price(product.sale_price * GRAMS_PER_KILO)
                defaults["product_units"] = GRAMS_PER_KILO
                defaults["servings"] = (GRAMS_PER_KILO / GRAMS_PER_GUEST).quantize(Decimal("0.01"))
                name = self._kilo_name(name)

            item, was_created = MenuItem.objects.get_or_create(
                restaurant=restaurant, name=name, defaults=defaults
            )
            if was_created:
                created += 1
            elif options["update_existing"]:
                for key, value in defaults.items():
                    if key == "description" and not value:
                        continue
                    setattr(item, key, value)
                item.save()
                updated += 1

        retired = self._retire_stale_gram_items(restaurant)

        self.stdout.write(
            self.style.SUCCESS(
                f"{restaurant.name}: {created} created, {updated} updated, "
                f"{skipped} skipped (no sale price), {retired} retired"
            )
        )
        unmapped = MenuItem.objects.filter(restaurant=restaurant, product__isnull=True).count()
        if unmapped:
            self.stdout.write(f"{unmapped} menu items still have no product mapped.")

    @staticmethod
    def _retire_stale_gram_items(restaurant) -> int:
        """Deactivate per-unit items left over from before cuts became per-kilo."""
        stale = [
            item
            for item in MenuItem.objects.filter(
                restaurant=restaurant, is_active=True, product__isnull=False
            ).select_related("product")
            if is_priced_by_gram(item.product.name) and item.product_units != GRAMS_PER_KILO
        ]
        for item in stale:
            item.is_active = False
            item.save(update_fields=["is_active"])
        return len(stale)

    @staticmethod
    def _kilo_name(name: str) -> str:
        cleaned = name
        for marker in ("* Gr", "*Gr", "* GR", "*GR", " X Gr", " X GR", "Por Gr"):
            cleaned = cleaned.replace(marker, "")
        return f"{cleaned.strip(' *')} (por kg)"

    @staticmethod
    def _load_overrides(path: str) -> dict:
        if not path:
            return {}
        source = Path(path)
        if not source.exists():
            raise CommandError(f"Descriptions file not found: {path}")
        data = json.loads(source.read_text(encoding="utf-8"))
        return {key.strip().upper(): value for key, value in data.items()}
