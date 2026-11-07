"""Registrations that wait for activation, in the administration (docs/14 §14.14): the filter, the
action that sends the activation e-mail again and the action that deletes the stale ones through
the one function the daily command uses as well."""

from datetime import timedelta
from io import StringIO

import pytest
from axes.models import AccessAttempt
from django.contrib.admin.models import DELETION, LogEntry
from django.core import mail
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts import services
from accounts.models import User
from accounts.roles import Role
from backoffice.models import AdminAccessAction as Action
from backoffice.models import AdminAccessLog
from tests.backend.helpers import PASSWORD, extract_link, log_in_verified

pytestmark = pytest.mark.django_db

SUPPORT = Role.SUPPORT_ADMIN.value
ROLES = ["anonymous", "owner", "vet", SUPPORT, "data_curator", "nutrition_reviewer", "superuser"]
STAFF = {SUPPORT, "data_curator", "nutrition_reviewer", "superuser"}
ALLOWED = {SUPPORT, "superuser"}
RESEND = "resend_activation_email"
PURGE = "delete_stale_registrations"


def list_url() -> str:
    return reverse("admin:accounts_user_changelist")


def run(client, action, users, **extra):
    data = {
        "action": action,
        "_selected_action": [user.pk for user in users],
        "index": "0",
        **extra,
    }
    return client.post(list_url(), data)


def messages_of(response) -> list[str]:
    return [str(m) for m in response.wsgi_request._messages]


@pytest.fixture
def old(settings):
    """A moment past the retention of unactivated registrations."""
    return timezone.now() - settings.PENDING_ACCOUNT_RETENTION - timedelta(hours=1)


@pytest.fixture
def pending(make_user):
    def factory(email="ceka@example.cz", *, date_joined=None, **fields) -> User:
        fields.setdefault("is_active", False)
        fields.setdefault("activation_pending", True)
        if date_joined is not None:
            fields["date_joined"] = date_joined
        return make_user(email, **fields)

    return factory


@pytest.fixture
def stale(pending, old) -> User:
    return pending("stara@example.cz", date_joined=old)


@pytest.fixture
def support_client(client, make_user):
    log_in_verified(client, make_user("podpora@example.cz", roles=(Role.SUPPORT_ADMIN,)))
    AdminAccessLog.objects.all().delete()
    return client


@pytest.fixture
def root_client(client, superuser):
    log_in_verified(client, superuser)
    AdminAccessLog.objects.all().delete()
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


def exists(user) -> bool:
    return User.objects.filter(pk=user.pk).exists()


# --- The shared function --------------------------------------------------------------------------


def test_the_stale_registrations_are_inactive_pending_and_past_the_retention(
    pending, make_user, old
):
    stale = pending("stara@example.cz", date_joined=old)
    fresh = pending("cerstva@example.cz")
    deactivated = make_user("vypnuty@example.cz", is_active=False, date_joined=old)
    active = make_user("aktivni@example.cz", date_joined=old)

    found = set(services.stale_pending_accounts())

    assert found == {stale}
    assert {fresh, deactivated, active}.isdisjoint(found)


def test_the_cut_off_is_the_retention_and_the_clock_can_be_replaced(pending, settings):
    now = timezone.now()
    just_inside = pending("uvnitr@example.cz", date_joined=now - settings.PENDING_ACCOUNT_RETENTION)
    just_outside = pending(
        "venku@example.cz",
        date_joined=now - settings.PENDING_ACCOUNT_RETENTION - timedelta(seconds=1),
    )

    assert set(services.stale_pending_accounts(now=now)) == {just_outside}
    later = now + timedelta(hours=1)
    assert set(services.stale_pending_accounts(now=later)) == {just_inside, just_outside}


def test_purge_without_a_selection_deletes_every_stale_registration(pending, old, make_user):
    first, second = (
        pending("a@example.cz", date_joined=old),
        pending("b@example.cz", date_joined=old),
    )
    keep = pending("c@example.cz")
    active = make_user("d@example.cz", date_joined=old)

    assert services.purge_pending_accounts() == 2

    assert not exists(first) and not exists(second)
    assert exists(keep) and exists(active)


def test_purge_with_a_selection_deletes_only_the_stale_ones_of_it(pending, old, make_user):
    selected_stale = pending("a@example.cz", date_joined=old)
    other_stale = pending("b@example.cz", date_joined=old)
    fresh = pending("c@example.cz")
    active = make_user("d@example.cz", date_joined=old)
    selection = User.objects.filter(pk__in=[selected_stale.pk, fresh.pk, active.pk])

    deleted = services.purge_pending_accounts(users=selection)

    assert deleted == 1
    assert not exists(selected_stale)
    assert exists(other_stale) and exists(fresh) and exists(active)


