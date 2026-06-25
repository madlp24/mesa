from django.urls import path

from . import views

app_name = "analytics"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("margin/", views.margin_analysis, name="margin_analysis"),
    path("pnl/", views.pnl_summary, name="pnl_summary"),
    path(
        "api/revenue-over-time/",
        views.revenue_over_time,
        name="revenue_over_time",
    ),
    path(
        "api/top-products/",
        views.top_products,
        name="top_products",
    ),
    path(
        "api/revenue-by-category/",
        views.revenue_by_category_api,
        name="revenue_by_category",
    ),
    path(
        "export/productos-vendidos.xlsx",
        views.export_productos_vendidos,
        name="export_productos_vendidos",
    ),
    path(
        "export/analisis.xlsx",
        views.export_analysis,
        name="export_analysis",
    ),
]
