"""Middleware of the accounts app: staff session limits and two-factor enforcement."""

from collections.abc import Callable
from typing import Final

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect, resolve_url
from django.urls import Resolver404, resolve, reverse
from django.utils.http import urlencode

from . import session_policy, two_factor

GetResponse = Callable[[HttpRequest], HttpResponse]


def _return_path(request: HttpRequest) -> str | None:
    """Return the path to come back to after signing in, only for requests that can repeat."""
    return request.get_full_path() if request.method in ("GET", "HEAD") else None


class StaffSessionPolicyMiddleware:
    """Sign out staff users who were idle too long or signed in too long ago (docs/14 §14.5).

    Applies to authenticated staff users only (``User.is_staff``); everybody else keeps the
    normal session. The user is redirected to the sign-in page, which shows why. Place after
    ``AuthenticationMiddleware`` and ``MessageMiddleware``.
    """

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = request.user
        if user.is_authenticated and user.is_staff:
            reason = session_policy.expiry_reason(request.session)
            if reason is not None:
                logout(request)
                messages.warning(request, session_policy.expiry_message(reason))
                login_url = resolve_url(settings.LOGIN_URL)
                path = _return_path(request)
                return redirect_to_login(path, login_url) if path else redirect(login_url)
            session_policy.touch(request.session)
        return self.get_response(request)


# Views reachable in every two-factor state: sign out and the legal pages.
ALWAYS_ALLOWED: Final = frozenset({"accounts:logout", "core:terms", "core:privacy"})
ENROLLMENT_VIEWS: Final = frozenset({"accounts:two_factor_setup"})
VERIFICATION_VIEWS: Final = frozenset({"accounts:two_factor_verify"})


class TwoFactorEnforcementMiddleware:
    """Send users who must set up or pass two-factor authentication to the right page.

    * No confirmed device and two-factor is mandatory for the user (staff, when
      ``settings.REQUIRE_2FA_FOR_STAFF``): every request goes to the enrolment page.
    * A confirmed device but a session that has not passed the check: every request goes
      to the verification page (any user who enrolled, staff or not).

    Exempt in both states: sign out, the legal pages and static files; in addition the
    enrolment page in the first state and the verification page in the second. Place after
    ``OTPMiddleware`` and ``StaffSessionPolicyMiddleware``.
    """

    def __init__(self, get_response: GetResponse) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        user = request.user
        if user.is_authenticated:
            state = two_factor.state_for(user)
            if state is not two_factor.State.OK and not self._exempt(request, state):
                return self._redirect(request, state)
        return self.get_response(request)

    @staticmethod
    def _exempt(request: HttpRequest, state: "two_factor.State") -> bool:
        if request.path_info.startswith(settings.STATIC_URL):
            return True
        try:
            view_name = resolve(request.path_info).view_name
        except Resolver404:
            return False
        if view_name in ALWAYS_ALLOWED:
            return True
        allowed = (
            ENROLLMENT_VIEWS
            if state is two_factor.State.ENROLLMENT_REQUIRED
            else VERIFICATION_VIEWS
        )
        return view_name in allowed

    @staticmethod
    def _redirect(request: HttpRequest, state: "two_factor.State") -> HttpResponseRedirect:
        name = (
            "accounts:two_factor_setup"
            if state is two_factor.State.ENROLLMENT_REQUIRED
            else "accounts:two_factor_verify"
        )
        target = reverse(name)
        path = _return_path(request)
        if path:
            target = f"{target}?{urlencode({'next': path})}"
        return HttpResponseRedirect(target)