def test_purge_never_deletes_what_is_not_stale_whatever_is_passed(make_user, pending, superuser):
    everything = User.objects.all()
    pending("cerstva@example.cz")

    assert services.purge_pending_accounts(users=everything) == 0
    assert exists(superuser)


def test_purge_with_an_empty_selection_deletes_nothing(stale):
    assert services.purge_pending_accounts(users=User.objects.none()) == 0
    assert exists(stale)


def test_the_command_and_the_action_use_the_same_function(support_client, stale, monkeypatch):
    calls = []
    real = services.purge_pending_accounts

    def spy(**kwargs):
        calls.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(services, "purge_pending_accounts", spy)

    call_command("purge_pending_accounts", stdout=StringIO())
    other = User.objects.create_user("jina@example.cz", is_active=False)
    User.objects.filter(pk=other.pk).update(
        activation_pending=True, date_joined=timezone.now() - timedelta(days=30)
    )
    run(support_client, PURGE, [other], post="yes")

    assert len(calls) == 2
    assert "users" not in calls[0] or calls[0]["users"] is None  # the command: everything stale
    assert set(calls[1]) == {"users"}  # the action: the selection


# --- The filter -----------------------------------------------------------------------------------


def test_the_filter_lists_the_registrations_that_wait(support_client, pending, make_user, stale):
    waiting = pending("ceka@example.cz")
    deactivated = make_user("vypnuty@example.cz", is_active=False)
    active = make_user("aktivni@example.cz")

    content = support_client.get(list_url(), {"ceka_na_aktivaci": "ano"}).content.decode()

    assert waiting.email in content and stale.email in content
    assert deactivated.email not in content and active.email not in content


def test_the_filter_for_registrations_past_the_deadline(support_client, pending, stale):
    waiting = pending("ceka@example.cz")

    content = support_client.get(list_url(), {"ceka_na_aktivaci": "po_lhute"}).content.decode()

    assert stale.email in content and waiting.email not in content


def test_the_filter_is_offered_with_its_title_and_choices(support_client, stale):
    content = support_client.get(list_url()).content.decode()

    assert "čeká na aktivaci" in content.lower()
    assert "ano, po lhůtě (smaže se)" in content
    assert "ceka_na_aktivaci=po_lhute" in content


# --- Sending the activation e-mail again ----------------------------------------------------------


def test_the_activation_e_mail_is_sent_again_and_the_link_activates(
    support_client, client, pending
):
    user = pending("ceka@example.cz")
    user.set_password(PASSWORD)
    user.save()

    response = run(support_client, RESEND, [user])

    (message,) = mail.outbox
    assert message.to == [user.email] and message.subject == "[BARF Nutri] Aktivace účtu"
    assert messages_of(response) == ["Aktivační e-mail byl odeslán: 1."]
    link = extract_link(message.body)
    anonymous = Client()
    assert anonymous.get(link).status_code == 200
    assert anonymous.post(link, {"password": PASSWORD}).status_code == 302
    assert User.objects.get(pk=user.pk).is_active


def test_the_second_click_is_throttled_and_the_message_counts_it(support_client, pending):
    first, second = pending("a@example.cz"), pending("b@example.cz")
    run(support_client, RESEND, [first])
    mail.outbox.clear()

    response = run(support_client, RESEND, [first, second])

    assert [m.to for m in mail.outbox] == [["b@example.cz"]]
    messages = messages_of(response)
    assert "Aktivační e-mail byl odeslán: 1." in messages
    assert any(m.startswith("Neodesláno kvůli omezení počtu e-mailů: 1.") for m in messages)


def test_accounts_that_do_not_wait_get_nothing_and_are_counted(support_client, pending, make_user):
    waiting = pending("ceka@example.cz")
    active = make_user("aktivni@example.cz")
    deactivated = make_user("vypnuty@example.cz", is_active=False)

    response = run(support_client, RESEND, [waiting, active, deactivated])

    assert [m.to for m in mail.outbox] == [["ceka@example.cz"]]
    assert "Přeskočeno účtů, které nečekají na aktivaci: 2." in messages_of(response)


def test_only_throttled_ones_say_only_that(support_client, pending):
    user = pending("ceka@example.cz")
    run(support_client, RESEND, [user])
    mail.outbox.clear()

    response = run(support_client, RESEND, [user])

    messages = messages_of(response)
    assert mail.outbox == []
    assert "Aktivační e-mail byl odeslán: 0." in messages
    assert any("Neodesláno kvůli omezení počtu e-mailů: 1." in m for m in messages)


