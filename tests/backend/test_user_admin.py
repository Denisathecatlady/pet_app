"""The user admin: escalation guards, hidden passwords, the reset-link action (docs/14 §14.4).

Every rule is checked as a role x action matrix: support administrator (and a curator who was
given the user permission by hand, who must be held to the same limits) against superusers."""

import re

import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.urls import NoReverseMatch, reverse

from accounts.models import User
from accounts.roles import Role
from backoffice.models import AdminAccessAction, AdminAccessLog
from tests.backend.helpers import OTHER_PASSWORD, PASSWORD, extract_link, log_in_verified

pytestmark = pytest.mark.django_db


@pytest.fixture
def victim(make_user) -> User:
    return make_user("victim@example.cz", first_name="Jana", last_name="Nováková")


@pytest.fixture
def colleague(make_user) -> User:
    return make_user("colleague@example.cz", roles=(Role.DATA_CURATOR,))


@pytest.fixture
def other_root(make_user) -> User:
    return make_user("other-root@example.cz", roles=(), is_superuser=True)


@pytest.fixture
def limited(client, make_user):
    """Staff who may change users but only as a non-superuser: a support administrator."""
    user = make_user("support@example.cz", roles=(Role.SUPPORT_ADMIN,))
    log_in_verified(client, user)
    client.account = user
    return client


@pytest.fixture
def curator_with_user_permission(client, make_user):
    """A different staff role with the user permissions added by hand: same limits apply."""
    user = make_user("curator-plus@example.cz", roles=(Role.DATA_CURATOR,))
    user.user_permissions.add(*Permission.objects.filter(codename__in=["view_user", "change_user"]))
    log_in_verified(client, user)
    client.account = user
    return client


@pytest.fixture(params=["support", "curator_with_user_permission"])
def non_superuser_client(request):
    """Each kind of staff member who is not a superuser but may change users."""
    return request.getfixturevalue("limited" if request.param == "support" else request.param)


@pytest.fixture
def root_client(client, superuser):
    log_in_verified(client, superuser)
    client.account = superuser
    return client


def change_url(user) -> str:
    return reverse("admin:accounts_user_change", args=[user.pk])


def fresh(user) -> User:
    return User.objects.get(pk=user.pk)


# --- What a non-superuser sees --------------------------------------------------------------


def test_the_list_shows_ordinary_users_but_no_staff(
    non_superuser_client, victim, colleague, other_root, superuser
):
    content = non_superuser_client.get(reverse("admin:accounts_user_changelist")).content.decode()

    assert victim.email in content
    for hidden in (colleague, other_root, superuser):
        assert hidden.email not in content, hidden.email
    # The signed-in account is staff itself, so it is not in the list either.
    assert f'href="{change_url(non_superuser_client.account)}"' not in content


@pytest.mark.parametrize(
    "query", ["q=colleague", "q=other-root", "is_staff__exact=1", "is_superuser__exact=1"]
)
def test_search_and_filters_do_not_reveal_staff(
    non_superuser_client, victim, colleague, other_root, query
):
    content = non_superuser_client.get(
        f"{reverse('admin:accounts_user_changelist')}?{query}"
    ).content.decode()

    assert colleague.email not in content and other_root.email not in content


def test_the_form_of_an_ordinary_user_has_only_the_basic_fields(non_superuser_client, victim):
    content = non_superuser_client.get(change_url(victim)).content.decode()

    for editable in ("first_name", "last_name", "is_active"):
        assert f'name="{editable}"' in content
    for hidden in ("password", "is_superuser", "is_staff", "groups", "user_permissions", "email"):
        assert f'name="{hidden}"' not in content, hidden
    assert victim.password not in content  # not even the hash


def test_the_roles_are_shown_to_a_non_superuser_as_text_only(non_superuser_client, make_user):
    vet = make_user("vet-person@example.cz", roles=(Role.VET,))

    content = non_superuser_client.get(change_url(vet)).content.decode()

    assert "Veterinární lékař" in content and 'name="groups"' not in content


# --- What a non-superuser can change --------------------------------------------------------


def test_names_and_the_active_flag_can_be_changed(non_superuser_client, victim):
    response = non_superuser_client.post(
        change_url(victim), {"first_name": "Eva", "last_name": "Svobodová"}
    )

    assert response.status_code == 302
    changed = fresh(victim)
    assert (changed.first_name, changed.last_name, changed.is_active) == ("Eva", "Svobodová", False)
    entry = LogEntry.objects.get(object_id=str(victim.pk), action_flag=CHANGE)
    assert entry.user == non_superuser_client.account


