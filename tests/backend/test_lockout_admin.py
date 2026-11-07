"""Lockout management in the administration (docs/14 §14.13): the list of failed sign-in
counters says who is locked now, and *Odemknout* unlocks with axes' own reset function.

The attempts are made by the real sign-in page, so django-axes itself writes the counters and
locks the account; nothing here fakes what axes decides."""

import re
from datetime import timedelta

import pytest
from axes.models import AccessAttempt
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.roles import Role
from backoffice.models import AdminAccessAction as Action
from backoffice.models import AdminAccessLog
from tests.backend.helpers import PASSWORD, log_in_verified

pytestmark = pytest.mark.django_db

SUPPORT = Role.SUPPORT_ADMIN.value
ROLES = ["anonymous", "owner", "vet", SUPPORT, "data_curator", "nutrition_reviewer", "superuser"]
STAFF = {SUPPORT, "data_curator", "nutrition_reviewer", "superuser"}
ALLOWED = {SUPPORT, "superuser"}
LIMIT = 5  # settings.AXES_FAILURE_LIMIT, asserted below


def list_url() -> str:
    return reverse("admin:axes_accessattempt_changelist")


def fail_login(email: str, times: int = 1, *, ip: str = "10.1.1.1", agent: str = "Browser A"):
    """Fail the sign-in ``times`` times from ``ip`` with ``agent``: real counters made by axes."""
    client = Client()
    response = None
    for _ in range(times):
        response = client.post(
            reverse("accounts:login"),
            {"email": email, "password": "špatné-heslo-123"},
            REMOTE_ADDR=ip,
            HTTP_USER_AGENT=agent,
        )
    return response


def can_log_in(email: str, *, ip: str = "10.1.1.1", agent: str = "Browser A") -> bool:
    response = Client().post(
        reverse("accounts:login"),
        {"email": email, "password": PASSWORD},
        REMOTE_ADDR=ip,
        HTTP_USER_AGENT=agent,
    )
    return response.status_code == 302


@pytest.fixture
def victim(make_user):
    return make_user("zamceny@example.cz")


@pytest.fixture
def support_client(client, make_user):
    log_in_verified(client, make_user("podpora@example.cz", roles=(Role.SUPPORT_ADMIN,)))
    return client


@pytest.fixture
def client_for(make_user, superuser):
    def build(role: str) -> Client:
        client = Client()
        if role == "anonymous":
            return client
        user = superuser if role == "superuser" else make_user(f"{role}@example.cz", roles=(role,))
        log_in_verified(client, user)
        return client

    return build


def test_the_failure_limit_is_five():
    from django.conf import settings

    assert settings.AXES_FAILURE_LIMIT == LIMIT


# --- The list -----------------------------------------------------------------------------------


def test_the_columns_are_the_account_the_address_the_failures_and_the_time(support_client, victim):
    fail_login(victim.email, 2)

    response = support_client.get(list_url())
    content = response.content.decode()

    assert response.status_code == 200
    headers = re.findall(r'<div class="text"><a href="[^"]*">([^<]+)</a></div>', content)
    assert headers == ["E-mail", "IP adresa", "Neúspěšných pokusů", "Poslední pokus"]
    # The state of the lock comes right after the account (not sortable: it is computed from the
    # whole group of counters), so it is visible without scrolling.
    columns = re.findall(r'<th scope="col" class="[^"]*?(column-\w+)', content)
    assert columns[:2] == ["column-username", "column-locked"]


def test_an_account_is_locked_exactly_when_axes_locks_it(support_client, victim):
    fail_login(victim.email, LIMIT - 1)
    below = support_client.get(list_url()).content.decode()

    fail_login(victim.email, 1)  # the fifth failure
    locked = support_client.get(list_url()).content.decode()

    assert "zbývá pokusů: 1" in below and "barf-status--danger" not in below
    assert 'barf-status--danger"><span aria-hidden="true">⛔</span> zamčeno' in locked
    assert can_log_in(victim.email) is False  # axes really refuses the correct password now


