"""Account services: registration, activation, account e-mails and deletion.

Views stay thin and call these functions. Functions that react to an e-mail
address entered by a visitor never reveal whether an account exists: callers
always show the same message (no account enumeration).
"""

import logging

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import User, UserManager
from .roles import Role
from .tokens import activation_token

logger = logging.getLogger(__name__)


# --- E-mails -----------------------------------------------------------------------------


def claim_email_slot(kind: str, user: User) -> bool:
    """Return ``True`` if an e-mail of ``kind`` may be sent to ``user`` now.

    At most one e-mail of each kind per ``settings.ACCOUNT_EMAIL_THROTTLE_SECONDS``
    goes to one user, so the public forms cannot be used to flood a mailbox. The
    limit lives in the cache (per process with the default local-memory cache).
    """
    key = f"accounts:email:{kind}:{user.pk}"
    return cache.add(key, True, timeout=settings.ACCOUNT_EMAIL_THROTTLE_SECONDS)


def _send(user: User, template_prefix: str, context: dict) -> None:
    """Render ``<prefix>_subject.txt`` and ``<prefix>_body.txt`` and send them to ``user``.

    Delivery errors are logged, not raised: the visitor must see the same page
    whether or not a message was sent.
    """
    context = {"user": user, **context}
    subject = render_to_string(f"{template_prefix}_subject.txt", context)
    subject = settings.EMAIL_SUBJECT_PREFIX + "".join(subject.splitlines()).strip()
    body = render_to_string(f"{template_prefix}_body.txt", context)
    try:
        send_mail(subject, body, None, [user.email])
    except Exception:
        logger.exception("Sending account e-mail %s to user %s failed", template_prefix, user.pk)


def send_activation_email(user: User, request: HttpRequest) -> None:
    """Send the activation link to a user who registered and has not activated yet.

    Inputs: the user and the current request (for the absolute link). Does nothing
    when the user is not pending activation or the e-mail is throttled.
    """
    if user.is_active or not user.activation_pending:
        return
    if not claim_email_slot("activation", user):
        return
    path = reverse(
        "accounts:activate",
        kwargs={
            "uidb64": urlsafe_base64_encode(force_bytes(user.pk)),
            "token": activation_token.make_token(user),
        },
    )
    _send(
        user,
        "accounts/email/activation",
        {
            "activation_url": request.build_absolute_uri(path),
            "valid_hours": settings.PASSWORD_RESET_TIMEOUT // 3600,
        },
    )


def send_already_registered_email(user: User, request: HttpRequest) -> None:
    """Tell the owner of an existing account that someone tried to register their e-mail."""
    if not claim_email_slot("already-registered", user):
        return
    _send(
        user,
        "accounts/email/already_registered",
        {
            "login_url": request.build_absolute_uri(reverse("accounts:login")),
            "password_reset_url": request.build_absolute_uri(reverse("accounts:password_reset")),
        },
    )


# --- Registration and activation ---------------------------------------------------------


def register(email: str, password: str, request: HttpRequest) -> None:
    """Register a new owner account, or notify the existing one.

    Inputs: e-mail and an already validated password. A new address gets an
    inactive account in the ``owner`` group and an activation e-mail. An address
    that already has an account gets a notice (or, if still pending, a fresh
    activation link) and its password is NOT changed. The password is hashed in
    both branches so that response time does not reveal which one ran.
    """
    email = UserManager.normalize_email(email)
    password_hash = make_password(password)
    existing = User.objects.filter(email=email).first()
    if existing is None:
        try:
            with transaction.atomic():
                user = User(
                    email=email, password=password_hash, is_active=False, activation_pending=True
                )
                user.save()
                owner_group, _ = Group.objects.get_or_create(name=Role.OWNER)
                user.groups.add(owner_group)
        except IntegrityError:  # registered concurrently with the same e-mail
            existing = User.objects.get(email=email)
        else:
            send_activation_email(user, request)
            return
    if existing.activation_pending and not existing.is_active:
        send_activation_email(existing, request)
    else:
        send_already_registered_email(existing, request)


def resend_activation(email: str, request: HttpRequest) -> None:
    """Send a new activation link if ``email`` belongs to an account pending activation.

    Silent otherwise, so the caller shows the same message for any address.
    """
    user = User.objects.filter(email=UserManager.normalize_email(email)).first()
    if user is not None:
        send_activation_email(user, request)


def user_for_activation(uidb64: str, token: str) -> User | None:
    """Return the user the activation link belongs to, or ``None`` if the link is invalid.

    A link is valid when it decodes to an existing user who is pending activation
    and the token matches and has not expired.
    """
    try:
        pk = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=pk)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None
    if user.is_active or not user.activation_pending:
        return None
    if not activation_token.check_token(user, token):
        return None
    return user


def activate(user: User) -> None:
    """Activate a user returned by :func:`user_for_activation`."""
    user.is_active = True
    user.activation_pending = False
    user.save(update_fields=["is_active", "activation_pending"])


# --- Re-authentication and deletion ------------------------------------------------------


def password_matches(request: HttpRequest, user: User, password: str) -> bool:
    """Check the current password of a signed-in user before a sensitive action.

    Goes through ``authenticate`` so that django-axes counts wrong guesses and
    locks the client out after ``LOGIN_FAILURE_LIMIT`` failures, as on the login page.
    """
    authenticated = authenticate(request, email=user.email, password=password)
    return authenticated is not None and authenticated.pk == user.pk


def delete_account(user: User) -> None:
    """Delete the user, all data that cascades from it, and their login records.

    django-axes keeps login logs by e-mail rather than by foreign key, so they are
    removed explicitly. Runs in one transaction.
    """
    from axes.models import AccessAttempt, AccessFailureLog, AccessLog

    with transaction.atomic():
        for model in (AccessLog, AccessAttempt, AccessFailureLog):
            model.objects.filter(username=user.email).delete()
        user.delete()