def test_a_crafted_post_cannot_escalate(non_superuser_client, victim):
    """Fields that are not in the form are ignored, whatever the request contains."""
    curators = Group.objects.get(name=Role.DATA_CURATOR)
    permission = Permission.objects.get(codename="delete_user")

    response = non_superuser_client.post(
        change_url(victim),
        {
            "first_name": "Jana",
            "last_name": "Nováková",
            "is_active": "on",
            "is_superuser": "on",
            "is_staff": "on",
            "groups": [curators.pk],
            "user_permissions": [permission.pk],
            "email": "stolen@example.cz",
            "password": "pbkdf2_sha256$1$a$b",
            "activation_pending": "on",
        },
    )

    assert response.status_code == 302
    after = fresh(victim)
    assert not after.is_superuser and not after.is_staff
    assert not after.groups.filter(name=Role.DATA_CURATOR).exists()
    assert not after.user_permissions.exists()
    assert after.email == "victim@example.cz" and after.password == victim.password
    assert not after.activation_pending


@pytest.mark.parametrize("target", ["colleague", "other_root", "superuser"])
def test_a_non_superuser_cannot_edit_or_deactivate_staff(
    non_superuser_client, request, target, colleague, other_root, superuser
):
    user = request.getfixturevalue(target)

    get = non_superuser_client.get(change_url(user))
    post = non_superuser_client.post(change_url(user), {"first_name": "Hacked", "last_name": "X"})

    assert get.status_code == 302 and post.status_code == 302  # "does not exist"
    after = fresh(user)
    assert after.first_name != "Hacked" and after.is_active


def test_a_non_superuser_cannot_edit_itself(non_superuser_client):
    account = non_superuser_client.account

    response = non_superuser_client.post(
        change_url(account), {"first_name": "Self", "last_name": "Edit", "is_active": "on"}
    )

    assert response.status_code == 302 and fresh(account).first_name != "Self"


def test_the_staff_flag_is_not_posted_into_existence(non_superuser_client, victim):
    non_superuser_client.post(change_url(victim), {"first_name": "A", "is_staff": "on"})
    assert not fresh(victim).is_staff


# --- Deleting -------------------------------------------------------------------------------


def test_a_non_superuser_cannot_delete_users(non_superuser_client, victim):
    page = non_superuser_client.get(reverse("admin:accounts_user_delete", args=[victim.pk]))
    post = non_superuser_client.post(
        reverse("admin:accounts_user_delete", args=[victim.pk]), {"post": "yes"}
    )

    assert page.status_code == 403 and post.status_code == 403
    assert User.objects.filter(pk=victim.pk).exists()


def test_the_bulk_delete_action_is_not_offered_to_a_non_superuser(non_superuser_client, victim):
    url = reverse("admin:accounts_user_changelist")

    content = non_superuser_client.get(url).content.decode()
    post = non_superuser_client.post(
        url, {"action": "delete_selected", "_selected_action": [victim.pk], "post": "yes"}
    )

    assert 'value="delete_selected"' not in content
    assert 'value="send_password_reset_link"' in content
    assert 'value="reset_two_factor"' not in content
    assert post.status_code == 302  # back to the list with "no action selected"
    assert User.objects.filter(pk=victim.pk).exists()


def test_the_delete_permission_is_not_enough_for_a_non_superuser(client, make_user, victim):
    user = make_user("support@example.cz", roles=(Role.SUPPORT_ADMIN,))
    user.user_permissions.add(Permission.objects.get(codename="delete_user"))
    log_in_verified(client, user)

    response = client.post(reverse("admin:accounts_user_delete", args=[victim.pk]), {"post": "yes"})

    assert response.status_code == 403 and User.objects.filter(pk=victim.pk).exists()


