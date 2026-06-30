from django.urls import path

from . import views

app_name = "sales"
urlpatterns = [
    path("", views.upload_report, name="upload"),
    path("undo/<int:pk>/", views.undo_import_view, name="undo_import"),
]