def test_a_failure_counts_towards_the_limit_over_all_browsers_of_an_address(support_client, victim):
    """Axes adds the counters of one e-mail and address over browsers; so must the column."""
    fail_login(victim.email, 3, agent="Browser A")
    fail_login(victim.email, 2, agent="Browser B")

    content = support_client.get(list_url()).content.decode()

    assert AccessAttempt.objects.count() == 2
    assert content.count("barf-status--danger") == 2  # both counters of the locked pair
    assert can_log_in(victim.email, agent="Browser C") is False


def test_another_address_is_not_locked_with_it(support_client, victim):
    fail_login(victim.email, LIMIT, ip="10.1.1.1")
    fail_login(victim.email, 2, ip="10.2.2.2")

    content = support_client.get(list_url()).content.decode()

    assert content.count("barf-status--danger") == 1
    assert "zbývá pokusů: 3" in content
    assert can_log_in(victim.email, ip="10.2.2.2") is True


def test_an_expired_lock_is_shown_as_expired_and_axes_agrees(support_client, victim, settings):
    fail_login(victim.email, LIMIT)
    AccessAttempt.objects.update(
        attempt_time=timezone.now() - settings.AXES_COOLOFF_TIME - timedelta(minutes=1)
    )

    content = support_client.get(list_url()).content.decode()

    assert "zámek vypršel" in content and "barf-status--danger" not in content
    assert can_log_in(victim.email) is True


def test_a_lock_that_just_has_not_expired_is_still_a_lock(support_client, victim, settings):
    fail_login(victim.email, LIMIT)
    AccessAttempt.objects.update(
        attempt_time=timezone.now() - settings.AXES_COOLOFF_TIME + timedelta(minutes=1)
    )

    assert "barf-status--danger" in support_client.get(list_url()).content.decode()
    assert can_log_in(victim.email) is False


def test_without_a_cool_off_a_lock_never_expires(support_client, victim, settings):
    fail_login(victim.email, LIMIT)
    AccessAttempt.objects.update(attempt_time=timezone.now() - timedelta(days=400))
    settings.AXES_COOLOFF_TIME = None

    assert "barf-status--danger" in support_client.get(list_url()).content.decode()


def test_the_filter_on_the_lock(support_client, make_user, victim):
    other = make_user("volny@example.cz")
    fail_login(victim.email, LIMIT)
    fail_login(other.email, 2)

    locked = support_client.get(list_url(), {"zamceno": "ano"}).content.decode()
    free = support_client.get(list_url(), {"zamceno": "ne"}).content.decode()

    assert victim.email in locked and other.email not in locked
    assert other.email in free and victim.email not in free


def test_the_filter_follows_the_cool_off_not_the_row(support_client, victim, settings):
    fail_login(victim.email, LIMIT)
    AccessAttempt.objects.update(
        attempt_time=timezone.now() - settings.AXES_COOLOFF_TIME - timedelta(minutes=1)
    )

    assert victim.email not in support_client.get(list_url(), {"zamceno": "ano"}).content.decode()
    assert victim.email in support_client.get(list_url(), {"zamceno": "ne"}).content.decode()


def test_the_list_can_be_searched_by_account_and_address(support_client, make_user, victim):
    other = make_user("jiny@example.cz")
    fail_login(victim.email, 1, ip="10.1.1.1")
    fail_login(other.email, 1, ip="10.9.9.9")

    by_account = support_client.get(list_url(), {"q": "zamceny"}).content.decode()
    by_address = support_client.get(list_url(), {"q": "10.9.9"}).content.decode()

    assert victim.email in by_account and other.email not in by_account
    assert other.email in by_address and victim.email not in by_address