def test_a_superuser_can_delete_users_page_and_bulk(root_client, victim, make_user):
    second = make_user("second@example.cz")
    url = reverse("admin:accounts_user_changelist")

    assert 'value="delete_selected"' in root_client.get(url).content.decode()
    assert (
        root_client.post(
            reverse("admin:accounts_user_delete", args=[victim.pk]), {"post": "yes"}
        ).status_code
        == 302
    )
    assert not User.objects.filter(pk=victim.pk).exists()
    response = root_client.post(
        url, {"action": "delete_selected", "_selected_action": [second.pk], "post": "yes"}
    )
    assert response.status_code == 302 and not User.objects.filter(pk=second.pk).exists()


# --- The superuser's form -------------------------------------------------------------------


def test_the_superuser_form_has_the_privilege_fields_but_no_password_and_no_staff_input(
    root_client, victim
):
    content = root_client.get(change_url(victim)).content.decode()

    for present in (
        "email",
        "first_name",
        "last_name",
        "is_active",
        "is_superuser",
        "groups",
        "user_permissions",
    ):
        assert f'name="{present}"' in content, present
    for absent in ("password", "is_staff"):
        assert f'name="{absent}"' not in content, absent
    assert victim.password not in content
    assert "Přístup do administrace" in content  # the derived flag is shown, read-only


def test_the_password_page_does_not_exist(root_client, victim):
    with pytest.raises(NoReverseMatch):
        reverse("admin:auth_user_password_change", args=[victim.pk])
    response = root_client.get(f"{change_url(victim)}password/")
    assert response.status_code in (302, 404)
    assert "password1" not in response.content.decode()


def test_a_superuser_grants_a_staff_role_and_staff_follows(root_client, victim):
    data = {
        "email": victim.email,
        "first_name": "Jana",
        "last_name": "Nováková",
        "is_active": "on",
        "groups": [Group.objects.get(name=Role.SUPPORT_ADMIN).pk],
        "is_staff": "",  # ignored: not a form field
    }

    assert root_client.post(change_url(victim), data).status_code == 302
    assert fresh(victim).is_staff

    data["groups"] = [Group.objects.get(name=Role.OWNER).pk]
    assert root_client.post(change_url(victim), data).status_code == 302
    assert not fresh(victim).is_staff


def test_a_superuser_makes_a_superuser_and_a_posted_staff_flag_is_ignored(root_client, victim):
    data = {
        "email": victim.email,
        "first_name": "",
        "last_name": "",
        "is_active": "on",
        "is_superuser": "on",
    }
    assert root_client.post(change_url(victim), data).status_code == 302
    assert fresh(victim).is_superuser and fresh(victim).is_staff

    del data["is_superuser"]
    assert root_client.post(change_url(victim), data).status_code == 302
    assert not fresh(victim).is_superuser and not fresh(victim).is_staff


def test_a_superuser_gives_individual_permissions(root_client, victim):
    permission = Permission.objects.get(codename="view_user")
    data = {"email": victim.email, "is_active": "on", "user_permissions": [permission.pk]}

    assert root_client.post(change_url(victim), data).status_code == 302
    assert list(fresh(victim).user_permissions.all()) == [permission]


def test_a_superuser_sees_staff_users_and_may_edit_them(root_client, colleague):
    content = root_client.get(reverse("admin:accounts_user_changelist")).content.decode()
    assert colleague.email in content

    data = {"email": colleague.email, "first_name": "Karel", "is_active": ""}
    assert root_client.post(change_url(colleague), data).status_code == 302
    assert fresh(colleague).first_name == "Karel" and not fresh(colleague).is_active


# --- Adding users -----------------------------------------------------------------------------


def test_a_superuser_adds_a_user_without_a_password_and_without_staff(root_client):
    response = root_client.post(reverse("admin:accounts_user_add"), {"email": "New@Example.cz"})

    assert response.status_code == 302
    created = User.objects.get(email="new@example.cz")
    assert not created.has_usable_password() and not created.is_staff and created.is_active
    content = root_client.get(reverse("admin:accounts_user_add")).content.decode()
    assert 'name="password1"' not in content and 'name="usable_password"' not in content


def test_the_new_user_sets_a_password_with_the_reset_link(root_client, client, make_user):
    from django.test import Client

    root_client.post(reverse("admin:accounts_user_add"), {"email": "new@example.cz"})
    created = User.objects.get(email="new@example.cz")
    root_client.post(
        reverse("admin:accounts_user_changelist"),
        {"action": "send_password_reset_link", "_selected_action": [created.pk]},
    )
    assert len(mail.outbox) == 1
    guest = Client()
    link = extract_link(mail.outbox[0].body)

    form_page = guest.get(link, follow=True)
    confirm = form_page.redirect_chain[-1][0] if form_page.redirect_chain else link
    response = guest.post(
        confirm, {"new_password1": OTHER_PASSWORD, "new_password2": OTHER_PASSWORD}
    )

    assert response.status_code == 302
    created.refresh_from_db()
    assert created.check_password(OTHER_PASSWORD)


