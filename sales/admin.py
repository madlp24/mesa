from django.contrib import admin

from .models import Sale, SaleItem


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ("external_id", "occurred_at", "total")
    date_hierarchy = "occurred_at"
    search_fields = ("external_id",)
    inlines = [SaleItemInline]
