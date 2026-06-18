from django.urls import path

from . import views

app_name = "analytics"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path(
        "api/revenue-over-time/",
        views.revenue_over_time,
        name="revenue_over_time",
    ),
]
