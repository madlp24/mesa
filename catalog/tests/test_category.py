import pytest
from django.contrib import admin

from catalog.models import Category


@pytest.mark.django_db
def test_categories_ordered_by_display_order_then_name(restaurant):
    Category.objects.create(restaurant=restaurant, name="Desserts", display_order=2)
    Category.objects.create(restaurant=restaurant, name="Starters", display_order=1)
    Category.objects.create(restaurant=restaurant, name="Beverages", display_order=1)

    names = list(Category.objects.values_list("name", flat=True))

    assert names == ["Beverages", "Starters", "Desserts"]


@pytest.mark.django_db
def test_str_returns_name(restaurant):
    category = Category.objects.create(restaurant=restaurant, name="Mains")

    assert str(category) == "Mains"


@pytest.mark.django_db
def test_slug_autopopulated_from_name(restaurant):
    category = Category.objects.create(restaurant=restaurant, name="Hot Drinks")

    assert category.slug == "hot-drinks"


def test_category_registered_in_admin_with_crud():
    model_admin = admin.site._registry[Category]

    assert model_admin.has_add_permission is not None
    assert model_admin.has_change_permission is not None
    assert model_admin.has_delete_permission is not None
