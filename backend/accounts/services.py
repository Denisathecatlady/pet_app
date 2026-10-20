"""Account services: registration, activation, account e-mails and deletion.

Views stay thin and call these functions. Functions that react to an e-mail
address entered by a visitor never reveal whether an account exists: callers
always show the same message (no account enumeration).
"""

import logging
import threading
from datetime import datetime

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from .models import User, UserManager
from .roles import Role
from .tokens import activation_token

logger = logging.getLogger(__name__)


# --- E-mails -----------------------------------------------------------------------------


DAY_SECONDS = 24 * 60 * 60


def claim_email_slot(kind: str, user: User) -> bool:
    """Return ``True`` if an e-mail of ``kind`` may be sent to ``user`` now.

    The public forms must not be usable to flood a mailbox, so two limits apply:
    at most one e-mail of each kind per ``settings.ACCOUNT_EMAIL_THROTTLE_SECONDS``
    and at most ``settings.ACCOUNT_EMAIL_DAILY_LIMIT`` account e-mails of all kinds
    per user in a 24-hour window. The counters live in the cache; production uses a
    shared database cache, so the limits hold across worker processes.
    """
    if not cache.add(
        f"accounts:email:{kind}:{user.pk}", True, timeout=settings.ACCOUNT_EMAIL_THROTTLE_SECONDS
    ):
        return False
    daily_key = f"accounts:email-day:{user.pk}"
    cache.add(daily_key, 0, timeout=DAY_SECONDS)
    try:
        sent_today = cache.incr(daily_key)
    except ValueError:  # the counter expired between add() and incr()
        cache.set(daily_key, 1, timeout=DAY_SECONDS)
        sent_today = 1
    return sent_today <= settings.ACCOUNT_EMAIL_DAILY_LIMIT


def _send_now(message: EmailMessage) -> None:
    try:
        message.send()
    except Exception:
        logger.exception("Sending account e-mail %r failed", message.subject)


def deliver(message: EmailMessage) -> None:
    """Send an account e-mail that was rendered in the request.

    With ``settings.ACCOUNT_EMAIL_IN_BACKGROUND`` (production) the SMTP exchange runs
    in a separate thread after this function returns. Pages that send an e-mail only
    for existing accounts (password reset, new activation link) then answer as fast
    as for unknown addresses, so response time does not reveal accounts. Delivery
    errors are logged, never raised. The thread is not a daemon: a worker that shuts
    down waits for it (at most ``EMAIL_TIMEOUT``).
    """
    if settings.ACCOUNT_EMAIL_IN_BACKGROUND:
        threading.Thread(target=_send_now, args=(message,), name="account-email").start()
    else:
        _send_now(message)


def _send(user: User, template_prefix: str, context: dict) -> None:
    """Render ``<prefix>_subject.txt`` and ``<prefix>_body.txt`` and deliver them to ``user``.

    Delivery errors are logged, not raised: the visitor must see the same page
    whether or not a message was sent.
    """
    context = {"user": user, **context}
    subject = render_to_string(f"{template_prefix}_subject.txt", context)
    subject = settings.EMAIL_SUBJECT_PREFIX + "".join(subject.splitlines()).strip()
    body = render_to_string(f"{template_prefix}_body.txt", context)
    deliver(EmailMessage(subject, body, None, [user.email]))


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
    that already has an active (or deactivated) account gets a notice and its
    password is NOT changed. An address still pending activation takes the password
    of this latest registration and gets a fresh activation link: activation asks
    for that password (:func:`activation_password_matches`), so an account
    registered first by someone else can never be activated with their password.
    The password is hashed in every branch so that response time does not reveal
    which one ran.
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
        existing.password = password_hash
        existing.save(update_fields=["password"])
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


def activation_password_matches(user: User, password: str) -> bool:
    """Check the password entered on the activation page.

    Activation needs both the link (proof of the mailbox) and the password of the
    latest registration of that address (proof of who registered). Only the holder of
    a valid link reaches this check, so it is not rate limited.
    """
    return user.check_password(password)


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
    """Delete the user and all data that cascades from it, in one transaction.

    Records kept outside foreign keys (django-axes login records, the e-mail in the
    admin log) are cleaned by the ``post_delete`` receivers in ``accounts.signals``,
    so deleting a user in the admin removes them too.
    """
    with transaction.atomic():
        user.delete()


def purge_pending_accounts(*, now: datetime | None = None) -> int:
    """Delete registrations never activated within ``settings.PENDING_ACCOUNT_RETENTION``.

    Anyone can register any address; an unconfirmed registration is personal data of
    a person who may never have agreed, so it is not kept. Accounts deactivated by
    an administrator (``activation_pending`` false) are not touched.

    Output: number of deleted accounts.
    """
    cutoff = (now or timezone.now()) - settings.PENDING_ACCOUNT_RETENTION
    stale = User.objects.filter(activation_pending=True, is_active=False, date_joined__lt=cutoff)
    deleted = 0
    for user in stale:
        delete_account(user)
        deleted += 1
    return deleted