def test_a_non_superuser_cannot_add_users(non_superuser_client):
    assert non_superuser_client.get(reverse("admin:accounts_user_add")).status_code == 403
    assert (
        non_superuser_client.post(
            reverse("admin:accounts_user_add"), {"email": "x@example.cz"}
        ).status_code
        == 403
    )
    assert not User.objects.filter(email="x@example.cz").exists()


# --- The reset-link action ---------------------------------------------------------------------


def send_link(client, *users) -> object:
    return client.post(
        reverse("admin:accounts_user_changelist"),
        {"action": "send_password_reset_link", "_selected_action": [u.pk for u in users]},
        follow=True,
    )


def test_the_action_sends_the_normal_reset_e_mail(non_superuser_client, victim):
    response = send_link(non_superuser_client, victim)

    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == [victim.email] and message.subject == "[BARF Nutri] Obnova hesla"
    assert re.search(r"/ucet/heslo/obnova/[^/]+/[^/]+/", message.body)
    assert "Odkaz na obnovu hesla byl odeslán: 1." in response.content.decode()
    assert LogEntry.objects.filter(
        object_id=str(victim.pk), change_message__contains="Odeslán"
    ).exists()
    assert AdminAccessLog.objects.filter(
        action=AdminAccessAction.CHANGE, object_pk=str(victim.pk), model="user"
    ).exists()


def test_the_action_is_throttled_like_the_public_form(non_superuser_client, victim):
    send_link(non_superuser_client, victim)
    response = send_link(non_superuser_client, victim)

    assert len(mail.outbox) == 1  # the second one within two minutes is not sent
    content = response.content.decode()
    assert "Odkaz na obnovu hesla byl odeslán: 0." in content and "Neodesláno: 1" in content


def test_the_public_reset_form_shares_the_throttle(non_superuser_client, victim, client):
    from django.test import Client

    Client().post(reverse("accounts:password_reset"), {"email": victim.email})
    assert len(mail.outbox) == 1

    send_link(non_superuser_client, victim)

    assert len(mail.outbox) == 1


def test_nothing_is_sent_to_an_inactive_account(non_superuser_client, make_user):
    inactive = make_user("gone@example.cz", is_active=False)

    response = send_link(non_superuser_client, inactive)

    assert mail.outbox == [] and "Neodesláno: 1" in response.content.decode()


def test_the_action_cannot_reach_staff_for_a_non_superuser(
    non_superuser_client, colleague, superuser
):
    send_link(non_superuser_client, colleague, superuser)

    assert mail.outbox == []


def test_a_superuser_may_send_the_link_to_staff(root_client, colleague):
    send_link(root_client, colleague)

    assert [m.to for m in mail.outbox] == [[colleague.email]]


def test_the_reset_link_works_once_and_sets_the_password(non_superuser_client, victim):
    from django.test import Client

    send_link(non_superuser_client, victim)
    guest = Client()
    response = guest.get(extract_link(mail.outbox[0].body), follow=True)
    confirm = response.redirect_chain[-1][0]

    done = guest.post(confirm, {"new_password1": OTHER_PASSWORD, "new_password2": OTHER_PASSWORD})

    assert done.status_code == 302
    victim.refresh_from_db()
    assert victim.check_password(OTHER_PASSWORD) and not victim.check_password(PASSWORD)


def test_the_list_does_not_query_per_user(root_client, make_user):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    url = reverse("admin:accounts_user_changelist")
    for n in range(3):
        make_user(f"first{n}@example.cz", roles=(Role.OWNER, Role.VET))
    with CaptureQueriesContext(connection) as few:
        root_client.get(url)
    for n in range(12):
        make_user(f"second{n}@example.cz", roles=(Role.OWNER, Role.VET))
    with CaptureQueriesContext(connection) as many:
        response = root_client.get(url)

    assert len(many) == len(few)
    assert response.content.decode().count("Majitel zvířat, Veterinární lékař") == 15
