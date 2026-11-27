from django.urls import path

from . import views

app_name = "alerts"
urlpatterns = [
    path("", views.report, name="report"),
    path("settings/", views.settings, name="settings"),
    path("export.xlsx", views.export_xlsx, name="export_xlsx"),
    path("export.pdf", views.export_pdf, name="export_pdf"),
]