def test_resending_is_written_to_the_access_log_for_the_ones_that_got_it(support_client, pending):
    first, second = pending("a@example.cz"), pending("b@example.cz")

    run(support_client, RESEND, [first, second])

    rows = AdminAccessLog.objects.filter(action=Action.CHANGE)
    assert sorted(r.object_pk for r in rows) == sorted([str(first.pk), str(second.pk)])
    assert LogEntry.objects.filter(change_message="Znovu odeslán aktivační e-mail.").count() == 2


def test_an_action_that_sent_nothing_is_not_logged_as_a_change(support_client, pending, make_user):
    active = make_user("aktivni@example.cz")
    user = pending("ceka@example.cz")
    run(support_client, RESEND, [user])
    mail.outbox.clear()
    AdminAccessLog.objects.all().delete()

    run(support_client, RESEND, [user, active])  # throttled and not waiting: nothing is sent

    assert mail.outbox == []
    assert not AdminAccessLog.objects.filter(action=Action.CHANGE).exists()
    assert {r.action for r in AdminAccessLog.objects.all()} == {Action.VIEW_OBJECT}


@pytest.mark.parametrize("role", ROLES)
def test_who_may_resend(client_for, pending, role):
    user = pending("ceka@example.cz")

    response = run(client_for(role), RESEND, [user])

    if role in ALLOWED:
        assert response.status_code == 302 and len(mail.outbox) == 1
    else:
        assert response.status_code == (403 if role in STAFF else 302)
        assert mail.outbox == []


# --- Deleting the stale registrations -------------------------------------------------------------


def test_the_confirmation_page_shows_the_count_and_deletes_nothing(
    support_client, pending, old, settings
):
    stales = [pending(f"stara{n}@example.cz", date_joined=old) for n in range(3)]
    fresh = pending("cerstva@example.cz")

    response = run(support_client, PURGE, [*stales, fresh])
    content = response.content.decode()

    assert response.status_code == 200
    assert "Registrací ke smazání: 3" in content
    assert f"starší než {settings.PENDING_ACCOUNT_RETENTION.days} dní" in content
    assert "Z vybraných účtů se přeskočí 1" in content
    for user in stales:
        assert user.email in content
    assert (
        fresh.email not in content.split("Z vybraných účtů se přeskočí")[0].split("barf-count")[1]
    )
    assert 'name="post" value="yes"' in content and 'name="action" value="' + PURGE in content
    assert "Trvale smazat registrace" in content
    assert all(exists(user) for user in [*stales, fresh])


def test_the_list_of_the_page_is_limited(support_client, pending, old):
    users = [pending(f"stara{n:02d}@example.cz", date_joined=old) for n in range(23)]

    content = run(support_client, PURGE, users).content.decode()

    assert "Registrací ke smazání: 23" in content
    assert "… a dalších 3" in content
    assert content.count("@example.cz</li>") == 20


def test_confirming_deletes_only_the_stale_registrations(support_client, pending, make_user, old):
    stale_one = pending("a@example.cz", date_joined=old)
    stale_two = pending("b@example.cz", date_joined=old)
    fresh = pending("c@example.cz")
    deactivated = make_user("d@example.cz", is_active=False, date_joined=old)
    active = make_user("e@example.cz", date_joined=old)
    everyone = [stale_one, stale_two, fresh, deactivated, active]

    response = run(support_client, PURGE, everyone, post="yes")

    assert response.status_code == 302
    assert messages_of(response) == ["Smazáno neaktivovaných registrací: 2."]
    assert not exists(stale_one) and not exists(stale_two)
    assert all(exists(user) for user in (fresh, deactivated, active))


def test_a_selection_without_a_stale_registration_deletes_and_shows_nothing(
    support_client, pending, make_user
):
    fresh, active = pending("a@example.cz"), make_user("b@example.cz")

    first = run(support_client, PURGE, [fresh, active])
    second = run(support_client, PURGE, [fresh, active], post="yes")

    for response in (first, second):
        assert response.status_code == 302
        assert any(
            "není žádná neaktivovaná registrace starší než lhůta" in m
            for m in messages_of(response)
        )
    assert exists(fresh) and exists(active)


