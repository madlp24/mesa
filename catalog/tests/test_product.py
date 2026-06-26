from decimal import Decimal

import pytest
from django.db.models import ProtectedError

from catalog.models import Category, Product


@pytest.fixture
def category(restaurant):
    return Category.objects.create(restaurant=restaurant, name="Mains")


@pytest.mark.django_db
def test_margin_amount_is_sale_minus_cost(category):
    product = Product.objects.create(
        restaurant=category.restaurant,
        name="Burger",
        sku="BUR-01",
        category=category,
        cost_price=Decimal("4.00"),
        sale_price=Decimal("10.00"),
    )

    assert product.margin_amount == Decimal("6.00")


@pytest.mark.django_db
def test_margin_pct_is_margin_over_sale_price(category):
    product = Product.objects.create(
        restaurant=category.restaurant,
        name="Burger",
        sku="BUR-02",
        category=category,
        cost_price=Decimal("4.00"),
        sale_price=Decimal("10.00"),
    )

    assert product.margin_pct == Decimal("60")


@pytest.mark.django_db
def test_margin_pct_returns_zero_when_sale_price_is_zero(category):
    product = Product.objects.create(
        restaurant=category.restaurant,
        name="Freebie",
        sku="FRE-01",
        category=category,
        cost_price=Decimal("4.00"),
        sale_price=Decimal("0.00"),
    )

    assert product.margin_pct == 0


@pytest.mark.django_db
def test_category_with_products_cannot_be_deleted(category):
    Product.objects.create(
        restaurant=category.restaurant,
        name="Burger",
        sku="BUR-03",
        category=category,
        cost_price=Decimal("4.00"),
        sale_price=Decimal("10.00"),
    )

    with pytest.raises(ProtectedError):
        category.delete()


@pytest.mark.django_db
def test_str_returns_name(category):
    product = Product.objects.create(
        restaurant=category.restaurant,
        name="Burger",
        sku="BUR-04",
        category=category,
        cost_price=Decimal("4.00"),
        sale_price=Decimal("10.00"),
    )

    assert str(product) == "Burger"
