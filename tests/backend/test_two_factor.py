"""Two-factor authentication: the service functions (docs/14 §14.6)."""

import base64
import re
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import two_factor
from accounts.roles import Role
from accounts.two_factor import State
from tests.backend.helpers import enroll, totp_token, wrong_token

pytestmark = pytest.mark.django_db


class Clock:
    """Moves the clock django-otp reads for its back-off (the code itself uses the real one)."""

    def __init__(self, monkeypatch):
        self.offset = timedelta()
        real_now = timezone.now
        monkeypatch.setattr(timezone, "now", lambda: real_now() + self.offset)

    def advance(self, seconds: float) -> None:
        self.offset += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    return Clock(monkeypatch)


def session_of(user, *, verified: bool):
    """The user as ``OTPMiddleware`` presents it."""
    user.is_verified = lambda: verified
    return user


@pytest.fixture
def staff(make_user):
    return make_user("staff@example.cz", roles=(Role.SUPPORT_ADMIN,))


@pytest.fixture
def enrolled(user):
    """An ordinary user with a confirmed device and ten recovery codes."""
    device = enroll(user)
    codes = two_factor.generate_recovery_codes(user)
    return user, device, codes


# --- Who needs it -----------------------------------------------------------------------------


def test_it_is_required_for_staff_only(staff, user, superuser):
    assert two_factor.is_required(staff) and two_factor.is_required(superuser)
    assert not two_factor.is_required(user)


@override_settings(REQUIRE_2FA_FOR_STAFF=False)
def test_the_requirement_can_be_switched_off(staff):
    assert not two_factor.is_required(staff)
    assert two_factor.state_for(session_of(staff, verified=False)) is State.OK


@pytest.mark.parametrize(
    ("kind", "device", "verified", "expected"),
    [
        ("staff", None, False, State.ENROLLMENT_REQUIRED),
        ("staff", "pending", False, State.ENROLLMENT_REQUIRED),
        ("staff", "confirmed", False, State.VERIFICATION_REQUIRED),
        ("staff", "confirmed", True, State.OK),
        ("user", None, False, State.OK),
        ("user", "pending", False, State.OK),
        ("user", "confirmed", False, State.VERIFICATION_REQUIRED),
        ("user", "confirmed", True, State.OK),
    ],
)
def test_state_matrix(staff, user, kind, device, verified, expected):
    account = staff if kind == "staff" else user
    if device is not None:
        enroll(account, confirmed=device == "confirmed")

    assert two_factor.state_for(session_of(account, verified=verified)) is expected


def test_without_the_otp_middleware_nobody_counts_as_verified(user):
    assert two_factor.is_verified(user) is False  # a plain user has no is_verified()


def test_status_never_contains_a_secret(enrolled):
    user, device, codes = enrolled

    status = two_factor.status(user)

    assert status.enrolled and status.recovery_codes_left == 10 and not status.required
    assert status.confirmed_at == device.created_at
    assert not hasattr(status, "key")


def test_status_of_a_user_without_a_device(user):
    status = two_factor.status(user)
    assert (status.enrolled, status.confirmed_at, status.recovery_codes_left) == (False, None, 0)


# --- Enrolment --------------------------------------------------------------------------------


def test_begin_enrollment_creates_a_pending_device_and_reuses_it(user):
    first = two_factor.begin_enrollment(user)
    again = two_factor.begin_enrollment(user)

    assert not first.confirmed and first.pk == again.pk and first.key == again.key
    assert two_factor.confirmed_device(user) is None  # a pending device grants nothing


def test_a_stale_pending_device_is_replaced_by_a_new_secret(user):
    old = two_factor.begin_enrollment(user)
    TOTPDevice.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - two_factor.PENDING_ENROLLMENT_MAX_AGE - timedelta(seconds=1)
    )

    new = two_factor.begin_enrollment(user)

    assert new.pk != old.pk and new.key != old.key
    assert not TOTPDevice.objects.filter(pk=old.pk).exists()


def test_confirmation_needs_a_code_from_the_pending_device(user):
    pending = two_factor.begin_enrollment(user)

    assert two_factor.confirm_enrollment(user, wrong_token(pending)) is None
    pending.refresh_from_db()
    assert not pending.confirmed and pending.throttling_failure_count == 1


@pytest.mark.parametrize("token", ["", "abc", "12345", "1234567", " "])
def test_confirmation_rejects_malformed_codes(user, token):
    pending = two_factor.begin_enrollment(user)

    assert two_factor.confirm_enrollment(user, token) is None
    pending.refresh_from_db()
    assert not pending.confirmed


