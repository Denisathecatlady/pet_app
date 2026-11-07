"""Two-factor authentication on django-otp: TOTP app plus one-time recovery codes (docs/14 §14.6).

Views stay thin and call these functions. What this module decides:

* **Who must use it.** Every staff user (``User.is_staff``, derived from the roles) when
  ``settings.REQUIRE_2FA_FOR_STAFF`` is true (prod.py refuses to start with false). Everybody
  else may enrol; a user who did enrol must pass the check at every sign-in.
* **What counts as a device.** A confirmed ``TOTPDevice``. A device that is not confirmed
  yet is a pending enrolment and grants nothing. Recovery codes are a ``StaticDevice``.
* **Throttling.** Failed tokens are throttled per device by django-otp (exponential
  back-off, ``OTP_TOTP_THROTTLE_FACTOR`` and ``OTP_STATIC_THROTTLE_FACTOR`` in the settings).
  Every failure looks the same to the caller (``verify`` returns ``None``): a wrong token, a
  throttled device, a malformed code and a user without any device cannot be told apart.

Limits of django-otp, stated honestly (docs/14 §14.6): the TOTP secret and the recovery codes
are stored in the database in plain text, so a database leak (or a backup) exposes the second
factor; recovery codes are not hashed; there is no hard lockout, only the back-off.
"""

import io
import re
from base64 import b32encode
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Final

import django_otp
import qrcode
from django.conf import settings
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.safestring import SafeString
from django_otp.models import Device
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice
from qrcode.image.svg import SvgPathImage

TOTP_DEVICE_NAME: Final = "Aplikace pro ověřování"
RECOVERY_DEVICE_NAME: Final = "Záložní kódy"
RECOVERY_CODE_COUNT: Final = 10
# A QR code that was not confirmed within this time is replaced by a fresh secret.
PENDING_ENROLLMENT_MAX_AGE: Final = timedelta(hours=1)

_TOTP_CODE = re.compile(r"\d{6}")
_RECOVERY_CODE = re.compile(r"[a-z2-7]{8}")


class State(Enum):
    """What a signed-in user still has to do before the application may be used."""

    OK = "ok"
    ENROLLMENT_REQUIRED = "enrollment_required"
    VERIFICATION_REQUIRED = "verification_required"


@dataclass(frozen=True)
class Status:
    """What the account page and the GDPR export say about two-factor authentication."""

    enrolled: bool
    confirmed_at: datetime | None
    recovery_codes_left: int
    required: bool


# --- Who needs what -----------------------------------------------------------------------


def is_required(user: Any) -> bool:
    """Return whether two-factor authentication is mandatory for ``user`` (a staff user)."""
    return bool(settings.REQUIRE_2FA_FOR_STAFF and user.is_staff)


def confirmed_device(user: Any) -> TOTPDevice | None:
    """Return the confirmed authenticator-app device of ``user``, if any."""
    return TOTPDevice.objects.filter(user=user, confirmed=True).order_by("pk").first()


def is_verified(user: Any) -> bool:
    """Return whether the session of ``user`` has passed the second factor.

    False when ``OTPMiddleware`` is not installed (fail closed).
    """
    check = getattr(user, "is_verified", None)
    return bool(check is not None and check())


def state_for(user: Any) -> State:
    """Return what ``user`` has to do next (``State.OK`` when nothing).

    Verified session: nothing. A confirmed device but an unverified session: verify.
    No device: enrol if two-factor is mandatory for the user, else nothing.
    """
    if is_verified(user):
        return State.OK
    if confirmed_device(user) is not None:
        return State.VERIFICATION_REQUIRED
    return State.ENROLLMENT_REQUIRED if is_required(user) else State.OK


def status(user: Any) -> Status:
    """Return the two-factor status of ``user`` (never a secret or a code)."""
    device = confirmed_device(user)
    return Status(
        enrolled=device is not None,
        confirmed_at=device.created_at if device is not None else None,
        recovery_codes_left=recovery_codes_left(user),
        required=is_required(user),
    )


def lockout_response(request: HttpRequest) -> HttpResponse | None:
    """Return the django-axes lockout response when the client is locked out of the account.

    The password lockout (docs/12 §12.10) stays as it is; this makes it hold for a session
    that already exists: a client locked out for this e-mail address cannot pass or change
    the second factor either. ``None`` when the client may continue.
    """
    from axes.handlers.proxy import AxesProxyHandler
    from axes.helpers import get_lockout_response

    if not settings.AXES_ENABLED:
        return None
    credentials = {"email": request.user.email}
    if AxesProxyHandler.is_locked(request, credentials):
        return get_lockout_response(request, None, credentials)
    return None


# --- Enrolment ----------------------------------------------------------------------------


def begin_enrollment(user: Any) -> TOTPDevice:
    """Return the pending (not yet confirmed) authenticator device of ``user``.

    Reuses a pending device younger than ``PENDING_ENROLLMENT_MAX_AGE`` so that reloading the
    page keeps the same QR code; older ones are deleted and a new secret is generated.
    A device that is not confirmed grants nothing.
    """
    cutoff = timezone.now() - PENDING_ENROLLMENT_MAX_AGE
    with transaction.atomic():
        TOTPDevice.objects.filter(user=user, confirmed=False, created_at__lt=cutoff).delete()
        pending = TOTPDevice.objects.filter(user=user, confirmed=False).order_by("-pk").first()
        if pending is None:
            pending = TOTPDevice.objects.create(user=user, name=TOTP_DEVICE_NAME, confirmed=False)
    return pending


