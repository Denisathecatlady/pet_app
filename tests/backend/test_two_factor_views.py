"""Two-factor authentication: enrolment, verification, recovery codes, switching off, the gate
that sends users to the right page, throttling and the interplay with the django-axes lockout
(docs/14 §14.6)."""

import base64
import re
from datetime import timedelta
from urllib.parse import urlencode

import pytest
from django.conf import settings
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import two_factor
from accounts.forms import INVALID_TOKEN_MESSAGE
from accounts.models import User
from accounts.roles import Role
from tests.backend.helpers import (
    OTHER_PASSWORD,
    PASSWORD,
    enroll,
    log_in_verified,
    totp_token,
    wrong_token,
)

pytestmark = pytest.mark.django_db

STATUS = reverse("accounts:two_factor")
SETUP = reverse("accounts:two_factor_setup")
VERIFY = reverse("accounts:two_factor_verify")
CODES = reverse("accounts:two_factor_codes")
DISABLE = reverse("accounts:two_factor_disable")
LOGIN = reverse("accounts:login")
LOGOUT = reverse("accounts:logout")
DASHBOARD = reverse("core:dashboard")


class Clock:
    def __init__(self, monkeypatch):
        self.offset = timedelta()
        real_now = timezone.now
        monkeypatch.setattr(timezone, "now", lambda: real_now() + self.offset)

    def advance(self, seconds: float) -> None:
        self.offset += timedelta(seconds=seconds)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    return Clock(monkeypatch)


def sign_in(client, user, password=PASSWORD, **extra):
    return client.post(LOGIN, {"email": user.email, "password": password}, **extra)


def verified(client, user):
    """Sign in with the password and pass the second factor; return the user's device.

    Uses the device the user already has (enrolling one if there is none). The code it used
    is spent, so a test that needs another code asks for ``totp_token(device, steps=1)``.
    """
    device = two_factor.confirmed_device(user) or enroll(user)
    sign_in(client, user)
    client.post(VERIFY, {"token": totp_token(device)})
    return device


@pytest.fixture
def staff(make_user):
    return make_user("staff@example.cz", roles=(Role.SUPPORT_ADMIN,))


@pytest.fixture
def enrolled_user(user):
    """An ordinary user with a device and recovery codes, not signed in."""
    device = enroll(user)
    return user, device, two_factor.generate_recovery_codes(user)


def error_texts(response, field="token") -> list[str]:
    return list(response.context["form"].errors.get(field, []))


# --- Enrolment ----------------------------------------------------------------------------------


def test_the_setup_page_shows_the_qr_code_the_secret_and_creates_a_pending_device(client, user):
    client.force_login(user)

    response = client.get(SETUP)

    assert response.status_code == 200
    content = response.content.decode()
    device = TOTPDevice.objects.get(user=user)
    assert not device.confirmed
    assert '<svg class="qr__image" role="img"' in content
    secret = re.search(r'<code class="secret">([^<]+)</code>', content).group(1)
    assert base64.b32decode(secret.replace(" ", "")) == device.bin_key
    assert user.email in content and "časový (TOTP)" in content
    assert 'autocomplete="one-time-code"' in content
    assert (
        response["Cache-Control"].startswith("max-age=0")
        and "no-store" in response["Cache-Control"]
    )


def test_reloading_the_setup_page_keeps_the_same_secret(client, user):
    client.force_login(user)
    first = client.get(SETUP).content.decode()
    second = client.get(SETUP).content.decode()

    pattern = r'<code class="secret">([^<]+)</code>'
    assert re.search(pattern, first).group(1) == re.search(pattern, second).group(1)
    assert TOTPDevice.objects.filter(user=user).count() == 1


def test_a_wrong_code_does_not_activate_the_device(client, user):
    client.force_login(user)
    client.get(SETUP)
    device = TOTPDevice.objects.get(user=user)

    response = client.post(SETUP, {"token": wrong_token(device)})

    assert response.status_code == 200 and error_texts(response) == [INVALID_TOKEN_MESSAGE]
    device.refresh_from_db()
    assert not device.confirmed
    assert two_factor.confirmed_device(user) is None