def test_confirmation_activates_the_device_and_records_the_time(user):
    pending = two_factor.begin_enrollment(user)
    before = timezone.now()

    device = two_factor.confirm_enrollment(user, totp_token(pending))

    assert device.pk == pending.pk and device.confirmed
    assert device.created_at >= before
    assert two_factor.confirmed_device(user) == device


def test_confirmation_without_a_pending_device_fails(user):
    assert two_factor.confirm_enrollment(user, "123456") is None


def test_confirming_a_new_device_replaces_the_old_one(enrolled):
    user, old, codes = enrolled
    pending = two_factor.begin_enrollment(user)

    new = two_factor.confirm_enrollment(user, totp_token(pending))

    assert new is not None and list(TOTPDevice.objects.filter(user=user)) == [new]
    assert two_factor.recovery_codes_left(user) == 10  # recovery codes stay


def test_a_code_of_another_users_pending_device_does_not_confirm(make_user):
    mine = make_user("me@example.cz")
    other = make_user("other@example.cz")
    other_pending = two_factor.begin_enrollment(other)
    two_factor.begin_enrollment(mine)

    assert two_factor.confirm_enrollment(mine, totp_token(other_pending)) is None


# --- The QR code and the secret ---------------------------------------------------------------


def test_the_qr_code_is_an_inline_svg_without_a_fixed_size(user):
    svg = two_factor.qr_svg(two_factor.begin_enrollment(user))

    assert svg.startswith("<svg ") and svg.endswith("</svg>")
    assert 'role="img"' in svg and 'aria-label="QR kód pro aplikaci"' in svg
    assert 'class="qr__image"' in svg and "viewBox=" in svg
    assert "mm" not in svg.split(">", 1)[0] and "<?xml" not in svg
    assert "style=" not in svg and "<script" not in svg  # strict CSP


def test_the_secret_is_shown_in_groups_and_matches_the_device(user):
    device = two_factor.begin_enrollment(user)

    text = two_factor.secret_text(device)

    assert re.fullmatch(r"([A-Z2-7]{4} )+[A-Z2-7]{4}", text)
    assert base64.b32decode(text.replace(" ", "")) == device.bin_key


def test_the_address_in_the_qr_names_the_issuer_and_the_account(user):
    device = two_factor.begin_enrollment(user)

    assert device.config_url.startswith("otpauth://totp/BARF%20Nutri%3Ajana%40example.cz?")
    assert "issuer=BARF%20Nutri" in device.config_url


# --- Verification and throttling ---------------------------------------------------------------


def test_a_code_from_the_app_is_accepted_once(enrolled):
    user, device, _ = enrolled
    token = totp_token(device)

    assert two_factor.verify(user, token).pk == device.pk
    assert two_factor.verify(user, token) is None  # the same code is not accepted twice


def test_spaces_and_hyphens_are_ignored(enrolled):
    user, device, codes = enrolled
    token = totp_token(device)

    assert two_factor.verify(user, f" {token[:3]} {token[3:]} ") is not None
    assert two_factor.verify(user, codes[0].upper().replace("-", " - ")) is not None


def test_a_recovery_code_works_once_and_is_consumed(enrolled):
    user, _, codes = enrolled

    assert isinstance(two_factor.verify(user, codes[0]), StaticDevice)
    assert two_factor.recovery_codes_left(user) == 9
    assert two_factor.verify(user, codes[0]) is None


def test_every_kind_of_failure_looks_the_same(enrolled, make_user):
    user, device, _ = enrolled
    nobody = make_user("nobody@example.cz")

    results = [
        two_factor.verify(user, wrong_token(device)),  # wrong code
        two_factor.verify(user, "abcdefgh"),  # wrong recovery code
        two_factor.verify(user, "not a code"),  # malformed
        two_factor.verify(user, ""),  # empty
        two_factor.verify(nobody, totp_token(device)),  # user without any device
        two_factor.verify(nobody, "abcdefgh"),
    ]

    assert results == [None] * 6


def test_failures_slow_down_the_next_attempts_and_a_right_code_waits(enrolled, clock):
    user, device, _ = enrolled
    assert two_factor.verify(user, wrong_token(device)) is None  # first failure: 2 s back-off

    assert two_factor.verify(user, totp_token(device)) is None  # right code, but too soon
    clock.advance(2.5)
    assert two_factor.verify(user, totp_token(device)) is not None


