"""Top-level URL configuration for the Mesa project."""
from django.contrib import admin
from django.urls import include, path

from tenants import views as tenant_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("accounts/", include("allauth.urls")),
    path("products/", include("catalog.urls")),
    path("upload/", include("sales.urls")),
    path("settings/", include("tenants.urls")),
    path("join/<str:token>/", tenant_views.accept_invitation, name="accept_invitation"),
    path("quotes/", include("quotes.urls")),
    path("", include("pages.urls")),
    path("", include("analytics.urls")),
]
