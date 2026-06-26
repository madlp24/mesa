from datetime import datetime, timezone
from decimal import Decimal

import pytest

from catalog.models import Category, Product
from sales.models import Sale, SaleItem


@pytest.fixture
def sale_item(restaurant):
    category = Category.objects.create(restaurant=restaurant, name="Mains")
    product = Product.objects.create(
        restaurant=restaurant,
        name="Burger",
        sku="BUR-01",
        category=category,
        cost_price=Decimal("4.00"),
        sale_price=Decimal("10.00"),
    )
    sale = Sale.objects.create(
        restaurant=restaurant,
        external_id="2026-01-10:BUR-01",
        occurred_at=datetime(2026, 1, 10, 12, 0, tzinfo=timezone.utc),
        total=Decimal("30.00"),
    )
    return SaleItem.objects.create(
        sale=sale,
        product=product,
        quantity=3,
        unit_price=Decimal("10.00"),
        unit_cost=Decimal("4.00"),
    )


@pytest.mark.django_db
def test_line_revenue_is_price_times_quantity(sale_item):
    assert sale_item.line_revenue == Decimal("30.00")


@pytest.mark.django_db
def test_line_cost_is_unit_cost_times_quantity(sale_item):
    assert sale_item.line_cost == Decimal("12.00")


@pytest.mark.django_db
def test_line_margin_is_revenue_minus_cost(sale_item):
    assert sale_item.line_margin == Decimal("18.00")


@pytest.mark.django_db
def test_sale_str_includes_external_id(sale_item):
    assert "2026-01-10:BUR-01" in str(sale_item.sale)


@pytest.mark.django_db
def test_sale_item_str_shows_quantity_and_product(sale_item):
    assert str(sale_item) == "3 x Burger"
