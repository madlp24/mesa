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
    path("<int:pk>/pdf/", views.quote_pdf, name="quote_pdf"),
    path("<int:pk>/charges/", views.quote_add_charge, name="quote_add_charge"),
    path("<int:pk>/services/", views.quote_add_service, name="quote_add_service"),
    path("<int:pk>/dishes/", views.quote_add_dish, name="quote_add_dish"),
    path("<int:pk>/dishes/custom/", views.quote_add_custom_dish, name="quote_add_custom_dish"),
    path("<int:pk>/lines/", views.quote_update_lines, name="quote_update_lines"),
    path("<int:pk>/lines/<int:line_id>/remove/", views.quote_remove_line, name="quote_remove_line"),
]
