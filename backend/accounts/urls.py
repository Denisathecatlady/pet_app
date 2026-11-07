from django.contrib.auth import views as auth_views
from django.urls import path

from . import two_factor_views, views

app_name = "accounts"

urlpatterns = [
    path("registrace/", views.register, name="register"),
    path("registrace/odeslano/", views.register_done, name="register_done"),
    path("aktivace/znovu/", views.resend_activation, name="resend_activation"),
    path(
        "aktivace/znovu/odeslano/",
        views.resend_activation_done,
        name="resend_activation_done",
    ),
    path("aktivace/<uidb64>/<token>/", views.activate, name="activate"),
    path("prihlaseni/", views.LoginView.as_view(), name="login"),
    path("odhlaseni/", auth_views.LogoutView.as_view(), name="logout"),
    path("heslo/zmena/", views.PasswordChangeView.as_view(), name="password_change"),
    path("heslo/obnova/", views.PasswordResetView.as_view(), name="password_reset"),
    path(
        "heslo/obnova/odeslano/",
        views.PasswordResetDoneView.as_view(),
        name="password_reset_done",
    ),
    path(
        "heslo/obnova/hotovo/",
        views.PasswordResetCompleteView.as_view(),
        name="password_reset_complete",
    ),
    path(
        "heslo/obnova/<uidb64>/<token>/",
        views.PasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path("profil/", views.profile, name="profile"),
    path("veterinar/", views.vet_verification_page, name="vet_verification"),
    path("export/", views.export_data, name="export"),
    path("2fa/", two_factor_views.status, name="two_factor"),
    path("2fa/nastaveni/", two_factor_views.setup, name="two_factor_setup"),
    path("2fa/overeni/", two_factor_views.verify, name="two_factor_verify"),
    path("2fa/kody/", two_factor_views.new_recovery_codes, name="two_factor_codes"),
    path("2fa/vypnout/", two_factor_views.disable, name="two_factor_disable"),
    path("smazat/", views.delete_account, name="delete"),
    path("smazano/", views.deleted, name="deleted"),
]
