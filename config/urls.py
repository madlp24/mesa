"""Top-level URL configuration for the Mesa project."""
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("accounts/", include("allauth.urls")),
    path("products/", include("catalog.urls")),
    path("upload/", include("sales.urls")),
    path("settings/", include("tenants.urls")),
    path("", include("analytics.urls")),
]
