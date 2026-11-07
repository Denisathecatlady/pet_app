"""Signal receivers of the back office."""

from typing import Any

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .access_log import log_admin_access
from .models import AdminAccessAction


@receiver(user_logged_in, dispatch_uid="backoffice_log_staff_login")
def log_staff_login(sender: Any, request: Any, user: Any, **kwargs: Any) -> None:
    """Record every sign-in of a staff user in the access log (action ``LOGIN``).

    Failed sign-ins are recorded by django-axes. The row is written at the password step;
    the second factor follows (docs/14 §14.7).
    """
    if user.is_staff and request is not None:
        log_admin_access(request, AdminAccessAction.LOGIN, user=user)