def test_a_forged_confirmation_cannot_delete_what_is_not_stale(support_client, make_user, pending):
    """The posted keys are not trusted: the age and the state are checked again."""
    active = make_user("aktivni@example.cz")
    fresh = pending("cerstva@example.cz")

    run(support_client, PURGE, [active, fresh], post="yes")

    assert exists(active) and exists(fresh)


def test_the_deletion_removes_the_records_kept_by_e_mail(support_client, stale):
    AccessAttempt.objects.create(
        username=stale.email, ip_address="10.0.0.1", user_agent="x", failures_since_start=1
    )

    run(support_client, PURGE, [stale], post="yes")

    assert not AccessAttempt.objects.filter(username=stale.email).exists()


def test_the_deletion_is_logged_in_both_logs_without_the_e_mail(support_client, stale):
    pk = stale.pk

    run(support_client, PURGE, [stale], post="yes")

    row = AdminAccessLog.objects.get(action=Action.DELETE)
    assert (row.model, row.object_pk, row.staff_email) == ("user", str(pk), "podpora@example.cz")
    entry = LogEntry.objects.get(action_flag=DELETION, object_id=str(pk))
    assert entry.object_repr == "[smazaný záznam]"  # the e-mail is gone from the log of the admin


def test_showing_the_page_is_a_view_of_the_records_not_a_deletion(support_client, stale):
    run(support_client, PURGE, [stale])

    assert [r.action for r in AdminAccessLog.objects.all()] == [Action.VIEW_OBJECT]
    assert exists(stale)


def test_a_superuser_deletes_too_and_may_see_staff_in_the_selection(root_client, stale):
    response = run(root_client, PURGE, [stale], post="yes")

    assert response.status_code == 302 and not exists(stale)


def test_support_cannot_reach_a_staff_account_with_it(support_client, make_user, old):
    """Staff accounts are not in the support list, so they cannot be selected."""
    staff = make_user("kolega@example.cz", roles=(Role.DATA_CURATOR,))
    User.objects.filter(pk=staff.pk).update(
        is_active=False, activation_pending=True, date_joined=old
    )

    run(support_client, PURGE, [staff], post="yes")

    assert exists(staff)


@pytest.mark.parametrize("role", ROLES)
def test_who_may_delete_the_stale_registrations(client_for, pending, old, role):
    user = pending("stara@example.cz", date_joined=old)

    client = client_for(role)
    shown = run(client, PURGE, [user])
    done = run(client, PURGE, [user], post="yes")

    if role in ALLOWED:
        assert shown.status_code == 200
        assert done.status_code == 302 and not exists(user)
    else:
        assert shown.status_code == done.status_code == (403 if role in STAFF else 302)
        assert exists(user)


def test_deleting_selected_users_in_general_is_still_not_offered_to_support(support_client, stale):
    content = support_client.get(list_url()).content.decode()

    assert 'value="delete_selected"' not in content
    assert f'value="{PURGE}"' in content and f'value="{RESEND}"' in content


def test_the_actions_are_named_in_czech(support_client, stale):
    content = support_client.get(list_url()).content.decode()

    assert "Znovu odeslat aktivační e-mail" in content
    assert "Smazat neaktivované registrace starší než lhůta" in content


def test_the_user_list_costs_the_same_queries_with_the_filter_for_few_and_for_many(
    support_client, pending, old
):
    pending("a0@example.cz", date_joined=old)
    with CaptureQueriesContext(connection) as one:
        support_client.get(list_url(), {"ceka_na_aktivaci": "po_lhute"})
    for number in range(1, 9):
        pending(f"a{number}@example.cz", date_joined=old)
    with CaptureQueriesContext(connection) as many:
        support_client.get(list_url(), {"ceka_na_aktivaci": "po_lhute"})

    assert len(many) == len(one)


def test_the_confirmation_page_has_no_inline_script_or_style(support_client, stale):
    content = run(support_client, PURGE, [stale]).content.decode()

    assert "style=" not in content and "<script>" not in content


def test_cancelling_is_a_plain_link_back_to_the_list_with_its_filter(support_client, stale):
    """No script is needed to go back (a page of the application has no inline or loaded
    script besides what the administration itself loads)."""
    url = f"{list_url()}?ceka_na_aktivaci=po_lhute"
    data = {"action": PURGE, "_selected_action": [stale.pk], "index": "0"}

    content = support_client.post(url, data).content.decode()

    assert f'<a href="{url}" class="button cancel-link">Zrušit</a>' in content
    assert "cancel.js" not in content


def test_the_command_still_reports_the_count(stale, capsys):
    call_command("purge_pending_accounts")

    assert "Smazáno neaktivovaných registrací: 1" in capsys.readouterr().out