def test_the_submitted_form_data_is_not_shown(support_client, victim):
    fail_login(victim.email, 1)
    AccessAttempt.objects.update(
        post_data="email=zamceny@example.cz&password=tajne-heslo-v-datech",
        get_data="token=tajny-token-v-adrese",
        http_accept="tajny-accept",
    )
    row = AccessAttempt.objects.get()

    pages = [
        support_client.get(list_url()).content.decode(),
        support_client.get(
            reverse("admin:axes_accessattempt_change", args=[row.pk])
        ).content.decode(),
    ]

    for content in pages:
        for secret in ("tajne-heslo-v-datech", "tajny-token-v-adrese", "tajny-accept"):
            assert secret not in content


def test_the_detail_page_is_read_only_and_says_if_the_account_is_locked(support_client, victim):
    fail_login(victim.email, LIMIT)
    row = AccessAttempt.objects.get()
    url = reverse("admin:axes_accessattempt_change", args=[row.pk])

    response = support_client.get(url)

    assert response.status_code == 200
    assert "zamčeno" in response.content.decode()
    assert 'name="username"' not in response.content.decode()
    assert support_client.post(url, {"username": "x"}).status_code == 403


def test_the_list_costs_the_same_queries_for_one_counter_and_for_many(support_client, make_user):
    fail_login(make_user("a0@example.cz").email, 1)
    with CaptureQueriesContext(connection) as one:
        support_client.get(list_url())
    for number in range(1, 8):
        fail_login(make_user(f"a{number}@example.cz").email, number % 6 + 1, ip=f"10.3.3.{number}")
    with CaptureQueriesContext(connection) as many:
        support_client.get(list_url())

    assert len(many) == len(one)


def test_the_names_are_czech(support_client, victim):
    content = support_client.get(list_url()).content.decode()

    assert "počítadla neúspěšných přihlášení" in content.lower()
    assert "Zámky přihlášení" in content
    assert "Access attempt" not in content and "Failed Logins" not in content


# --- The role x action matrix ---------------------------------------------------------------------


def expected_status(role: str) -> int:
    if role in ALLOWED:
        return 200
    return 403 if role in STAFF else 302


@pytest.mark.parametrize("role", ROLES)
def test_who_sees_the_list(client_for, victim, role):
    fail_login(victim.email, 1)

    response = client_for(role).get(list_url())

    assert response.status_code == expected_status(role)
    assert (victim.email in response.content.decode()) == (role in ALLOWED)


@pytest.mark.parametrize("role", ROLES)
def test_who_unlocks(client_for, victim, role):
    fail_login(victim.email, LIMIT)
    row = AccessAttempt.objects.get()

    response = client_for(role).post(
        list_url(), {"action": "unlock_selected", "_selected_action": [row.pk], "index": "0"}
    )

    if role in ALLOWED:
        assert response.status_code == 302
        assert not AccessAttempt.objects.exists()
    else:
        assert response.status_code == expected_status(role)
        assert AccessAttempt.objects.filter(pk=row.pk).exists()


def test_a_staff_member_with_the_view_permission_only_cannot_unlock(client, make_user, victim):
    from django.contrib.auth.models import Permission

    viewer = make_user("revizor@example.cz", roles=(Role.DATA_CURATOR,))
    viewer.user_permissions.add(Permission.objects.get(codename="view_accessattempt"))
    log_in_verified(client, viewer)
    fail_login(victim.email, LIMIT)
    row = AccessAttempt.objects.get()

    page = client.get(list_url())
    client.post(
        list_url(), {"action": "unlock_selected", "_selected_action": [row.pk], "index": "0"}
    )

    assert page.status_code == 200 and 'value="unlock_selected"' not in page.content.decode()
    assert AccessAttempt.objects.filter(pk=row.pk).exists()


# --- Unlocking ------------------------------------------------------------------------------------


def unlock(client, *rows):
    return client.post(
        list_url(),
        {"action": "unlock_selected", "_selected_action": [r.pk for r in rows], "index": "0"},
    )


def test_unlocking_lets_the_account_sign_in_again(support_client, victim):
    fail_login(victim.email, LIMIT)
    assert can_log_in(victim.email) is False
    row = AccessAttempt.objects.get()

    response = unlock(support_client, row)

    assert response.status_code == 302
    assert not AccessAttempt.objects.exists()
    assert can_log_in(victim.email) is True


