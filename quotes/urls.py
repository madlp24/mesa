from django.urls import path

from . import views

app_name = "quotes"
urlpatterns = [
    path("", views.quote_list, name="quote_list"),
    path("new/", views.quote_create, name="quote_create"),
    path("menu/", views.menu_list, name="menu_list"),
    path("menu/<int:pk>/", views.menu_item_edit, name="menu_item_edit"),
    path("<int:pk>/", views.quote_detail, name="quote_detail"),
    path("<int:pk>/compose/", views.quote_compose, name="quote_compose"),
]
