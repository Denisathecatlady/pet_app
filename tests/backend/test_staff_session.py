"""Idle and absolute time limits of staff sessions (docs/14 §14.5). Time is moved by patching
``accounts.session_policy.now_seconds``, the one function the policy reads."""

import pytest
from django.conf import settings
from django.contrib.auth.models import Group
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django_otp import DEVICE_ID_SESSION_KEY

from accounts import session_policy
from accounts.roles import Role
from accounts.session_policy import (
    IDLE,
    SESSION_LAST_SEEN,
    SESSION_LOGIN_AT,
    TOO_OLD,
    duration_text,
    expiry_message,
)
from tests.backend.helpers import PASSWORD, enroll, log_in_verified

pytestmark = pytest.mark.django_db

IDLE_LIMIT = 1800
MAX_LIMIT = 43200
PAGE = reverse("core:dashboard")
LOGIN = reverse("accounts:login")


class Time:
    def __init__(self, monkeypatch, start: int = 1_800_000_000):
        self.now = start
        monkeypatch.setattr(session_policy, "now_seconds", lambda: self.now)

    def advance(self, seconds: int) -> None:
        self.now += seconds


@pytest.fixture
def time(monkeypatch) -> Time:
    return Time(monkeypatch)


@pytest.fixture
def staff(make_staff):
    return make_staff()


def is_signed_in(client) -> bool:
    return "_auth_user_id" in client.session


def test_the_defaults_are_thirty_minutes_and_twelve_hours():
    assert settings.STAFF_SESSION_IDLE_SECONDS == IDLE_LIMIT
    assert settings.STAFF_SESSION_MAX_SECONDS == MAX_LIMIT


def test_signing_in_records_the_start_in_the_session(client, staff, time):
    log_in_verified(client, staff)

    assert client.session[SESSION_LOGIN_AT] == client.session[SESSION_LAST_SEEN] == time.now


def test_a_staff_session_survives_activity_within_the_idle_limit(client, staff, time):
    log_in_verified(client, staff)

    for _ in range(5):
        time.advance(IDLE_LIMIT - 1)
        assert client.get(PAGE).status_code == 200

    assert is_signed_in(client)


def test_staff_is_signed_out_after_the_idle_limit(client, staff, time):
    log_in_verified(client, staff)
    time.advance(IDLE_LIMIT + 1)

    response = client.get(PAGE)

    assert response.status_code == 302
    assert response["Location"] == f"{LOGIN}?next={PAGE}"
    assert not is_signed_in(client)


def test_exactly_at_the_idle_limit_the_session_still_lives(client, staff, time):
    log_in_verified(client, staff)
    time.advance(IDLE_LIMIT)

    assert client.get(PAGE).status_code == 200


def test_the_login_page_says_why(client, staff, time):
    log_in_verified(client, staff)
    time.advance(IDLE_LIMIT + 1)

    page = client.get(PAGE, follow=True)

    content = page.content.decode()
    assert "Z bezpečnostních důvodů jsme vás odhlásili" in content
    assert "déle než 30 minut nečinní" in content and "Přihlaste se prosím znovu" in content
    assert page.redirect_chain[-1][0] == f"{LOGIN}?next={PAGE}"
    # The message is shown once.
    assert "Z bezpečnostních důvodů" not in client.get(LOGIN).content.decode()


def test_activity_does_not_extend_the_absolute_limit(client, staff, time):
    log_in_verified(client, staff)
    for _ in range(28):  # 28 x 25 min = 11 h 40 min, never idle for long
        time.advance(25 * 60)
        assert client.get(PAGE).status_code == 200

    time.advance(25 * 60)  # 12 h 05 min after the sign-in
    response = client.get(PAGE, follow=True)

    assert not is_signed_in(client)
    assert "od přihlášení uplynulo více než 12 hodin" in response.content.decode()


def test_the_absolute_limit_is_measured_from_the_sign_in_not_the_last_request(client, staff, time):
    log_in_verified(client, staff)
    for _ in range(20):  # 20 x 29 min = 9 h 40 min of activity
        time.advance(29 * 60)
        assert client.get(PAGE).status_code == 200
    login_at = client.session[SESSION_LOGIN_AT]
    time.now = login_at + MAX_LIMIT - 1
    session = client.session
    session[SESSION_LAST_SEEN] = time.now - 5  # (active right before)
    session.save()
    assert client.get(PAGE).status_code == 200

    time.now = login_at + MAX_LIMIT + 1
    assert client.get(PAGE).status_code == 302
    assert not is_signed_in(client)


def test_a_post_is_sent_to_the_login_without_a_return_address(client, staff, time):
    log_in_verified(client, staff)
    time.advance(IDLE_LIMIT + 1)

    response = client.post(reverse("animals:create"), {"name": "Rex"})

    assert response.status_code == 302 and response["Location"] == LOGIN


def test_the_return_address_keeps_the_query_string(client, staff, time):
    log_in_verified(client, staff)
    time.advance(IDLE_LIMIT + 1)

    response = client.get(f"{reverse('catalog:source_list')}?q=fediaf")

    assert response["Location"] == f"{LOGIN}?next=/zdroje/%3Fq%3Dfediaf"