def test_the_right_code_activates_the_device_and_shows_the_recovery_codes_once(client, user):
    client.force_login(user)
    client.get(SETUP)
    device = TOTPDevice.objects.get(user=user)

    response = client.post(SETUP, {"token": totp_token(device)})

    assert response.status_code == 200
    content = response.content.decode()
    codes = re.findall(r"<code>([a-z2-7]{4}-[a-z2-7]{4})</code>", content)
    assert len(codes) == 10 and len(set(codes)) == 10
    assert "Aplikace je už znovu neukáže" in content
    device.refresh_from_db()
    assert device.confirmed
    assert client.session[DEVICE_ID_SESSION_KEY] == device.persistent_id  # signed in with it
    # They are never shown again, only counted.
    later = client.get(STATUS).content.decode()
    assert not any(code in later for code in codes) and "nepoužitých: 10" in later
    assert StaticDevice.objects.filter(user=user).count() == 1


def test_the_session_key_changes_when_the_second_factor_is_passed(client, user):
    client.force_login(user)
    client.get(SETUP)
    before = client.session.session_key

    client.post(SETUP, {"token": totp_token(TOTPDevice.objects.get(user=user))})

    assert client.session.session_key != before


def test_enrolment_continues_to_the_requested_page(client, staff):
    client.force_login(staff)
    next_url = reverse("accounts:profile")
    client.get(f"{SETUP}?next={next_url}")
    device = TOTPDevice.objects.get(user=staff)
    form = client.get(f"{SETUP}?next={next_url}").content.decode()
    assert f'name="next" value="{next_url}"' in form

    client.post(SETUP, {"token": totp_token(device), "next": next_url})
    codes_page = client.get(next_url)  # the gate lets a verified session through

    assert codes_page.status_code == 200


def test_replacing_the_device_needs_the_password_and_keeps_the_recovery_codes(
    client, enrolled_user
):
    user, old, codes = enrolled_user
    verified_client = client
    verified_client.force_login(user)
    session = verified_client.session
    session[DEVICE_ID_SESSION_KEY] = old.persistent_id
    session.save()
    page = verified_client.get(SETUP)
    assert 'name="password"' in page.content.decode()
    pending = TOTPDevice.objects.get(user=user, confirmed=False)

    wrong = verified_client.post(SETUP, {"password": OTHER_PASSWORD, "token": totp_token(pending)})
    assert wrong.status_code == 200 and "Heslo není správné." in wrong.content.decode()
    assert (
        TOTPDevice.objects.get(pk=old.pk).confirmed
        and not TOTPDevice.objects.get(pk=pending.pk).confirmed
    )

    right = verified_client.post(SETUP, {"password": PASSWORD, "token": totp_token(pending)})

    assert right.status_code == 302 and right["Location"] == DASHBOARD
    assert list(TOTPDevice.objects.filter(user=user)) == [TOTPDevice.objects.get(pk=pending.pk)]
    assert two_factor.recovery_codes_left(user) == 10


def test_a_wrong_password_does_not_use_up_the_code(client, enrolled_user):
    user, old, _ = enrolled_user
    client.force_login(user)
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = old.persistent_id
    session.save()
    client.get(SETUP)
    pending = TOTPDevice.objects.get(user=user, confirmed=False)
    code = totp_token(pending)

    client.post(SETUP, {"password": OTHER_PASSWORD, "token": code})

    pending.refresh_from_db()
    assert pending.last_t == -1 and pending.throttling_failure_count == 0  # code untouched
    assert client.post(SETUP, {"password": PASSWORD, "token": code}).status_code == 302


def test_a_session_that_did_not_pass_the_check_cannot_replace_the_device_even_without_the_gate(
    enrolled_user,
):
    """Defence in depth: the view itself refuses, not only the middleware in front of it."""
    user, old, _ = enrolled_user
    without_gate = [m for m in settings.MIDDLEWARE if "TwoFactorEnforcement" not in m]
    with override_settings(MIDDLEWARE=without_gate):
        guest = Client()
        sign_in(guest, user)
        guest.get(SETUP)
        response = guest.post(SETUP, {"password": PASSWORD, "token": "123456"})

    assert response.status_code == 302 and response["Location"] == VERIFY
    assert list(TOTPDevice.objects.filter(user=user)) == [old]  # no pending device either


