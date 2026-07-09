from django.urls import path

from . import views

app_name = "pages"
urlpatterns = [
    path("", views.landing, name="landing"),
    path("help/", views.help_page, name="help"),
]
