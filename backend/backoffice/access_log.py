"""Writing the access log of the administration (docs/14 §14.7).

Use :class:`AccessLoggedAdminMixin` on the ``ModelAdmin`` of every model that contains personal
data. A model says so with a class attribute ``contains_personal_data = True``;
:func:`is_personal_data` also knows the history model of such a model and the models of
third-party apps listed in ``EXTERNAL_PERSONAL_DATA_MODELS``. A test walks over every
registered admin and fails when one of those models has an admin without the mixin, so a
model added later cannot be forgotten.

What is logged: the list, the record, its history, its deletion page, adding, changing and
deleting, and every custom action. What is never logged: search terms, filter values and
submitted data (the path is stored without its query string).
"""

import ipaddress
from collections.abc import Callable, Iterable
from typing import Any, Final

from django.contrib import admin
from django.db.models import Model
from django.http import HttpRequest, HttpResponse

from accounts.axes_hooks import get_client_ip

from .models import AdminAccessAction, AdminAccessLog

# Models of third-party apps that hold personal data (the sign-in records of django-axes keep
# e-mail addresses, IP addresses and browsers). They cannot carry the marker themselves.
EXTERNAL_PERSONAL_DATA_MODELS: Final = frozenset(
    {"axes.AccessAttempt", "axes.AccessLog", "axes.AccessFailureLog"}
)
PATH_MAX_LENGTH: Final = 255
_MARKS_ATTRIBUTE: Final = "_admin_access_marks"


def is_personal_data(model: type[Model]) -> bool:
    """Return whether ``model`` is flagged as containing personal data.

    True for a model with ``contains_personal_data = True``, for the history model
    (django-simple-history) of such a model and for ``EXTERNAL_PERSONAL_DATA_MODELS``.
    """
    if getattr(model, "contains_personal_data", False):
        return True
    if model._meta.label in EXTERNAL_PERSONAL_DATA_MODELS:
        return True
    tracked = getattr(model, "instance_type", None)  # set on historical models
    return bool(tracked is not None and getattr(tracked, "contains_personal_data", False))


def _valid_ip(value: str | None) -> str | None:
    try:
        return str(ipaddress.ip_address(value)) if value else None
    except ValueError:
        return None  # e.g. garbage in X-Forwarded-For: the row must still be written


def log_admin_access(
    request: HttpRequest,
    action: str,
    model: type[Model] | None = None,
    object_pks: Iterable[Any] = (),
    *,
    user: Any = None,
) -> list[AdminAccessLog]:
    """Write one access-log row per object (one row without an object when none is given).

    Inputs: the request (path without query string and client IP come from it), the action
    (``AdminAccessAction``), the model and the primary keys of the records, and the staff
    member when it is not ``request.user`` (the sign-in signal passes it). The IP address is
    found like the one of the sign-in lockout (trusted proxies, ``TRUSTED_PROXY_COUNT``).

    Output: the rows written. A database error propagates: an access that cannot be recorded
    must not go unnoticed.
    """
    staff = user if user is not None else getattr(request, "user", None)
    authenticated = staff is not None and staff.is_authenticated
    common = {
        "staff_user_id": staff.pk if authenticated else None,
        "staff_email": staff.email if authenticated else "",
        "action": action,
        "app_label": model._meta.app_label if model is not None else "",
        "model": model._meta.model_name if model is not None else "",
        "ip_address": _valid_ip(get_client_ip(request)),
        "path": request.path[:PATH_MAX_LENGTH],
    }
    keys = [str(pk)[:64] for pk in object_pks] or [""]
    rows = [AdminAccessLog(object_pk=key, **common) for key in keys]
    return AdminAccessLog.objects.bulk_create(rows)


def log_command_access(
    command: str, action: str, model: type[Model], object_pks: Iterable[Any]
) -> list[AdminAccessLog]:
    """Record an access made from the command line (``manage.py``), where there is no request.

    The staff member is not known (shell access to the server is the authority), so the row
    names the command instead of an e-mail address and has no IP address.
    """
    rows = [
        AdminAccessLog(
            staff_email=f"manage.py {command}",
            action=action,
            app_label=model._meta.app_label,
            model=model._meta.model_name,
            object_pk=str(pk)[:64],
            path=f"manage.py {command}",
        )
        for pk in object_pks
    ]
    return AdminAccessLog.objects.bulk_create(rows)


def access_logged_action(action: str = AdminAccessAction.CHANGE) -> Callable[[Callable], Callable]:
    """Mark an admin action function with the access-log action it performs.

    ``@access_logged_action(AdminAccessAction.EXPORT)`` above an action that exports data. An
    action that does not call ``record_access`` itself is logged afterwards by the mixin, once
    per selected record, with this action (default ``CHANGE``).
    """

    def decorate(function: Callable) -> Callable:
        function.access_action = action  # type: ignore[attr-defined]
        return function

    return decorate