@pytest.mark.parametrize("method", ["get", "post"])
def test_enrolment_needs_a_signed_in_user(client, method):
    response = getattr(client, method)(SETUP)

    assert response.status_code == 302 and response["Location"].startswith(LOGIN)


# --- Verification ---------------------------------------------------------------------------------


def test_the_password_alone_does_not_open_anything(client, enrolled_user):
    user, _, _ = enrolled_user

    login = sign_in(client, user)
    assert login.status_code == 302
    page = client.get(DASHBOARD)

    assert page.status_code == 302
    assert page["Location"] == f"{VERIFY}?{urlencode({'next': DASHBOARD})}"


def test_a_code_from_the_app_completes_the_sign_in(client, enrolled_user):
    user, device, _ = enrolled_user
    sign_in(client, user)
    client.get(DASHBOARD)
    before = client.session.session_key

    response = client.post(VERIFY, {"token": totp_token(device), "next": DASHBOARD})

    assert response.status_code == 302 and response["Location"] == DASHBOARD
    assert client.get(DASHBOARD).status_code == 200
    assert client.session.session_key != before  # rotated: no fixation
    assert client.session[DEVICE_ID_SESSION_KEY] == device.persistent_id


def test_the_verification_page_asks_for_a_code_and_offers_recovery_and_sign_out(
    client, enrolled_user
):
    user, _, _ = enrolled_user
    sign_in(client, user)

    content = client.get(VERIFY).content.decode()

    assert "Ověření přihlášení" in content and 'autocomplete="one-time-code"' in content
    assert "záložních kódů" in content or "záložní" in content
    assert f'action="{LOGOUT}"' in content


def test_a_wrong_code_is_refused_with_one_message(client, enrolled_user):
    user, device, _ = enrolled_user
    sign_in(client, user)

    response = client.post(VERIFY, {"token": wrong_token(device)})

    assert response.status_code == 200 and error_texts(response) == [INVALID_TOKEN_MESSAGE]
    assert client.get(DASHBOARD).status_code == 302  # still not through


def test_a_recovery_code_completes_the_sign_in_once(client, enrolled_user):
    user, _, codes = enrolled_user
    sign_in(client, user)

    ok = client.post(VERIFY, {"token": codes[0]})

    assert ok.status_code == 302 and client.get(DASHBOARD).status_code == 200
    assert two_factor.recovery_codes_left(user) == 9
    second = Client()
    sign_in(second, user)
    assert error_texts(second.post(VERIFY, {"token": codes[0]})) == [INVALID_TOKEN_MESSAGE]


def test_a_used_code_cannot_be_replayed_by_another_session(client, enrolled_user):
    user, device, _ = enrolled_user
    code = totp_token(device)
    other = Client()
    sign_in(client, user)
    sign_in(other, user)

    assert client.post(VERIFY, {"token": code}).status_code == 302
    assert error_texts(other.post(VERIFY, {"token": code})) == [INVALID_TOKEN_MESSAGE]


@pytest.mark.parametrize("token", ["x", "12345", "1234567", "abcdefgh", "ABCD-EFGH", "ž" * 6])
def test_malformed_codes_get_the_same_message(client, enrolled_user, token):
    user, _, _ = enrolled_user
    sign_in(client, user)

    response = client.post(VERIFY, {"token": token})

    assert response.status_code == 200 and error_texts(response) == [INVALID_TOKEN_MESSAGE]


@pytest.mark.parametrize("token", ["", "      ", "9" * 40])
def test_an_empty_or_too_long_code_is_refused_by_the_form(client, enrolled_user, token):
    user, _, _ = enrolled_user
    sign_in(client, user)

    response = client.post(VERIFY, {"token": token})

    assert response.status_code == 200 and error_texts(response)
    assert client.get(DASHBOARD).status_code == 302


