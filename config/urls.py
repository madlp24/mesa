"""Top-level URL configuration for the Mesa project."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("allauth.urls")),
    path("products/", include("catalog.urls")),
    path("", include("analytics.urls")),
]
