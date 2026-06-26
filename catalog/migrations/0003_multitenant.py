"""Make the catalog multi-tenant.

Adds a ``restaurant`` FK to Category/Product/ProductAlias, assigns all existing
data to a default "Demo" restaurant, gives existing users a membership to it, and
swaps global uniqueness for per-restaurant uniqueness.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def assign_to_demo(apps, schema_editor):
    Restaurant = apps.get_model("tenants", "Restaurant")
    Membership = apps.get_model("tenants", "Membership")
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Category = apps.get_model("catalog", "Category")
    Product = apps.get_model("catalog", "Product")
    ProductAlias = apps.get_model("catalog", "ProductAlias")

    # Fresh database (e.g. the test DB): nothing to migrate, leave it clean.
    if not (Category.objects.exists() or Product.objects.exists() or User.objects.exists()):
        return

    demo, _ = Restaurant.objects.get_or_create(slug="demo", defaults={"name": "Demo"})
    Category.objects.filter(restaurant__isnull=True).update(restaurant=demo)
    Product.objects.filter(restaurant__isnull=True).update(restaurant=demo)
    ProductAlias.objects.filter(restaurant__isnull=True).update(restaurant=demo)
    for user in User.objects.all():
        Membership.objects.get_or_create(user=user, defaults={"restaurant": demo})


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0002_productalias"),
        ("tenants", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="restaurant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="categories",
                to="tenants.restaurant",
            ),
        ),
        migrations.AddField(
            model_name="product",
            name="restaurant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="products",
                to="tenants.restaurant",
            ),
        ),
        migrations.AddField(
            model_name="productalias",
            name="restaurant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="product_aliases",
                to="tenants.restaurant",
            ),
        ),
        migrations.AlterField(
            model_name="category",
            name="name",
            field=models.CharField(max_length=100),
        ),
        migrations.AlterField(
            model_name="category",
            name="slug",
            field=models.SlugField(),
        ),
        migrations.AlterField(
            model_name="product",
            name="sku",
            field=models.CharField(max_length=50),
        ),
        migrations.RemoveConstraint(
            model_name="productalias",
            name="unique_alias_identity",
        ),
        migrations.RunPython(assign_to_demo, noop),
        migrations.AlterField(
            model_name="category",
            name="restaurant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="categories",
                to="tenants.restaurant",
            ),
        ),
        migrations.AlterField(
            model_name="product",
            name="restaurant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="products",
                to="tenants.restaurant",
            ),
        ),
        migrations.AlterField(
            model_name="productalias",
            name="restaurant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="product_aliases",
                to="tenants.restaurant",
            ),
        ),
        migrations.AddConstraint(
            model_name="category",
            constraint=models.UniqueConstraint(
                fields=["restaurant", "name"],
                name="unique_category_name_per_restaurant",
            ),
        ),
        migrations.AddConstraint(
            model_name="category",
            constraint=models.UniqueConstraint(
                fields=["restaurant", "slug"],
                name="unique_category_slug_per_restaurant",
            ),
        ),
        migrations.AddConstraint(
            model_name="product",
            constraint=models.UniqueConstraint(
                fields=["restaurant", "sku"], name="unique_sku_per_restaurant"
            ),
        ),
        migrations.AddConstraint(
            model_name="productalias",
            constraint=models.UniqueConstraint(
                fields=["restaurant", "pos_clave", "raw_name"],
                name="unique_alias_identity_per_restaurant",
            ),
        ),
    ]