def test_every_reason_of_failure_gives_the_same_page(client, enrolled_user, clock):
    """Wrong code, throttled device, wrong recovery code: one message, nothing to tell apart."""
    user, device, codes = enrolled_user
    sign_in(client, user)
    texts = []
    texts.append(error_texts(client.post(VERIFY, {"token": wrong_token(device)})))  # wrong
    texts.append(error_texts(client.post(VERIFY, {"token": totp_token(device)})))  # throttled
    clock.advance(10)
    texts.append(error_texts(client.post(VERIFY, {"token": "abcdefgh"})))  # wrong recovery code
    texts.append(error_texts(client.post(VERIFY, {"token": codes[0]})))  # throttled recovery

    assert texts == [[INVALID_TOKEN_MESSAGE]] * 4


def test_a_user_without_a_device_has_nothing_to_verify(client, user):
    client.force_login(user)

    get = client.get(VERIFY)
    post = client.post(VERIFY, {"token": "123456"})

    assert get.status_code == post.status_code == 302
    assert get["Location"] == post["Location"] == reverse("accounts:profile")


def test_staff_without_a_device_is_sent_from_verification_to_enrolment(client, staff):
    client.force_login(staff)

    assert client.get(VERIFY)["Location"].startswith(SETUP)


def test_a_verified_user_visiting_the_page_is_sent_on(client, enrolled_user):
    user, device, _ = enrolled_user
    verified(client, user)

    assert client.get(f"{VERIFY}?next={DASHBOARD}")["Location"] == DASHBOARD


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.example/phish",
        "//evil.example/phish",
        "http://testserver.evil.example/",
        "javascript:alert(1)",
        "/\\evil.example",
        VERIFY,
        SETUP,
        STATUS,
    ],
)
def test_next_never_leaves_the_site_and_never_loops(client, enrolled_user, target):
    user, device, _ = enrolled_user
    sign_in(client, user)

    response = client.post(VERIFY, {"token": totp_token(device), "next": target})

    assert response.status_code == 302 and response["Location"] == DASHBOARD


def test_a_safe_next_is_followed(client, enrolled_user):
    user, device, _ = enrolled_user
    sign_in(client, user)
    target = f"{reverse('catalog:source_list')}?q=fediaf"

    response = client.post(VERIFY, {"token": totp_token(device), "next": target})

    assert response["Location"] == target


def test_next_from_the_query_string_is_checked_too(client, enrolled_user):
    user, _, _ = enrolled_user
    sign_in(client, user)

    page = client.get(f"{VERIFY}?next=https://evil.example/").content.decode()

    assert "evil.example" not in page and f'name="next" value="{DASHBOARD}"' in page


# --- The gate: who is sent where ------------------------------------------------------------------

GATE_URLS = {
    "dashboard": ("get", DASHBOARD),
    "profile": ("get", reverse("accounts:profile")),
    "password change": ("get", reverse("accounts:password_change")),
    "admin index": ("get", reverse("admin:index")),
    "sources (public page)": ("get", reverse("catalog:source_list")),
    "home": ("get", reverse("core:home")),
    "new animal (POST)": ("post", reverse("animals:create")),
    "status": ("get", STATUS),
    "codes": ("get", CODES),
    "disable": ("get", DISABLE),
    "export": ("get", reverse("accounts:export")),
    "terms": ("get", reverse("core:terms")),
    "privacy": ("get", reverse("core:privacy")),
    "logout (POST)": ("post", LOGOUT),
    "setup": ("get", SETUP),
    "verify": ("get", VERIFY),
}
OPEN_IN_EVERY_STATE = {"terms", "privacy", "logout (POST)"}


def gate_target(client, method, url):
    response = getattr(client, method)(url)
    if response.status_code == 302 and response["Location"].startswith("/ucet/2fa/"):
        return response["Location"].split("?")[0]
    return None


@pytest.mark.parametrize("name", GATE_URLS)
def test_staff_without_a_device_may_only_enrol(client, staff, name):
    client.force_login(staff)
    method, url = GATE_URLS[name]

    target = gate_target(client, method, url)

    if name in OPEN_IN_EVERY_STATE or name == "setup":
        assert target is None, name
    else:
        assert target == SETUP, name