def test_the_admin_is_covered_too(client, staff, time):
    log_in_verified(client, staff)
    time.advance(IDLE_LIMIT + 1)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 302 and response["Location"].startswith(LOGIN)


def test_a_superuser_is_staff_and_covered(client, superuser, time):
    log_in_verified(client, superuser)
    time.advance(IDLE_LIMIT + 1)

    assert client.get(PAGE).status_code == 302 and not is_signed_in(client)


def test_the_second_factor_is_gone_with_the_session(client, staff, time):
    log_in_verified(client, staff)
    time.advance(IDLE_LIMIT + 1)
    client.get(PAGE)

    client.post(LOGIN, {"email": staff.email, "password": PASSWORD})

    # A new sign-in is a new session: the password alone does not open it.
    assert client.get(PAGE)["Location"].startswith(reverse("accounts:two_factor_verify"))


@pytest.mark.parametrize("role", [Role.OWNER, Role.VET])
def test_other_users_are_not_limited(client, make_user, time, role):
    user = make_user("someone@example.cz", roles=(role,))
    client.force_login(user)
    time.advance(MAX_LIMIT * 3)

    assert client.get(PAGE).status_code == 200 and is_signed_in(client)


def test_a_user_who_is_no_longer_staff_is_no_longer_limited(client, staff, time):
    log_in_verified(client, staff)
    staff.groups.clear()
    time.advance(MAX_LIMIT * 2)

    assert client.get(PAGE).status_code == 200


def test_a_user_who_becomes_staff_is_limited_from_their_own_sign_in(client, make_user, time):
    user = make_user("someone@example.cz")
    client.force_login(user)  # the sign-in time is recorded for everybody
    user.groups.add(Group.objects.get(name=Role.SUPPORT_ADMIN))
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = enroll(user).persistent_id  # (second factor passed)
    session.save()
    time.advance(IDLE_LIMIT + 1)

    assert client.get(PAGE).status_code == 302 and not is_signed_in(client)


def test_a_staff_session_without_a_start_time_counts_as_expired(client, staff, time):
    log_in_verified(client, staff)
    session = client.session
    del session[SESSION_LOGIN_AT]
    session.save()

    assert client.get(PAGE).status_code == 302 and not is_signed_in(client)


def test_garbage_in_the_session_counts_as_expired(client, staff, time):
    log_in_verified(client, staff)
    session = client.session
    session[SESSION_LAST_SEEN] = "yesterday"
    session.save()

    assert client.get(PAGE).status_code == 302


def test_every_request_of_a_staff_user_records_the_activity(client, staff, time):
    log_in_verified(client, staff)
    time.advance(600)

    client.get(PAGE)

    assert client.session[SESSION_LAST_SEEN] == time.now
    assert client.session[SESSION_LOGIN_AT] == time.now - 600


def test_the_limits_are_settings(client, staff, time):
    log_in_verified(client, staff)

    with override_settings(STAFF_SESSION_IDLE_SECONDS=60, STAFF_SESSION_MAX_SECONDS=3600):
        time.advance(61)
        assert client.get(PAGE).status_code == 302
    log_in_verified(client, staff)
    with override_settings(STAFF_SESSION_IDLE_SECONDS=600, STAFF_SESSION_MAX_SECONDS=3600):
        for _ in range(7):
            time.advance(590)
            client.get(PAGE)
        assert not is_signed_in(client)  # 7 x 590 s > 3600 s since the sign-in


# --- Unit level -------------------------------------------------------------------------------


def test_expiry_reason_does_not_change_the_session(time):
    started = time.now - 10
    session = {SESSION_LOGIN_AT: started, SESSION_LAST_SEEN: started}

    assert session_policy.expiry_reason(session) is None
    time.advance(IDLE_LIMIT)
    assert session_policy.expiry_reason(session) == IDLE
    assert session == {SESSION_LOGIN_AT: started, SESSION_LAST_SEEN: started}


def test_too_old_wins_over_idle(time):
    session = {SESSION_LOGIN_AT: time.now - MAX_LIMIT - 1, SESSION_LAST_SEEN: time.now - 5000}

    assert session_policy.expiry_reason(session) == TOO_OLD


def test_start_session_ignores_a_request_without_a_session(time):
    session_policy.start_session(RequestFactory().get("/"))  # must not raise


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (30, "30 sekund"),
        (60, "1 minutu"),
        (120, "2 minuty"),
        (1800, "30 minut"),
        (3600, "1 hodinu"),
        (7200, "2 hodiny"),
        (43200, "12 hodin"),
        (90, "90 sekund"),
    ],
)
def test_durations_are_czech(seconds, text):
    assert duration_text(seconds) == text


def test_messages_name_the_limit():
    assert "30 minut" in expiry_message(IDLE)
    assert "12 hodin" in expiry_message(TOO_OLD)
    with override_settings(STAFF_SESSION_IDLE_SECONDS=3600):
        assert "1 hodinu" in expiry_message(IDLE)
