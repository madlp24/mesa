"""Make sales multi-tenant: add a restaurant FK and per-restaurant external_id."""
import django.db.models.deletion
from django.db import migrations, models


def assign_to_demo(apps, schema_editor):
    Restaurant = apps.get_model("tenants", "Restaurant")
    Sale = apps.get_model("sales", "Sale")

    if not Sale.objects.exists():
        return
    demo, _ = Restaurant.objects.get_or_create(slug="demo", defaults={"name": "Demo"})
    Sale.objects.filter(restaurant__isnull=True).update(restaurant=demo)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("sales", "0001_initial"),
        ("catalog", "0003_multitenant"),
    ]

    operations = [
        migrations.AddField(
            model_name="sale",
            name="restaurant",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sales",
                to="tenants.restaurant",
            ),
        ),
        migrations.AlterField(
            model_name="sale",
            name="external_id",
            field=models.CharField(max_length=100),
        ),
        migrations.RunPython(assign_to_demo, noop),
        migrations.AlterField(
            model_name="sale",
            name="restaurant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="sales",
                to="tenants.restaurant",
            ),
        ),
        migrations.AddConstraint(
            model_name="sale",
            constraint=models.UniqueConstraint(
                fields=["restaurant", "external_id"],
                name="unique_external_id_per_restaurant",
            ),
        ),
    ]