@pytest.mark.parametrize("name", GATE_URLS)
@pytest.mark.parametrize("kind", ["staff", "user"])
def test_an_enrolled_unverified_session_may_only_verify(client, staff, user, kind, name):
    account = staff if kind == "staff" else user
    enroll(account)
    client.force_login(account)
    method, url = GATE_URLS[name]

    target = gate_target(client, method, url)

    if name in OPEN_IN_EVERY_STATE or name == "verify":
        assert target is None, name
    else:
        assert target == VERIFY, name


@pytest.mark.parametrize("name", GATE_URLS)
@pytest.mark.parametrize("kind", ["staff", "user"])
def test_a_verified_session_is_not_sent_anywhere(client, staff, user, kind, name):
    account = staff if kind == "staff" else user
    log_in_verified(client, account)
    method, url = GATE_URLS[name]

    response = getattr(client, method)(url)

    sent_to_the_gate = response.status_code == 302 and response["Location"].startswith(
        (SETUP, VERIFY)
    )
    assert not sent_to_the_gate, name


@pytest.mark.parametrize("name", GATE_URLS)
def test_a_user_without_a_device_is_not_sent_anywhere(client, user, name):
    """Two-factor authentication is optional for everybody but staff."""
    client.force_login(user)
    method, url = GATE_URLS[name]

    assert gate_target(client, method, url) in (None, STATUS), name  # (a page with nothing to do)


def test_the_gate_remembers_where_the_user_was_going(client, staff):
    client.force_login(staff)
    url = f"{reverse('catalog:source_list')}?q=fediaf"

    response = client.get(url)

    assert response["Location"] == f"{SETUP}?{urlencode({'next': url})}"


def test_a_post_is_sent_to_the_gate_without_a_return_address(client, staff):
    client.force_login(staff)

    response = client.post(reverse("animals:create"), {"name": "Rex"})

    assert response.status_code == 302 and response["Location"] == SETUP


def test_static_files_and_unknown_paths_are_not_redirected(client, staff):
    client.force_login(staff)

    assert client.get("/static/css/app.css").status_code == 404  # (not served in tests)
    assert client.get("/neexistuje/").status_code == 302  # the gate comes first for staff


def test_anonymous_visitors_are_not_touched_by_the_gate(client):
    assert client.get(reverse("core:home")).status_code == 200
    assert client.get(reverse("catalog:source_list")).status_code == 200
    assert client.get(DASHBOARD).status_code == 302
    assert client.get(DASHBOARD)["Location"].startswith(LOGIN)


@override_settings(REQUIRE_2FA_FOR_STAFF=False)
def test_when_the_requirement_is_off_staff_without_a_device_is_not_forced(client, staff):
    client.force_login(staff)

    assert client.get(DASHBOARD).status_code == 200


@override_settings(REQUIRE_2FA_FOR_STAFF=False)
def test_when_the_requirement_is_off_a_staff_user_who_enrolled_must_still_verify(client, staff):
    enroll(staff)
    client.force_login(staff)

    assert gate_target(client, "get", DASHBOARD) == VERIFY


def test_a_device_that_is_not_confirmed_does_not_lock_anybody_in(client, user):
    enroll(user, confirmed=False)
    client.force_login(user)

    assert client.get(DASHBOARD).status_code == 200


def test_removing_the_device_ends_the_verified_state_at_once(client, staff):
    device = log_in_verified(client, staff)
    assert client.get(DASHBOARD).status_code == 200

    device.delete()

    assert gate_target(client, "get", DASHBOARD) == SETUP


def test_the_logout_works_in_every_state_and_ends_the_session(client, staff):
    client.force_login(staff)

    response = client.post(LOGOUT)

    assert response.status_code == 302 and "_auth_user_id" not in client.session


# --- Recovery codes -------------------------------------------------------------------------------


def test_new_recovery_codes_need_a_current_code(client, enrolled_user):
    user, device, old = enrolled_user
    verified(client, user)

    wrong = client.post(CODES, {"token": wrong_token(device)})
    assert wrong.status_code == 200 and error_texts(wrong) == [INVALID_TOKEN_MESSAGE]
    assert two_factor.recovery_codes_left(user) == 10
    assert not re.findall(r"<code>[a-z2-7]{4}-", wrong.content.decode())


