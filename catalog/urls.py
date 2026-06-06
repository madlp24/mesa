from django.urls import path

from . import views

app_name = "catalog"
urlpatterns = [
    path("<int:pk>/", views.product_detail, name="product_detail"),
    path(
        "<int:pk>/sales-series/",
        views.product_sales_series,
        name="product_sales_series",
    ),
]