def test_the_back_off_doubles_with_every_failure(enrolled, clock):
    user, device, _ = enrolled
    waits = []
    for _ in range(4):
        two_factor.verify(user, wrong_token(device))
        device.refresh_from_db()
        waits.append(device.throttling_failure_count)
        clock.advance(2 ** (device.throttling_failure_count - 1) * 2 + 0.5)

    assert waits == [1, 2, 3, 4]
    assert two_factor.verify(user, totp_token(device)) is not None  # a right code resets it
    device.refresh_from_db()
    assert device.throttling_failure_count == 0


def test_an_attempt_during_the_wait_is_not_counted(enrolled):
    user, device, _ = enrolled
    two_factor.verify(user, wrong_token(device))

    for _ in range(5):
        two_factor.verify(user, wrong_token(device))

    device.refresh_from_db()
    assert device.throttling_failure_count == 1


def test_recovery_codes_are_throttled_separately(enrolled, clock):
    user, device, codes = enrolled
    two_factor.verify(user, "abcdefgh")  # a failed recovery code

    assert two_factor.verify(user, codes[0]) is None  # throttled
    assert two_factor.verify(user, totp_token(device)) is not None  # the app is not affected
    clock.advance(2.5)
    assert two_factor.verify(user, codes[0]) is not None


def test_the_throttle_settings_are_documented_values():
    from django.conf import settings

    assert settings.OTP_TOTP_THROTTLE_FACTOR == 2 and settings.OTP_STATIC_THROTTLE_FACTOR == 2


def test_verify_totp_accepts_only_the_app(enrolled):
    user, device, codes = enrolled

    assert not two_factor.verify_totp(user, codes[0])
    assert two_factor.recovery_codes_left(user) == 10  # and a recovery code is not consumed
    assert two_factor.verify_totp(user, totp_token(device))


def test_verify_totp_without_a_device_is_false(user):
    assert not two_factor.verify_totp(user, "123456")


def test_a_code_cannot_be_used_for_another_user(enrolled, make_user):
    user, device, codes = enrolled
    other = make_user("other@example.cz")
    enroll(other)

    assert two_factor.verify(other, totp_token(device)) is None
    assert two_factor.verify(other, codes[0]) is None


# --- Recovery codes -----------------------------------------------------------------------------


def test_ten_recovery_codes_of_the_documented_shape(user):
    codes = two_factor.generate_recovery_codes(user)

    assert len(codes) == 10 == two_factor.RECOVERY_CODE_COUNT
    assert all(re.fullmatch(r"[a-z2-7]{4}-[a-z2-7]{4}", code) for code in codes)
    assert two_factor.recovery_codes_left(user) == 10


def test_new_recovery_codes_replace_the_old_ones(user, clock):
    old = two_factor.generate_recovery_codes(user)
    enroll(user)

    new = two_factor.generate_recovery_codes(user)

    assert two_factor.recovery_codes_left(user) == 10 and not set(old) & set(new)
    assert two_factor.verify(user, old[0]) is None
    clock.advance(2.5)  # (the failed attempt above started the back-off)
    assert two_factor.verify(user, new[0]) is not None
    assert StaticDevice.objects.filter(user=user).count() == 1


def test_recovery_codes_are_stored_in_plain_text_as_django_otp_does(user):
    """Documented limit (docs/14 §14.6): the database holds the codes, unlike a password."""
    code = two_factor.generate_recovery_codes(user)[0]

    assert StaticToken.objects.filter(token=code.replace("-", "")).exists()


# --- Removing -----------------------------------------------------------------------------------


def test_remove_devices_deletes_everything_of_the_user_only(enrolled, make_user):
    user, _, _ = enrolled
    two_factor.begin_enrollment(user)
    other = make_user("other@example.cz")
    enroll(other)
    two_factor.generate_recovery_codes(other)

    removed = two_factor.remove_devices(user)

    assert removed == 3  # the authenticator, the pending one and the recovery codes
    assert not TOTPDevice.objects.filter(user=user).exists()
    assert not StaticDevice.objects.filter(user=user).exists()
    assert not StaticToken.objects.filter(device__user=user).exists()
    assert TOTPDevice.objects.filter(user=other).exists()
    assert StaticToken.objects.filter(device__user=other).count() == 10


def test_codes_are_normalised():
    assert two_factor.normalize_code(" AbCd - 2f3G ") == "abcd2f3g"
    assert two_factor.display_code("abcd2f3g") == "abcd-2f3g"