def test_a_recovery_code_is_not_enough_for_new_recovery_codes(client, enrolled_user):
    user, device, old = enrolled_user
    verified(client, user)

    response = client.post(CODES, {"token": old[0]})

    assert error_texts(response) == [INVALID_TOKEN_MESSAGE]
    assert two_factor.recovery_codes_left(user) == 10


def test_new_recovery_codes_are_shown_once_and_replace_the_old_ones(client, enrolled_user, clock):
    user, device, old = enrolled_user
    verified(client, user)
    clock.advance(0)

    response = client.post(CODES, {"token": totp_token(device, steps=1)})

    assert response.status_code == 200
    new = re.findall(r"<code>([a-z2-7]{4}-[a-z2-7]{4})</code>", response.content.decode())
    assert len(new) == 10 and not set(new) & set(old)
    assert "Dosavadní už neplatí" in response.content.decode()
    assert two_factor.recovery_codes_left(user) == 10
    again = client.get(CODES).content.decode()
    assert not any(code in again for code in new)
    other = Client()
    sign_in(other, user)
    assert other.post(VERIFY, {"token": old[0]}).status_code == 200  # old code: refused
    clock.advance(10)
    assert other.post(VERIFY, {"token": new[0]}).status_code == 302


def test_new_recovery_codes_need_a_device(client, staff, user):
    client.force_login(user)

    assert client.get(CODES)["Location"] == STATUS


# --- Switching off --------------------------------------------------------------------------------


def test_staff_cannot_switch_it_off(client, staff):
    log_in_verified(client, staff)

    assert client.get(DISABLE).status_code == 403
    assert client.post(DISABLE, {"password": PASSWORD, "token": "123456"}).status_code == 403
    assert two_factor.confirmed_device(staff) is not None


def test_an_optional_user_needs_the_password_and_a_code_to_switch_it_off(client, enrolled_user):
    user, device, _ = enrolled_user
    verified(client, user)
    page = client.get(DISABLE).content.decode()
    assert 'name="password"' in page and 'name="token"' in page

    wrong_password = client.post(
        DISABLE, {"password": OTHER_PASSWORD, "token": totp_token(device, steps=1)}
    )
    assert "Heslo není správné." in wrong_password.content.decode()
    wrong_code = client.post(DISABLE, {"password": PASSWORD, "token": wrong_token(device)})
    assert error_texts(wrong_code) == [INVALID_TOKEN_MESSAGE]
    assert two_factor.confirmed_device(user) is not None


def test_switching_off_removes_every_device_and_the_gate(client, enrolled_user):
    user, device, _ = enrolled_user
    verified(client, user)

    response = client.post(DISABLE, {"password": PASSWORD, "token": totp_token(device, steps=1)})

    assert response.status_code == 302 and response["Location"] == STATUS
    assert not TOTPDevice.objects.filter(user=user).exists()
    assert not StaticDevice.objects.filter(user=user).exists()
    other = Client()
    sign_in(other, user)
    assert other.get(DASHBOARD).status_code == 200  # a password is enough again


def test_switching_off_without_a_device_goes_to_the_status_page(client, user):
    client.force_login(user)

    assert client.get(DISABLE)["Location"] == STATUS


# --- The status page and the account page ---------------------------------------------------------


def test_status_of_an_account_without_two_factor(client, user):
    client.force_login(user)

    content = client.get(STATUS).content.decode()

    assert "Vypnuto" in content and "ne, je dobrovolné" in content
    assert SETUP in content and DISABLE not in content


def test_status_of_a_staff_account_says_it_is_mandatory_and_offers_no_switch_off(client, staff):
    log_in_verified(client, staff)

    content = client.get(STATUS).content.decode()

    assert "Zapnuto" in content and "pro správce aplikace je povinné" in content
    assert DISABLE not in content and CODES in content


def test_the_status_page_warns_when_the_recovery_codes_run_out(client, enrolled_user):
    user, _, codes = enrolled_user
    verified(client, user)
    StaticDevice.objects.get(user=user).token_set.exclude(
        token__in=[c.replace("-", "") for c in codes[:2]]
    ).delete()

    assert "Zbývá vám málo záložních kódů" in client.get(STATUS).content.decode()


