"""django-axes callables (settings AXES_USERNAME_CALLABLE and AXES_CLIENT_IP_CALLABLE)."""

from django.conf import settings
from django.http import HttpRequest

from .models import UserManager


def get_username(request: HttpRequest | None, credentials: dict | None = None) -> str | None:
    """Return the normalised e-mail of a login attempt.

    Normalising means ``Jana@x.cz`` and ``jana@x.cz`` count as one username, so the
    lockout cannot be bypassed by changing letter case. Reads ``credentials`` first
    (key ``email``, or ``username`` from the admin login), then the POST data.
    Returns ``None`` when no e-mail is present.
    """
    if credentials:
        value = credentials.get("email") or credentials.get("username")
    elif request is not None:
        data = getattr(request, "data", request.POST)
        value = data.get("email") or data.get("username")
    else:
        value = None
    return UserManager.normalize_email(value) or None


def get_client_ip(request: HttpRequest) -> str | None:
    """Return the client IP address used for lockout.

    With ``settings.TRUSTED_PROXY_COUNT == 0`` this is ``REMOTE_ADDR``. Behind N
    trusted reverse proxies that each append to ``X-Forwarded-For``, the address is
    the N-th entry from the right; entries further left are client-controlled and
    ignored. A shorter header falls back to ``REMOTE_ADDR``.
    """
    remote_addr = request.META.get("REMOTE_ADDR")
    count = settings.TRUSTED_PROXY_COUNT
    if count <= 0:
        return remote_addr
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if len(hops) < count:
        return remote_addr
    return hops[-count]
