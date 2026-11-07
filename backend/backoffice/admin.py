"""Admin of the access log: read-only and for superusers only (docs/14 §14.7)."""

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .access_log import AccessLoggedAdminMixin
from .models import AdminAccessLog


@admin.register(AdminAccessLog)
class AdminAccessLogAdmin(AccessLoggedAdminMixin, admin.ModelAdmin):
    """Who opened which record, when and from where.

    Only superusers see it, whatever permissions a group has: the staff must not be able to
    read the record of their own access (``ROLE_PERMISSIONS`` leaves it out on purpose). Rows
    cannot be added, changed or deleted here; old rows go with ``purge_admin_access_log``.
    Viewing the log is itself recorded.
    """

    list_display = ("timestamp", "staff_email", "action", "app_label", "model", "object_pk")
    list_filter = ("action", "app_label", "model")
    search_fields = ("staff_email", "object_pk", "path")
    date_hierarchy = "timestamp"
    fields = (
        "timestamp",
        "staff_email",
        "staff_user",
        "action",
        "app_label",
        "model",
        "object_pk",
        "ip_address",
        "path",
    )
    readonly_fields = fields

    def _superuser(self, request: HttpRequest) -> bool:
        return bool(request.user.is_active and request.user.is_superuser)

    def has_module_permission(self, request: HttpRequest) -> bool:
        return self._superuser(request)

    def has_view_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return self._superuser(request)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
