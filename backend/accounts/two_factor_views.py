"""Views of two-factor authentication, mounted under ``/ucet/2fa/`` (docs/14 §14.6).

Every page needs a signed-in user. ``TwoFactorEnforcementMiddleware`` decides who may reach
which page before a view runs: a user who must enrol only reaches ``setup``, a user who must
verify only reaches ``verify``; the pages that change the second factor (recovery codes,
disable, replacing the device) therefore only ever see a verified session.

Pages that take a password or a code answer a client locked out by django-axes with the lockout
page (HTTP 429), like the sign-in page. Recovery codes are shown in the response of the POST that
created them and never again; the pages are not cached (``never_cache``, and the middleware that
forbids caching for signed-in users).
"""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from . import two_factor
from .forms import DisableForm, EnrollmentForm, TotpTokenForm, VerifyForm


def safe_next(request: HttpRequest) -> str:
    """Return where to go after the check: the ``next`` parameter if it is a safe address.

    Safe means a path of this site (no other host, no other scheme: no open redirect) that is
    not one of the two-factor pages themselves (which would loop). Otherwise the overview.
    """
    target = request.POST.get("next") or request.GET.get("next") or ""
    if (
        target
        and url_has_allowed_host_and_scheme(
            target, allowed_hosts={request.get_host()}, require_https=request.is_secure()
        )
        and not target.startswith(reverse("accounts:two_factor"))
    ):
        return target
    return resolve_url(settings.LOGIN_REDIRECT_URL)


def _locked_out(request: HttpRequest) -> HttpResponse | None:
    return two_factor.lockout_response(request) if request.method == "POST" else None


@login_required
@never_cache
@require_GET
def status(request: HttpRequest) -> HttpResponse:
    """The state of two-factor authentication of the account and what can be done with it."""
    state = two_factor.status(request.user)
    return render(
        request,
        "accounts/two_factor/status.html",
        {"state": state, "can_disable": state.enrolled and not state.required},
    )


@login_required
@never_cache
@sensitive_post_parameters("token", "password")
@require_http_methods(["GET", "POST"])
def setup(request: HttpRequest) -> HttpResponse:
    """Set up an authenticator app: scan the QR code (or type the secret), confirm with a code.

    The device counts only after the code from it was entered. A user who already has a device
    replaces it (and must enter the password). The first time, the recovery codes are shown
    in the response that confirms the device.
    """
    if (locked := _locked_out(request)) is not None:
        return locked
    user = request.user
    replacing = two_factor.confirmed_device(user) is not None
    if replacing and not two_factor.is_verified(user):
        # The gate sends such a session to the verification first; this keeps a password alone
        # from swapping the second factor even if the gate were not in front of the view.
        return redirect("accounts:two_factor_verify")
    pending = two_factor.begin_enrollment(user)
    form = EnrollmentForm(request.POST or None, user=user, request=request, replacing=replacing)
    if request.method == "POST" and form.is_valid():
        two_factor.mark_verified(request, form.device)
        if two_factor.recovery_codes_left(user) > 0:
            messages.success(request, "Nová aplikace pro ověřování je nastavena.")
            return redirect(safe_next(request))
        return render(
            request,
            "accounts/two_factor/codes.html",
            {"codes": two_factor.generate_recovery_codes(user), "next": safe_next(request)},
        )
    context = {
        "form": form,
        "replacing": replacing,
        "qr": two_factor.qr_svg(pending),
        "secret": two_factor.secret_text(pending),
        "account_name": user.get_username(),
        "next": safe_next(request),
    }
    return render(request, "accounts/two_factor/setup.html", context)


@login_required
@never_cache
@sensitive_post_parameters("token")
@require_http_methods(["GET", "POST"])
def verify(request: HttpRequest) -> HttpResponse:
    """The second step of signing in: a code from the app or a recovery code.

    A failure says only that the code was not accepted, whatever the reason (wrong, used,
    throttled, malformed). A user without a device has nothing to verify here.
    """
    user = request.user
    if two_factor.is_verified(user):
        return redirect(safe_next(request))
    if two_factor.confirmed_device(user) is None:
        return redirect(
            "accounts:two_factor_setup" if two_factor.is_required(user) else "accounts:profile"
        )
    if (locked := _locked_out(request)) is not None:
        return locked
    form = VerifyForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        two_factor.mark_verified(request, form.device)
        return redirect(safe_next(request))
    return render(
        request, "accounts/two_factor/verify.html", {"form": form, "next": safe_next(request)}
    )


@login_required
@never_cache
@sensitive_post_parameters("token")
@require_http_methods(["GET", "POST"])
def new_recovery_codes(request: HttpRequest) -> HttpResponse:
    """Replace the recovery codes: needs a current code from the app; shows the new ones once."""
    user = request.user
    if two_factor.confirmed_device(user) is None:
        return redirect("accounts:two_factor")
    if (locked := _locked_out(request)) is not None:
        return locked
    form = TotpTokenForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        codes = two_factor.generate_recovery_codes(user)
        return render(
            request,
            "accounts/two_factor/codes.html",
            {"codes": codes, "next": reverse("accounts:two_factor"), "regenerated": True},
        )
    return render(request, "accounts/two_factor/new_codes.html", {"form": form})


@login_required
@never_cache
@sensitive_post_parameters("token", "password")
@require_http_methods(["GET", "POST"])
def disable(request: HttpRequest) -> HttpResponse:
    """Switch two-factor authentication off: password and a current code, optional users only.

    Raises:
        PermissionDenied: two-factor authentication is mandatory for the user (staff).
    """
    user = request.user
    if two_factor.is_required(user):
        raise PermissionDenied("Dvoufázové ověření je pro tento účet povinné.")
    if two_factor.confirmed_device(user) is None:
        return redirect("accounts:two_factor")
    if (locked := _locked_out(request)) is not None:
        return locked
    form = DisableForm(request.POST or None, user=user, request=request)
    if request.method == "POST" and form.is_valid():
        two_factor.remove_devices(user)
        messages.success(request, "Dvoufázové ověření bylo vypnuto.")
        return redirect("accounts:two_factor")
    return render(request, "accounts/two_factor/disable.html", {"form": form})