def secret_text(device: TOTPDevice) -> str:
    """Return the secret in the base32 form authenticator apps accept, in groups of four."""
    secret = b32encode(device.bin_key).decode("ascii")
    return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))


def qr_svg(device: TOTPDevice) -> SafeString:
    """Return the QR code of the device's ``otpauth://`` address as an inline SVG element.

    Rendered by ``qrcode`` without Pillow. The fixed size in millimetres is dropped (CSS
    sizes it) and the element is given a role and a label; the secret is also shown in
    text for manual entry (``secret_text``), so the picture is not the only way in.
    """
    code = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
        image_factory=SvgPathImage,
    )
    code.add_data(device.config_url)
    code.make(fit=True)
    buffer = io.BytesIO()
    code.make_image().save(buffer)
    svg = buffer.getvalue().decode("utf-8")
    svg = svg[svg.index("<svg") :]
    svg = re.sub(r' width="[^"]*" height="[^"]*"', "", svg, count=1)
    svg = svg.replace(
        "<svg ", '<svg class="qr__image" role="img" aria-label="QR kód pro aplikaci" ', 1
    )
    return SafeString(svg)


@transaction.atomic
def confirm_enrollment(user: Any, token: str) -> TOTPDevice | None:
    """Activate the pending device if ``token`` is a valid code from it.

    Inputs: the user and the six digits typed by the user. Output: the now confirmed device,
    or ``None`` (wrong or throttled token, no pending device: not told apart).

    Confirming replaces every earlier device of the user (the new authenticator takes over)
    and, for a user without recovery codes, the caller creates them with
    :func:`generate_recovery_codes`. django-otp keeps no confirmation time, so the creation
    time of the device is set to the moment of confirmation (the GDPR export reports it).
    """
    pending = TOTPDevice.objects.filter(user=user, confirmed=False).order_by("-pk").first()
    code = normalize_code(token)
    if pending is None or not _TOTP_CODE.fullmatch(code):
        return None
    if django_otp.verify_token(user, pending.persistent_id, code) is None:
        return None
    TOTPDevice.objects.filter(user=user).exclude(pk=pending.pk).delete()
    pending.refresh_from_db()
    pending.confirmed = True
    pending.created_at = timezone.now()
    pending.save(update_fields=["confirmed", "created_at"])
    return pending


# --- Verification -------------------------------------------------------------------------


def normalize_code(raw: str) -> str:
    """Return ``raw`` without spaces and hyphens, in lower case (as codes are stored)."""
    return re.sub(r"[\s-]", "", raw or "").lower()


def verify(user: Any, raw_code: str) -> Device | None:
    """Check a code from the authenticator app or a recovery code.

    Input: the user and what they typed. Output: the device that accepted the code, or
    ``None`` for every kind of failure (wrong, malformed, throttled, no device): the
    caller must show one message for all of them. A recovery code is consumed.
    """
    code = normalize_code(raw_code)
    device: Device | None = None
    if _TOTP_CODE.fullmatch(code):
        device = confirmed_device(user)
    elif _RECOVERY_CODE.fullmatch(code):
        device = StaticDevice.objects.filter(user=user, confirmed=True).order_by("pk").first()
    if device is None:
        return None
    return django_otp.verify_token(user, device.persistent_id, code)


def verify_totp(user: Any, raw_code: str) -> bool:
    """Check a code from the authenticator app only (recovery codes do not count).

    Used before sensitive changes (new recovery codes, switching two-factor off).
    """
    code = normalize_code(raw_code)
    device = confirmed_device(user)
    if device is None or not _TOTP_CODE.fullmatch(code):
        return False
    return django_otp.verify_token(user, device.persistent_id, code) is not None


def mark_verified(request: HttpRequest, device: Device) -> None:
    """Remember in the session that the second factor was passed, with a fresh session key.

    The key is rotated because the privilege of the session changes (session fixation).
    """
    django_otp.login(request, device)
    request.session.cycle_key()


# --- Recovery codes -----------------------------------------------------------------------


def display_code(code: str) -> str:
    """Return a recovery code in the form shown to the user: ``abcd-efgh``."""
    return f"{code[:4]}-{code[4:]}"


@transaction.atomic
def generate_recovery_codes(user: Any) -> list[str]:
    """Replace the recovery codes of ``user`` with new ones and return them for display.

    The old codes stop working. The codes are returned only here and are not shown again
    (django-otp stores them in plain text, so the page could, but the application does not).
    """
    device, _ = StaticDevice.objects.get_or_create(
        user=user, defaults={"name": RECOVERY_DEVICE_NAME}
    )
    device.token_set.all().delete()
    codes = [StaticToken.random_token() for _ in range(RECOVERY_CODE_COUNT)]
    StaticToken.objects.bulk_create([StaticToken(device=device, token=code) for code in codes])
    return [display_code(code) for code in codes]


def recovery_codes_left(user: Any) -> int:
    """Return how many recovery codes of ``user`` are still unused."""
    return StaticToken.objects.filter(device__user=user).count()


# --- Switching off and loss recovery ------------------------------------------------------


@transaction.atomic
def remove_devices(user: Any) -> int:
    """Delete every two-factor device of ``user`` (authenticator, pending and recovery codes).

    Output: the number of devices deleted (recovery codes go with their device and are not
    counted). Sessions that were verified with a deleted device are no longer verified
    (``OTPMiddleware`` finds no device), so a staff user is sent to enrolment on the next request.
    """
    removed = 0
    for model in (TOTPDevice, StaticDevice):
        _, per_model = model.objects.filter(user=user).delete()
        removed += per_model.get(model._meta.label, 0)
    return removed