def test_the_account_page_shows_the_state_with_icon_and_text(client, user, staff):
    client.force_login(user)
    assert "ⓘ" in client.get(reverse("accounts:profile")).content.decode()
    assert "vypnuto" in client.get(reverse("accounts:profile")).content.decode()

    other = Client()
    log_in_verified(other, staff)
    content = other.get(reverse("accounts:profile")).content.decode()
    assert "✓" in content and "zapnuto" in content and STATUS in content


# --- Throttling -----------------------------------------------------------------------------------


def test_repeated_failures_lock_out_the_right_code_for_a_while(client, enrolled_user, clock):
    user, device, _ = enrolled_user
    sign_in(client, user)
    for attempt in range(3):
        if attempt:
            clock.advance(10)  # the wait is over before the next attempt is made
        client.post(VERIFY, {"token": wrong_token(device)})
    device.refresh_from_db()
    assert device.throttling_failure_count == 3  # the next attempt may come after 2 * 2**2 = 8 s

    too_soon = client.post(VERIFY, {"token": totp_token(device)})
    assert error_texts(too_soon) == [INVALID_TOKEN_MESSAGE]  # right code, still refused
    clock.advance(9)
    ok = client.post(VERIFY, {"token": totp_token(device, steps=1)})
    assert ok.status_code == 302


def test_throttling_does_not_depend_on_the_session_or_the_client(client, enrolled_user):
    user, device, _ = enrolled_user
    sign_in(client, user)
    client.post(VERIFY, {"token": wrong_token(device)})
    other = Client()
    sign_in(other, user)

    assert error_texts(other.post(VERIFY, {"token": totp_token(device)})) == [INVALID_TOKEN_MESSAGE]


# --- django-axes: a locked-out account cannot pass or change the second factor --------------------


def lock_out(user, **extra):
    attacker = Client()
    for _ in range(settings.AXES_FAILURE_LIMIT):
        sign_in(attacker, user, OTHER_PASSWORD, **extra)
    return attacker


def test_a_locked_out_account_cannot_sign_in_so_it_has_no_session_to_verify(client, enrolled_user):
    user, device, _ = enrolled_user
    lock_out(user)

    assert sign_in(client, user).status_code == 429  # even the right password
    response = client.post(VERIFY, {"token": totp_token(device)})

    assert response.status_code == 302 and response["Location"].startswith(LOGIN)
    assert DEVICE_ID_SESSION_KEY not in client.session


def test_a_session_that_exists_cannot_verify_while_the_client_is_locked_out(client, enrolled_user):
    user, device, _ = enrolled_user
    sign_in(client, user)  # the password was right: a session exists
    lock_out(user)  # then the same address fails five times for this account

    response = client.post(VERIFY, {"token": totp_token(device)})

    assert response.status_code == 429
    assert "Přihlášení je dočasně zablokováno" in response.content.decode()
    assert DEVICE_ID_SESSION_KEY not in client.session
    assert client.get(DASHBOARD).status_code == 302  # still not verified


def test_a_locked_out_client_cannot_use_a_recovery_code_either(client, enrolled_user):
    user, _, codes = enrolled_user
    sign_in(client, user)
    lock_out(user)

    assert client.post(VERIFY, {"token": codes[0]}).status_code == 429
    assert two_factor.recovery_codes_left(user) == 10


def test_a_locked_out_client_cannot_change_the_second_factor(client, enrolled_user):
    user, device, codes = enrolled_user
    verified(client, user)
    lock_out(user)

    assert client.post(CODES, {"token": totp_token(device, steps=1)}).status_code == 429
    assert (
        client.post(
            DISABLE, {"password": PASSWORD, "token": totp_token(device, steps=1)}
        ).status_code
        == 429
    )
    assert client.post(SETUP, {"token": "123456"}).status_code == 429
    assert two_factor.confirmed_device(user) is not None
    assert two_factor.recovery_codes_left(user) == 10