class AccessLoggedAdminMixin:
    """Record every access to personal data through this admin in ``AdminAccessLog``.

    Put it first in the bases: ``class UserAdmin(AccessLoggedAdminMixin, DjangoUserAdmin)``.
    Rows are written after the page was rendered or the change was saved, never for a
    refused request. ``access_delete_action`` is the action recorded for deletions (axes
    attempts record ``UNLOCK``, deleting them unlocks the account).
    """

    access_delete_action: str = AdminAccessAction.DELETE

    def record_access(
        self,
        request: HttpRequest,
        action: str,
        objs: Iterable[Model] = (),
        *,
        object_pks: Iterable[Any] | None = None,
    ) -> None:
        """Log one access of ``action`` to the given records (or pks) of this admin's model."""
        pks = list(object_pks) if object_pks is not None else [obj.pk for obj in objs]
        log_admin_access(request, action, self.model, pks)  # type: ignore[attr-defined]
        setattr(request, _MARKS_ATTRIBUTE, getattr(request, _MARKS_ATTRIBUTE, 0) + 1)

    # --- Views -----------------------------------------------------------------------------

    def changelist_view(self, request: HttpRequest, extra_context: Any = None) -> HttpResponse:
        response = super().changelist_view(request, extra_context)  # type: ignore[misc]
        # Only a list that was shown: a POST is an action (logged by the action wrapper) and
        # a redirect shows nothing.
        if request.method == "GET" and response.status_code == 200:
            self.record_access(request, AdminAccessAction.VIEW_LIST)
        return response

    def change_view(
        self, request: HttpRequest, object_id: str, form_url: str = "", extra_context: Any = None
    ) -> HttpResponse:
        response = super().change_view(request, object_id, form_url, extra_context)  # type: ignore[misc]
        # A rendered form (also a form shown again with errors) shows the record; a saved
        # change redirects and is logged by log_change, a missing record redirects too.
        if response.status_code == 200:
            self.record_access(request, AdminAccessAction.VIEW_OBJECT, object_pks=[object_id])
        return response

    def history_view(
        self, request: HttpRequest, object_id: str, extra_context: Any = None
    ) -> HttpResponse:
        response = super().history_view(request, object_id, extra_context)  # type: ignore[misc]
        if response.status_code == 200:
            self.record_access(request, AdminAccessAction.VIEW_OBJECT, object_pks=[object_id])
        return response

    def history_form_view(
        self, request: HttpRequest, object_id: str, version_id: str, extra_context: Any = None
    ) -> HttpResponse:
        """An old version of a record (django-simple-history) shows the record's data too."""
        response = super().history_form_view(  # type: ignore[misc]
            request, object_id, version_id, extra_context
        )
        if response.status_code == 200:
            self.record_access(request, AdminAccessAction.VIEW_OBJECT, object_pks=[object_id])
        return response

    def delete_view(
        self, request: HttpRequest, object_id: str, extra_context: Any = None
    ) -> HttpResponse:
        response = super().delete_view(request, object_id, extra_context)  # type: ignore[misc]
        if request.method == "GET" and response.status_code == 200:
            # The confirmation page lists the record and what depends on it.
            self.record_access(request, AdminAccessAction.VIEW_OBJECT, object_pks=[object_id])
        return response

    def autocomplete_view(self, request: HttpRequest) -> HttpResponse:
        response = super().autocomplete_view(request)  # type: ignore[misc]
        if response.status_code == 200:
            self.record_access(request, AdminAccessAction.VIEW_LIST)
        return response

    # --- Writes: the hooks Django calls exactly when a record was added, changed, deleted --

    def log_addition(self, request: HttpRequest, obj: Model, message: Any) -> Any:
        entry = super().log_addition(request, obj, message)  # type: ignore[misc]
        self.record_access(request, AdminAccessAction.ADD, [obj])
        return entry

    def log_change(self, request: HttpRequest, obj: Model, message: Any) -> Any:
        entry = super().log_change(request, obj, message)  # type: ignore[misc]
        self.record_access(request, AdminAccessAction.CHANGE, [obj])
        return entry

    def log_deletions(self, request: HttpRequest, queryset: Any) -> Any:
        # Called before the objects are deleted, so their keys can still be read.
        objs = list(queryset)
        entries = super().log_deletions(request, objs)  # type: ignore[misc]
        self.record_access(request, self.access_delete_action, objs)
        return entries

    # --- Custom actions --------------------------------------------------------------------

    def get_actions(self, request: HttpRequest) -> dict[str, Any]:
        """Wrap every action so that it always leaves a row in the access log.

        ``delete_selected`` is not wrapped (``log_deletions`` records the deletion, and its
        confirmation page deletes nothing). For any other action, when it wrote no row itself,
        one row per selected record is written afterwards with the action marked by
        :func:`access_logged_action` (default ``CHANGE``).
        """
        actions = super().get_actions(request)  # type: ignore[misc]
        wrapped = {}
        for name, (function, action_name, description) in actions.items():
            if name == "delete_selected":
                wrapped[name] = (function, action_name, description)
            else:
                wrapped[name] = (self._logged(function), action_name, description)
        return wrapped

    def _logged(self, function: Callable) -> Callable:
        action = getattr(function, "access_action", AdminAccessAction.CHANGE)

        def run(modeladmin: Any, request: HttpRequest, queryset: Any) -> Any:
            marks = getattr(request, _MARKS_ATTRIBUTE, 0)
            pks = list(queryset.values_list("pk", flat=True))
            response = function(modeladmin, request, queryset)
            if getattr(request, _MARKS_ATTRIBUTE, 0) == marks:
                self.record_access(request, action, object_pks=pks)
            return response

        run.__name__ = getattr(function, "__name__", "action")
        run.__doc__ = function.__doc__
        for attribute in ("short_description", "allowed_permissions"):
            if hasattr(function, attribute):
                setattr(run, attribute, getattr(function, attribute))
        return run


def admin_mixin_missing() -> list[str]:
    """Return the labels of registered models with personal data whose admin lacks the mixin.

    Empty when the rule holds. Used by the test that guards the rule (and usable in a check).
    """
    missing = []
    for model, model_admin in admin.site._registry.items():
        if is_personal_data(model) and not isinstance(model_admin, AccessLoggedAdminMixin):
            missing.append(model._meta.label)
    return sorted(missing)
