from django.urls import path

from . import views

app_name = "tenants"
urlpatterns = [
    path("", views.settings, name="settings"),
]
