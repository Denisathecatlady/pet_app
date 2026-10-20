from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("prehled/", views.dashboard, name="dashboard"),
    path("podminky-uziti/", views.terms, name="terms"),
    path("ochrana-osobnich-udaju/", views.privacy, name="privacy"),
]
