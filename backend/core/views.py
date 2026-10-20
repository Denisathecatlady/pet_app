"""Public pages and the signed-in overview."""

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from accounts.roles import Role
from animals import services as animal_services


def home(request: HttpRequest) -> HttpResponse:
    """Landing page for anonymous visitors; signed-in users go to their overview."""
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    return render(request, "core/home.html")


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Overview: cards of own animals and, for vets, of animals shared with them."""
    user = request.user
    context = {
        "own": animal_services.summarize(animal_services.owned_animals(user)),
        "is_vet": user.has_role(Role.VET),
        "shared": animal_services.summarize(animal_services.shared_animals(user)),
    }
    return render(request, "core/dashboard.html", context)


def terms(request: HttpRequest) -> HttpResponse:
    """Terms of use (DRAFT placeholder, to be written by a lawyer)."""
    return render(request, "core/terms.html")


def privacy(request: HttpRequest) -> HttpResponse:
    """Privacy notice (DRAFT placeholder, to be written by a lawyer)."""
    context = {"pending_retention_days": settings.PENDING_ACCOUNT_RETENTION.days}
    return render(request, "core/privacy.html", context)
