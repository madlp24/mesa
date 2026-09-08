from django.urls import path

from . import views

app_name = "tenants"
urlpatterns = [
    path("", views.settings, name="settings"),
    path("invite/", views.invite, name="invite"),
    path("invitations/<int:pk>/revoke/", views.revoke_invitation, name="revoke_invitation"),
    path("members/<int:pk>/remove/", views.remove_member, name="remove_member"),
]
