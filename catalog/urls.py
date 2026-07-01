from django.urls import path

from . import views

app_name = "catalog"
urlpatterns = [
    path("", views.product_list, name="product_list"),
    path("merge/", views.merge_products, name="merge_products"),
    path("alias/<int:alias_id>/", views.alias_action, name="alias_action"),
    path("<int:pk>/", views.product_detail, name="product_detail"),
    path(
        "<int:pk>/sales-series/",
        views.product_sales_series,
        name="product_sales_series",
    ),
]