def test_the_lockout_of_one_address_does_not_block_another(client, enrolled_user):
    user, device, _ = enrolled_user
    sign_in(client, user, REMOTE_ADDR="10.0.0.9")
    lock_out(user)  # from 127.0.0.1

    response = client.post(VERIFY, {"token": totp_token(device)}, REMOTE_ADDR="10.0.0.9")

    assert response.status_code == 302


def test_the_password_lockout_is_unchanged_by_failed_codes(client, enrolled_user, clock):
    """Failed codes are throttled by django-otp; they do not count towards the password lockout."""
    user, device, _ = enrolled_user
    sign_in(client, user)
    for _ in range(settings.AXES_FAILURE_LIMIT + 2):
        client.post(VERIFY, {"token": wrong_token(device)})
        clock.advance(10_000)

    assert client.post(VERIFY, {"token": totp_token(device)}).status_code == 302
    fresh = Client()
    assert sign_in(fresh, user).status_code == 302  # the account is not locked out


# --- Markup: strict CSP and accessible forms ------------------------------------------------------


def test_no_page_of_the_flow_has_inline_code_and_all_carry_the_csp(client, enrolled_user, clock):
    user, device, _ = enrolled_user
    other = Client()
    sign_in(other, user)
    rendered = {
        "verify": other.get(VERIFY),
        "verify (error)": other.post(VERIFY, {"token": wrong_token(device)}),
    }
    clock.advance(10)  # (the wrong code above started a back-off)
    verified(client, user)
    rendered.update(
        {
            "status": client.get(STATUS),
            "setup (replace)": client.get(SETUP),
            "new codes": client.get(CODES),
            "disable": client.get(DISABLE),
            "codes": client.post(CODES, {"token": totp_token(device, steps=1)}),
        }
    )
    fresh = Client()
    fresh.force_login(User.objects.create_user("another@example.cz", PASSWORD))
    rendered["setup (first time)"] = fresh.get(SETUP)

    for name, response in rendered.items():
        content = response.content.decode()
        assert response.status_code == 200, name
        assert "style=" not in content.replace('class="', "") or "<svg" in content, name
        assert "<script" not in content and "<style" not in content, name
        assert " onclick=" not in content and "javascript:" not in content, name
        policy = response["Content-Security-Policy"]
        assert "script-src 'self'" in policy and "style-src 'self'" in policy, name
        assert "no-store" in response["Cache-Control"], name


def test_every_visible_input_has_a_label(client, enrolled_user):
    user, device, _ = enrolled_user
    verified(client, user)
    pages = {
        "setup": client.get(SETUP),
        "new codes": client.get(CODES),
        "disable": client.get(DISABLE),
    }
    other = Client()
    sign_in(other, user)
    pages["verify"] = other.get(VERIFY)

    for name, response in pages.items():
        content = response.content.decode()
        inputs = re.findall(r"<input\b[^>]*>", content)
        visible = [i for i in inputs if 'type="hidden"' not in i]
        assert visible, name
        for tag in visible:
            field_id = re.search(r'\bid="([^"]+)"', tag).group(1)
            assert f'for="{field_id}"' in content, (name, tag)
        # The code field asks the browser for a one-time code and does not capitalise or check
        # the spelling of a recovery code.
        assert 'autocomplete="one-time-code"' in content and 'spellcheck="false"' in content, name


def test_the_state_is_shown_by_icon_text_and_colour(client, user, staff):
    client.force_login(user)
    off = client.get(STATUS).content.decode()
    other = Client()
    log_in_verified(other, staff)
    on = other.get(STATUS).content.decode()

    assert 'class="status status--info"' in off and 'aria-hidden="true">ⓘ</span>' in off
    assert "Vypnuto" in off
    assert 'class="status status--success"' in on and 'aria-hidden="true">✓</span>' in on
    assert "Zapnuto" in on


def test_the_qr_code_has_a_text_alternative(client, user):
    client.force_login(user)

    content = client.get(SETUP).content.decode()

    assert 'role="img" aria-label="QR kód pro aplikaci"' in content
    assert "Nelze skenovat? Zadejte v aplikaci ručně" in content  # the secret in text
