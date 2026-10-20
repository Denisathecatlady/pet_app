"""Views of the accounts app, mounted under ``/ucet/``."""

import json
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from . import services
from .export import build_export
from .forms import (
    AccountDeleteForm,
    ActivationForm,
    LoginForm,
    PasswordChangeForm,
    PasswordResetForm,
    ProfileForm,
    RegistrationForm,
    ResendActivationForm,
)
from .models import User

# --- Registration and activation ---------------------------------------------------------


@sensitive_post_parameters("password1", "password2")
@require_http_methods(["GET", "POST"])
def register(request: HttpRequest) -> HttpResponse:
    """Registration form. Always ends on the same "check your e-mail" page."""
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.register(form.cleaned_data["email"], form.cleaned_data["password1"], request)
        return redirect("accounts:register_done")
    return render(request, "accounts/register.html", {"form": form})


@require_GET
def register_done(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "accounts/register_done.html",
        {"valid_hours": settings.PASSWORD_RESET_TIMEOUT // 3600},
    )


@never_cache
@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
def activate(request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
    """GET shows the form, POST with the registration password activates.

    GET never activates (link prefetchers). Asking for the password means that only
    the person who chose it can activate, never a mailbox owner who did not
    register (account pre-hijacking, see ``services.register``).
    """
    user = services.user_for_activation(uidb64, token)
    if user is None:
        return render(request, "accounts/activation_invalid.html", status=400)
    form = ActivationForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        services.activate(user)
        messages.success(request, "Účet je aktivní. Nyní se můžete přihlásit.")
        return redirect("accounts:login")
    return render(request, "accounts/activate.html", {"activation_email": user.email, "form": form})


@require_http_methods(["GET", "POST"])
def resend_activation(request: HttpRequest) -> HttpResponse:
    """Ask for a new activation link. The response never reveals whether the e-mail exists."""
    form = ResendActivationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.resend_activation(form.cleaned_data["email"], request)
        return redirect("accounts:resend_activation_done")
    return render(request, "accounts/resend_activation.html", {"form": form})


@require_GET
def resend_activation_done(request: HttpRequest) -> HttpResponse:
    return render(request, "accounts/resend_activation_done.html")


# --- Login, logout, lockout --------------------------------------------------------------


class LoginView(auth_views.LoginView):
    form_class = LoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True


def lockout(
    request: HttpRequest,
    original_response: HttpResponse | None = None,
    credentials: dict | None = None,
) -> HttpResponse:
    """Response for clients locked out by django-axes (``AXES_LOCKOUT_CALLABLE``), HTTP 429."""
    cooloff: timedelta = settings.AXES_COOLOFF_TIME
    context = {
        "failure_limit": settings.AXES_FAILURE_LIMIT,
        "cooloff_minutes": int(cooloff.total_seconds() // 60),
    }
    return render(request, "accounts/lockout.html", context, status=429)


# --- Passwords ---------------------------------------------------------------------------


class PasswordChangeView(auth_views.PasswordChangeView):
    form_class = PasswordChangeForm
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def get_form_kwargs(self) -> dict[str, Any]:
        return {**super().get_form_kwargs(), "request": self.request}

    def form_valid(self, form: PasswordChangeForm) -> HttpResponse:
        response = super().form_valid(form)
        messages.success(self.request, "Heslo bylo změněno.")
        return response


class PasswordResetView(auth_views.PasswordResetView):
    form_class = PasswordResetForm
    template_name = "accounts/password_reset_form.html"
    subject_template_name = "accounts/email/password_reset_subject.txt"
    email_template_name = "accounts/email/password_reset_body.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:password_reset_complete")
    reset_url_token = "nastavit-heslo"


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


# --- Profile and GDPR --------------------------------------------------------------------


@login_required
@require_http_methods(["GET", "POST"])
def profile(request: HttpRequest) -> HttpResponse:
    """Show the account and edit first and last name. The e-mail is read-only."""
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profil byl uložen.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})


@login_required
@never_cache
@require_GET
def export_data(request: HttpRequest) -> HttpResponse:
    """Download all personal data of the signed-in user as JSON (GDPR art. 15 and 20)."""
    payload = json.dumps(
        build_export(request.user), cls=DjangoJSONEncoder, ensure_ascii=False, indent=2
    )
    filename = f"barf-nutri-export-{timezone.localdate().isoformat()}.json"
    response = HttpResponse(payload, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
def delete_account(request: HttpRequest) -> HttpResponse:
    """Delete the account after the current password is confirmed (GDPR art. 17)."""
    form = AccountDeleteForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        user = User.objects.get(pk=request.user.pk)
        logout(request)
        services.delete_account(user)
        return redirect("accounts:deleted")
    return render(request, "accounts/delete.html", {"form": form})


@require_GET
def deleted(request: HttpRequest) -> HttpResponse:
    return render(request, "accounts/deleted.html")
