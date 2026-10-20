"""Template context processors of the core app."""

from django.conf import settings
from django.http import HttpRequest


def contact(request: HttpRequest) -> dict[str, str]:
    """``contact_email``: the administrator's address (``settings.CONTACT_EMAIL``, may be empty)."""
    return {"contact_email": settings.CONTACT_EMAIL}