def test_unlocking_uses_the_reset_function_of_axes(support_client, victim, monkeypatch):
    calls = []
    import axes.utils

    real = axes.utils.reset
    from backoffice import third_party_admin

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(third_party_admin, "axes_reset", spy)
    fail_login(victim.email, 2)

    unlock(support_client, AccessAttempt.objects.get())

    assert calls == [{"username": victim.email}]


def test_the_message_counts_the_accounts_and_the_counters(support_client, make_user, victim):
    other = make_user("druhy@example.cz")
    fail_login(victim.email, 2, agent="A")
    fail_login(victim.email, 1, agent="B")
    fail_login(other.email, 1)

    response = unlock(support_client, *AccessAttempt.objects.all())

    messages = [str(m) for m in response.wsgi_request._messages]
    assert messages == ["Odemčeno účtů: 2 (smazaných počítadel: 3)."]


def test_unlocking_clears_the_account_on_every_address_but_nobody_else(
    support_client, make_user, victim
):
    other = make_user("jiny@example.cz")
    fail_login(victim.email, LIMIT, ip="10.1.1.1")
    fail_login(victim.email, 1, ip="10.2.2.2")
    fail_login(other.email, LIMIT, ip="10.1.1.1")

    unlock(support_client, AccessAttempt.objects.get(username=victim.email, ip_address="10.1.1.1"))

    assert list(AccessAttempt.objects.values_list("username", flat=True)) == [other.email]
    assert can_log_in(victim.email, ip="10.2.2.2") is True
    assert can_log_in(other.email) is False  # still locked


def test_a_counter_without_an_account_name_clears_nothing_else(support_client, victim):
    """``reset`` without an e-mail would remove every counter: the action must not call it."""
    fail_login(victim.email, LIMIT)
    nameless = AccessAttempt.objects.create(
        username=None, ip_address="10.8.8.8", user_agent="x", failures_since_start=2
    )

    response = unlock(support_client, nameless)

    messages = [str(m) for m in response.wsgi_request._messages]
    assert "Odemčeno účtů: 0 (smazaných počítadel: 0)." in messages
    assert "Přeskočeno počítadel bez e-mailu: 1." in messages
    assert AccessAttempt.objects.count() == 2
    assert can_log_in(victim.email) is False


def test_unlocking_is_written_to_the_access_log_for_every_removed_counter(
    support_client, make_user, victim
):
    AdminAccessLog.objects.all().delete()
    fail_login(victim.email, 2, agent="A")
    fail_login(victim.email, 1, agent="B")
    selected = AccessAttempt.objects.get(user_agent="A")
    removed = sorted(str(pk) for pk in AccessAttempt.objects.values_list("pk", flat=True))

    unlock(support_client, selected)

    rows = AdminAccessLog.objects.filter(action=Action.UNLOCK)
    assert sorted(r.object_pk for r in rows) == removed
    assert {(r.app_label, r.model, r.staff_email) for r in rows} == {
        ("axes", "accessattempt", "podpora@example.cz")
    }
    assert not AdminAccessLog.objects.filter(action=Action.DELETE).exists()
    assert not AdminAccessLog.objects.filter(action=Action.CHANGE).exists()


def test_the_log_records_the_unlock_even_when_the_counters_are_gone_already(support_client, victim):
    fail_login(victim.email, 1)
    row = AccessAttempt.objects.get()
    AccessAttempt.objects.all().delete()  # unlocked by somebody else meanwhile
    AdminAccessLog.objects.all().delete()

    response = unlock(support_client, row)

    assert response.status_code == 302
    assert [r.action for r in AdminAccessLog.objects.all()] == [Action.UNLOCK]


def test_deleting_all_through_the_standard_action_is_not_offered(support_client, victim):
    fail_login(victim.email, 1)

    content = support_client.get(list_url()).content.decode()

    assert 'value="unlock_selected"' in content
    assert 'value="delete_selected"' not in content
    assert "Odemknout" in content
