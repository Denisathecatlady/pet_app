"""The administration site of the application (docs/14 §14.1).

``BarfAdminSite`` is the default admin site (``backoffice.admin_apps.BarfAdminConfig``). It
differs from Django's in three ways:

* access needs a staff user whose session passed the second factor (``has_permission``);
* there is no separate sign-in page: the application's own sign-in (django-axes lockout,
  password check, then the second factor) is the only way in, so the administration cannot be
  used to bypass either of them;
* the password is changed on the account page, with the same rate limiting as everywhere else.
"""

from typing import Any

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme

from accounts import two_factor


class BarfAdminSite(admin.AdminSite):
    site_header = "BARF Nutri – správa"
    site_title = "BARF Nutri – správa"
    index_title = "Správa aplikace"

    def has_permission(self, request: HttpRequest) -> bool:
        """Staff only, and only with a session that passed the second factor.

        A staff user without a confirmed device or with an unverified session is stopped
        by ``TwoFactorEnforcementMiddleware`` first; this check is the second lock on the
        same door (and fails closed when that middleware is missing).
        """
        return (
            super().has_permission(request)
            and two_factor.state_for(request.user) is two_factor.State.OK
        )

    def login(self, request: HttpRequest, extra_context: Any = None) -> HttpResponse:
        """Send visitors to the application's sign-in; signed-in users to their overview.

        A signed-in user who is not allowed in (not staff, or second factor pending) must not
        be sent back to the administration: that would loop.
        """
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        target = request.GET.get(REDIRECT_FIELD_NAME, "")
        if not url_has_allowed_host_and_scheme(
            target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        ):
            return redirect(settings.LOGIN_URL)
        return redirect_to_login(target, resolve_url(settings.LOGIN_URL))

    def password_change(
        self, request: HttpRequest, extra_context: Any = None
    ) -> HttpResponseRedirect:
        return redirect("accounts:password_change")
