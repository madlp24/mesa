from django.contrib import admin

from .models import Category, Product, ProductAlias


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "display_order")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "sku",
        "category",
        "cost_price",
        "sale_price",
        "margin_display",
        "is_active",
    )
    list_filter = ("category", "is_active")
    search_fields = ("name", "sku")

    @admin.display(description="Margin %")
    def margin_display(self, obj: Product) -> str:
        return f"{obj.margin_pct:.1f}%"


@admin.register(ProductAlias)
class ProductAliasAdmin(admin.ModelAdmin):
    list_display = ("pos_clave", "raw_name", "product", "created_at")
    search_fields = ("pos_clave", "raw_name", "normalized_name", "product__name")
    list_select_related = ("product",)
