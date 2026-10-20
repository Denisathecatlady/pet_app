"""HTTP security headers not covered by Django 5.2 itself."""

from collections.abc import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.cache import add_never_cache_headers


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


class NoStoreForSignedInUsersMiddleware:
    """Forbid caching of every page served to a signed-in user.

    Pages of signed-in users show personal data and animal health records. Without
    ``Cache-Control: private, no-store`` a browser may keep them and show them from
    history or the back button after logout on a shared computer. A ``Cache-Control``
    header already set by a view is left untouched. Place after
    ``AuthenticationMiddleware``.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not response.has_header("Cache-Control"):
            add_never_cache_headers(response)
        return response
