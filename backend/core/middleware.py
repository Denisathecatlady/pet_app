"""HTTP security headers not covered by Django 5.2 itself."""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse


class ContentSecurityPolicyMiddleware:
    """Add the ``Content-Security-Policy`` header from ``settings.CONTENT_SECURITY_POLICY``.

    A header already set by a view is left untouched. An empty setting disables it.
    Error responses under ``DEBUG`` are exempt: Django's technical error pages need
    inline CSS and JavaScript.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        policy = getattr(settings, "CONTENT_SECURITY_POLICY", "")
        if settings.DEBUG and response.status_code >= 400:
            return response
        if policy and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = policy
        return response
