"""Admin for the e-mail based user."""

from django.contrib import admin
from django.contrib.auth import forms as auth_forms
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import User


class AdminUserCreationForm(auth_forms.AdminUserCreationForm):
    class Meta(auth_forms.AdminUserCreationForm.Meta):
        model = User
        fields = ("email",)
        field_classes: dict = {}


class AdminUserChangeForm(auth_forms.UserChangeForm):
    class Meta(auth_forms.UserChangeForm.Meta):
        model = User
        fields = "__all__"
        field_classes: dict = {}


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Osobní údaje", {"fields": ("first_name", "last_name")}),
        (
            "Oprávnění a role",
            {
                "fields": (
                    "is_active",
                    "activation_pending",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Důležitá data", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "usable_password", "password1", "password2"),
            },
        ),
    )
    readonly_fields = ("activation_pending", "last_login", "date_joined")
    list_display = ("email", "first_name", "last_name", "is_active", "is_staff", "date_joined")
    list_filter = ("is_active", "activation_pending", "is_staff", "is_superuser", "groups")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
