"""The administration of vet verification requests (docs/14 §14.11): the list, the three actions
with their confirmation page, every role against every action, the notes, the four-eyes rule,
the guard against deciding twice, one transaction, the e-mails and the access log."""

import re

import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Group, Permission
from django.core import mail
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts import vet_verification
from accounts.models import User, VetVerificationRequest
from accounts.roles import Role
from accounts.services import claim_email_slot
from accounts.vet_verification import VetVerificationError
from backoffice.models import AdminAccessAction as Action
from backoffice.models import AdminAccessLog
from tests.backend.helpers import log_in_verified

pytestmark = pytest.mark.django_db

SUPPORT = Role.SUPPORT_ADMIN.value
ROLES = ["anonymous", "owner", "vet", SUPPORT, "data_curator", "nutrition_reviewer", "superuser"]
STAFF_ROLES = {SUPPORT, "data_curator", "nutrition_reviewer", "superuser"}
DECIDING_ROLES = {SUPPORT, "superuser"}
ACTIONS = ["approve_requests", "reject_requests", "revoke_vet_role"]
METHOD = "Ověřeno v telefonu a podle listin."
REASON = "Nedoložen údaj o pracovišti."
NOTES = {"verification_method_note": METHOD, "decision_note": REASON}


def list_url() -> str:
    return reverse("admin:accounts_vetverificationrequest_changelist")


def post_action(client, action, items, **extra):
    data = {"action": action, "_selected_action": [item.pk for item in items], **extra}
    return client.post(list_url(), data)


def confirm(client, action, items, **notes):
    return post_action(client, action, items, post="yes", **notes)


def fresh(item) -> VetVerificationRequest:
    return VetVerificationRequest.objects.get(pk=item.pk)


def is_vet(user) -> bool:
    return User.objects.get(pk=user.pk).groups.filter(name=Role.VET).exists()


@pytest.fixture
def make_request(make_user):
    def factory(email="zadatel@example.cz", status="PENDING", **fields) -> VetVerificationRequest:
        user = User.objects.filter(email=email).first() or make_user(email)
        fields.setdefault("workplace", "Klinika Praha")
        item = VetVerificationRequest.objects.create(user=user, **fields)
        if status != "PENDING":
            item.status = status
            item.decided_at = timezone.now()
            item.decision_note = "Dříve zamítnuto."
            item.verification_method_note = "Dříve ověřeno."
            item.save()
        return item

    return factory


@pytest.fixture
def pending(make_request):
    return make_request()


@pytest.fixture
def support(make_user) -> User:
    return make_user("podpora@example.cz", roles=(Role.SUPPORT_ADMIN,))


@pytest.fixture
def support_client(client, support):
    log_in_verified(client, support)
    AdminAccessLog.objects.all().delete()  # (the sign-in itself is logged: start clean)
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


# --- Every role against every action --------------------------------------------------------------


def expected_status(role: str) -> int:
    """302 to sign in for visitors without staff access, 403 for staff without the permission."""
    if role in DECIDING_ROLES:
        return 200
    return 403 if role in STAFF_ROLES else 302


@pytest.mark.parametrize("role", ROLES)
def test_the_list_is_for_support_and_superusers_only(client_for, pending, role):
    response = client_for(role).get(list_url())

    assert response.status_code == expected_status(role)
    assert ("zadatel@example.cz" in response.content.decode()) == (role in DECIDING_ROLES)


@pytest.mark.parametrize("action", ACTIONS)
@pytest.mark.parametrize("role", ROLES)
def test_each_role_against_each_action_first_step(client_for, make_request, role, action):
    """The first POST of the action: the confirmation page for the roles that decide, and for
    nobody else any change."""
    status = "APPROVED" if action == "revoke_vet_role" else "PENDING"
    item = make_request(status=status)
    before = (fresh(item).status, is_vet(item.user))

    response = post_action(client_for(role), action, [item])

    assert response.status_code == expected_status(role)
    assert (fresh(item).status, is_vet(item.user)) == before
    if role in DECIDING_ROLES:
        assert "Poznámky níže se uloží" in response.content.decode()


@pytest.mark.parametrize(
    ("action", "status", "after_status", "vet_after"),
    [
        ("approve_requests", "PENDING", "APPROVED", True),
        ("reject_requests", "PENDING", "REJECTED", False),
        ("revoke_vet_role", "APPROVED", "REVOKED", False),
    ],
)
@pytest.mark.parametrize("role", ROLES)
def test_each_role_against_each_action_confirmed(
    client_for, make_request, role, action, status, after_status, vet_after
):
    item = make_request(status=status)
    if status == "APPROVED":
        item.user.groups.add(Group.objects.get(name=Role.VET))

    response = confirm(client_for(role), action, [item], **NOTES)

    assert response.status_code == (302 if role in DECIDING_ROLES else expected_status(role))
    if role in DECIDING_ROLES:
        assert fresh(item).status == after_status
        assert is_vet(item.user) is vet_after
    else:
        assert fresh(item).status == status
        assert is_vet(item.user) is (status == "APPROVED")


def test_a_staff_member_who_may_only_view_cannot_decide(client, make_user, pending):
    """The action needs the decide permission, not merely the right to see the list."""
    viewer = make_user("revizor@example.cz", roles=(Role.DATA_CURATOR,))
    viewer.user_permissions.add(Permission.objects.get(codename="view_vetverificationrequest"))
    log_in_verified(client, viewer)

    page = client.get(list_url())
    response = confirm(client, "approve_requests", [pending], **NOTES)

    assert page.status_code == 200
    for action in ACTIONS:
        assert f'value="{action}"' not in page.content.decode()
    assert response.status_code == 200  # only the list again: the action does not exist for them
    assert "Poznámky níže se uloží" not in response.content.decode()
    assert fresh(pending).status == "PENDING" and not is_vet(pending.user)


def test_the_decide_permission_alone_does_not_show_the_list(client, make_user, pending):
    decider = make_user("rozhodce@example.cz", roles=(Role.DATA_CURATOR,))
    decider.user_permissions.add(Permission.objects.get(codename="decide_vetverificationrequest"))
    log_in_verified(client, decider)

    assert client.get(list_url()).status_code == 403
    assert confirm(client, "approve_requests", [pending], **NOTES).status_code == 403
    assert fresh(pending).status == "PENDING"


def test_nobody_adds_or_changes_a_request_by_hand(client_for, pending):
    for role in DECIDING_ROLES:
        client = client_for(role)
        assert client.get(reverse("admin:accounts_vetverificationrequest_add")).status_code == 403
        change = reverse("admin:accounts_vetverificationrequest_change", args=[pending.pk])
        assert client.get(change).status_code == 200  # read-only
        assert client.post(change, {"status": "APPROVED"}).status_code == 403
    assert fresh(pending).status == "PENDING"


def test_the_detail_page_is_read_only_and_shows_both_notes(root_client, make_request):
    item = make_request(status="APPROVED")
    url = reverse("admin:accounts_vetverificationrequest_change", args=[item.pk])

    content = root_client.get(url).content.decode()

    assert "Dříve ověřeno." in content and "Dříve zamítnuto." in content
    for name in ("status", "decision_note", "verification_method_note", "workplace"):
        assert f'name="{name}"' not in content, name


def test_only_a_superuser_deletes_a_request(client_for, pending):
    assert (
        client_for(SUPPORT)
        .get(reverse("admin:accounts_vetverificationrequest_delete", args=[pending.pk]))
        .status_code
        == 403
    )
    assert (
        client_for("superuser")
        .get(reverse("admin:accounts_vetverificationrequest_delete", args=[pending.pk]))
        .status_code
        == 200
    )


# --- The list -------------------------------------------------------------------------------------


def test_the_list_shows_the_state_as_icon_text_and_colour(support_client, make_request):
    for status, _text, css in (
        ("PENDING", "čeká na posouzení", "info"),
        ("APPROVED", "schváleno", "success"),
        ("REJECTED", "zamítnuto", "danger"),
        ("REVOKED", "role odebrána", "warning"),
    ):
        make_request(f"{css}@example.cz", status=status)

    content = support_client.get(list_url()).content.decode()

    for icon, text, css in (
        ("ⓘ", "čeká na posouzení", "info"),
        ("✓", "schváleno", "success"),
        ("⛔", "zamítnuto", "danger"),
        ("⚠", "role odebrána", "warning"),
    ):
        assert (
            f'<span class="barf-status barf-status--{css}"><span aria-hidden="true">{icon}</span>'
            f" {text}</span>"
        ) in content


def test_the_list_filters_by_state_and_searches(support_client, make_request):
    make_request("ceka@example.cz", workplace="Klinika Brno", professional_id="777")
    make_request("hotovo@example.cz", status="REJECTED", workplace="Ordinace Plzeň")

    waiting = support_client.get(list_url(), {"status__exact": "PENDING"}).content.decode()
    assert "ceka@example.cz" in waiting and "hotovo@example.cz" not in waiting

    by_workplace = support_client.get(list_url(), {"q": "Plzeň"}).content.decode()
    assert "hotovo@example.cz" in by_workplace and "ceka@example.cz" not in by_workplace
    by_email = support_client.get(list_url(), {"q": "ceka@"}).content.decode()
    assert "ceka@example.cz" in by_email and "hotovo@example.cz" not in by_email
    by_number = support_client.get(list_url(), {"q": "777"}).content.decode()
    assert "ceka@example.cz" in by_number


def test_a_non_superuser_does_not_see_requests_of_staff_except_their_own(
    support_client, support, make_request, make_user
):
    staff = make_user("kolega@example.cz", roles=(Role.DATA_CURATOR,))
    VetVerificationRequest.objects.create(user=staff, workplace="Pracoviště kolegy")
    VetVerificationRequest.objects.create(user=support, workplace="Moje pracoviště")
    make_request("obycejny@example.cz")

    content = support_client.get(list_url()).content.decode()

    assert "obycejny@example.cz" in content
    assert "podpora@example.cz" in content
    assert "kolega@example.cz" not in content
    listed = [int(pk) for pk in re.findall(r'name="_selected_action" value="(\d+)"', content)]
    assert len(listed) == 2
    assert staff.vet_verification_requests.get().pk not in listed


def test_a_superuser_sees_the_requests_of_staff(root_client, make_user):
    staff = make_user("kolega@example.cz", roles=(Role.DATA_CURATOR,))
    VetVerificationRequest.objects.create(user=staff, workplace="X")

    assert "kolega@example.cz" in root_client.get(list_url()).content.decode()


def test_a_request_of_staff_is_not_reachable_for_support_by_address_or_action(
    support_client, make_user
):
    staff = make_user("kolega@example.cz", roles=(Role.DATA_CURATOR,))
    item = VetVerificationRequest.objects.create(user=staff, workplace="X")

    detail = support_client.get(
        reverse("admin:accounts_vetverificationrequest_change", args=[item.pk])
    )
    response = confirm(support_client, "approve_requests", [item], **NOTES)

    assert detail.status_code == 302  # as for a record that does not exist
    assert response.status_code == 302
    assert fresh(item).status == "PENDING" and not is_vet(staff)


def test_the_list_costs_the_same_queries_for_one_request_and_for_many(support_client, make_request):
    make_request("a0@example.cz")
    with CaptureQueriesContext(connection) as one:
        support_client.get(list_url())
    for number in range(1, 8):
        make_request(f"a{number}@example.cz", status="APPROVED" if number % 2 else "PENDING")
    with CaptureQueriesContext(connection) as many:
        support_client.get(list_url())

    assert len(many) == len(one)


# --- The confirmation page -----------------------------------------------------------------------


def test_the_page_of_an_approval_asks_for_how_the_person_was_verified(support_client, pending):
    response = post_action(support_client, "approve_requests", [pending])
    content = response.content.decode()

    assert response.status_code == 200
    assert "Schválit žádost o ověření veterináře" in content
    assert "zadatel@example.cz" in content and "Klinika Praha" in content
    assert 'name="verification_method_note"' in content
    assert "Jak byla totožnost a oprávnění ověřena" in content
    assert 'name="decision_note"' in content
    assert 'name="post" value="yes"' in content
    assert 'name="action" value="approve_requests"' in content
    assert f'name="_selected_action" value="{pending.pk}"' in content
    assert "Schválit a přidělit roli" in content
    assert 'class="barf-danger"' not in content  # an approval is not destructive
    assert fresh(pending).status == "PENDING"  # showing the page changes nothing


def test_the_pages_of_a_rejection_and_a_revocation_ask_for_the_reason_only(
    support_client, make_request
):
    approved = make_request("schvaleny@example.cz", status="APPROVED")
    reject = post_action(support_client, "reject_requests", [make_request("ceka@example.cz")])
    revoke = post_action(support_client, "revoke_vet_role", [approved])

    for response, button in ((reject, "Zamítnout žádost"), (revoke, "Odebrat roli")):
        content = response.content.decode()
        assert 'class="barf-danger"' in content
        assert 'name="decision_note"' in content
        assert 'name="verification_method_note"' not in content
        assert button in content
        assert "Žadatel ho uvidí" in content
    assert "okamžitě ztratí přístup" in revoke.content.decode()


def test_the_page_escapes_what_the_applicant_wrote(support_client, make_request):
    hostile = "<script>alert(1)</script>"
    item = make_request(workplace=hostile, professional_id=hostile, message=hostile)

    content = post_action(support_client, "approve_requests", [item]).content.decode()

    assert "<script>alert(1)" not in content
    assert content.count("&lt;script&gt;alert(1)&lt;/script&gt;") >= 3


def test_the_page_has_no_inline_script_or_style(support_client, pending):
    content = post_action(support_client, "approve_requests", [pending]).content.decode()

    assert "style=" not in content
    assert 'href="/static/css/admin.css"' in content
    assert "<script>" not in content


# --- Notes are required ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("action", "field", "status"),
    [
        ("approve_requests", "verification_method_note", "PENDING"),
        ("reject_requests", "decision_note", "PENDING"),
        ("revoke_vet_role", "decision_note", "APPROVED"),
    ],
)
@pytest.mark.parametrize("value", ["", "   ", "\n"])
def test_the_required_note_blocks_the_decision(
    support_client, make_request, action, field, status, value
):
    item = make_request(status=status)
    if status == "APPROVED":
        item.user.groups.add(Group.objects.get(name=Role.VET))
    notes = {"verification_method_note": METHOD, "decision_note": REASON, field: value}

    response = confirm(support_client, action, [item], **notes)

    assert response.status_code == 200  # the page again, with the error
    assert "Toto pole je třeba vyplnit." in response.content.decode()
    assert fresh(item).status == status
    assert is_vet(item.user) is (status == "APPROVED")
    assert mail.outbox == []


def test_the_note_that_is_not_needed_may_stay_empty(support_client, pending):
    response = confirm(
        support_client, "approve_requests", [pending], verification_method_note=METHOD
    )

    assert response.status_code == 302 and fresh(pending).status == "APPROVED"


def test_a_note_longer_than_the_limit_is_refused(support_client, pending):
    response = confirm(support_client, "reject_requests", [pending], decision_note="x" * 2001)

    assert response.status_code == 200 and fresh(pending).status == "PENDING"


# --- The decisions --------------------------------------------------------------------------------


def test_approving_through_the_admin(support_client, support, pending, settings):
    response = confirm(support_client, "approve_requests", [pending], **NOTES)

    assert response.status_code == 302 and response["Location"] == list_url()
    item = fresh(pending)
    assert item.status == "APPROVED" and is_vet(pending.user)
    assert item.decided_by == support and item.decided_at is not None
    assert item.verification_method_note == METHOD and item.decision_note == REASON


def test_rejecting_through_the_admin(support_client, support, pending):
    confirm(support_client, "reject_requests", [pending], decision_note=REASON)

    item = fresh(pending)
    assert item.status == "REJECTED" and not is_vet(pending.user)
    assert item.decided_by == support and item.decision_note == REASON
    assert item.verification_method_note == ""


def test_revoking_through_the_admin(support_client, make_request):
    item = make_request(status="APPROVED")
    item.user.groups.add(Group.objects.get(name=Role.VET))

    confirm(support_client, "revoke_vet_role", [item], decision_note=REASON)

    assert fresh(item).status == "REVOKED" and not is_vet(item.user)


def test_the_messages_say_what_happened(support_client, make_request):
    first, second = make_request("a@example.cz"), make_request("b@example.cz")

    response = confirm(support_client, "approve_requests", [first, second], **NOTES)
    messages = [str(m) for m in response.wsgi_request._messages]

    assert "Schváleno žádostí: 2. Uživatelé mají roli veterináře." in messages
    assert "E-mail žadateli odeslán: 2." in messages


def test_several_requests_are_decided_together_with_the_same_notes(support_client, make_request):
    items = [make_request(f"u{number}@example.cz") for number in range(3)]

    confirm(support_client, "reject_requests", items, decision_note=REASON)

    assert {fresh(item).status for item in items} == {"REJECTED"}
    assert {fresh(item).decision_note for item in items} == {REASON}


def test_the_decision_is_written_to_the_history_of_the_request_and_the_admin_log(
    support_client, support, pending
):
    confirm(support_client, "approve_requests", [pending], **NOTES)

    assert [h.status for h in pending.history.order_by("history_date")] == ["PENDING", "APPROVED"]
    assert pending.history.latest("history_date").history_user == support
    entry = LogEntry.objects.get(action_flag=CHANGE, object_id=str(pending.pk))
    assert entry.change_message == "Žádost schválena, přidělena role veterináře."
    assert entry.object_repr == f"žádost o ověření veterináře č. {pending.pk}"
    assert "zadatel@example.cz" not in entry.object_repr + entry.change_message


# --- Already decided, and the own request ---------------------------------------------------------


@pytest.mark.parametrize("action", ["approve_requests", "reject_requests"])
@pytest.mark.parametrize("status", ["APPROVED", "REJECTED", "REVOKED"])
def test_a_decided_request_is_refused_by_approve_and_reject(
    support_client, make_request, action, status
):
    item = make_request(status=status)
    before = fresh(item)

    response = confirm(support_client, action, [item], **NOTES)
    messages = [str(m) for m in response.wsgi_request._messages]

    assert response.status_code == 302
    assert "Žádnou z vybraných žádostí nelze vyřídit." in messages
    assert any("už byla vyřízena" in m for m in messages)
    after = fresh(item)
    assert (after.status, after.decided_at, after.decided_by) == (
        before.status,
        before.decided_at,
        before.decided_by,
    )
    assert mail.outbox == []


@pytest.mark.parametrize("status", ["PENDING", "REJECTED", "REVOKED"])
def test_only_an_approved_request_can_be_revoked_in_the_admin(support_client, make_request, status):
    item = make_request(status=status)

    response = confirm(support_client, "revoke_vet_role", [item], **NOTES)

    assert any("jen u schválené" in str(m) for m in response.wsgi_request._messages)
    assert fresh(item).status == status


@pytest.mark.parametrize("client_name", ["support_client", "root_client"])
@pytest.mark.parametrize("action", ACTIONS)
def test_the_own_request_cannot_be_decided(request, client_name, action):
    """The four-eyes rule holds for support and for superusers alike, on every action."""
    client = request.getfixturevalue(client_name)
    me = User.objects.get(
        email="podpora@example.cz" if client_name == "support_client" else "root@example.cz"
    )
    own = VetVerificationRequest.objects.create(user=me, workplace="Moje klinika")
    if action == "revoke_vet_role":
        VetVerificationRequest.objects.filter(pk=own.pk).update(
            status="APPROVED", decided_at=timezone.now(), verification_method_note="x"
        )

    first = post_action(client, action, [own])
    response = confirm(client, action, [own], **NOTES)

    messages = [str(m) for m in response.wsgi_request._messages]
    assert first.status_code == 302 and response.status_code == 302
    assert any("Vlastní žádost nesmíte vyřídit" in m for m in messages)
    assert fresh(own).status == ("APPROVED" if action == "revoke_vet_role" else "PENDING")
    assert not is_vet(me) and mail.outbox == []


def test_a_mixed_selection_decides_the_eligible_ones_and_reports_the_rest(
    support_client, support, make_request
):
    fine = make_request("dobra@example.cz")
    done = make_request("hotova@example.cz", status="REJECTED")
    own = VetVerificationRequest.objects.create(user=support, workplace="Moje")

    page = post_action(support_client, "approve_requests", [fine, done, own])
    response = confirm(support_client, "approve_requests", [fine, done, own], **NOTES)

    assert "Tyto vybrané žádosti se přeskočí" in page.content.decode()
    messages = [str(m) for m in response.wsgi_request._messages]
    assert "Schváleno žádostí: 1. Uživatelé mají roli veterináře." in messages
    skipped = next(m for m in messages if m.startswith("Přeskočeno žádostí: 2."))
    assert "hotova@example.cz" in skipped and "podpora@example.cz" in skipped
    assert fresh(fine).status == "APPROVED"
    assert fresh(done).status == "REJECTED" and fresh(own).status == "PENDING"


def test_nothing_changes_when_one_is_decided_by_somebody_else_meanwhile(
    support_client, make_request, monkeypatch
):
    """One transaction: the second decision fails, the first is taken back."""
    first, second = make_request("a@example.cz"), make_request("b@example.cz")
    real = vet_verification.decide
    calls = []

    def flaky(vet_request, decision, **kwargs):
        calls.append(vet_request.pk)
        if len(calls) == 2:
            raise VetVerificationError("Žádost už byla vyřízena (stav: zamítnuto).")
        return real(vet_request, decision, **kwargs)

    monkeypatch.setattr(vet_verification, "decide", flaky)

    response = confirm(support_client, "approve_requests", [first, second], **NOTES)

    messages = [str(m) for m in response.wsgi_request._messages]
    assert any(m.startswith("Nic se nezměnilo:") for m in messages)
    assert len(calls) == 2
    assert fresh(first).status == "PENDING" and fresh(second).status == "PENDING"
    assert not is_vet(first.user) and mail.outbox == []
    assert not LogEntry.objects.filter(action_flag=CHANGE).exists()


def test_the_decision_needs_the_csrf_token(make_user, pending):
    client = Client(enforce_csrf_checks=True)
    log_in_verified(client, make_user("podpora@example.cz", roles=(Role.SUPPORT_ADMIN,)))
    data = {
        "action": "approve_requests",
        "_selected_action": [pending.pk],
        "post": "yes",
        **NOTES,
    }

    response = client.post(list_url(), data)

    assert response.status_code == 403
    assert fresh(pending).status == "PENDING" and not is_vet(pending.user)


def test_no_selection_does_nothing(support_client, pending):
    response = support_client.post(list_url(), {"action": "approve_requests", "index": "0"})

    assert response.status_code == 302 and fresh(pending).status == "PENDING"


# --- The e-mails ----------------------------------------------------------------------------------


def test_the_applicant_gets_the_decision_e_mail(support_client, pending):
    response = confirm(support_client, "reject_requests", [pending], decision_note=REASON)

    (message,) = mail.outbox
    assert message.to == ["zadatel@example.cz"]
    assert message.subject == "[BARF Nutri] Žádost o roli veterinárního lékaře byla zamítnuta"
    assert REASON in message.body
    assert "E-mail žadateli odeslán: 1." in [str(m) for m in response.wsgi_request._messages]


def test_the_approval_e_mail_does_not_contain_the_internal_note(support_client, pending):
    confirm(support_client, "approve_requests", [pending], **NOTES)

    (message,) = mail.outbox
    assert "schválil vaši žádost" in message.body and REASON in message.body
    assert METHOD not in message.body


def test_the_e_mail_is_throttled_and_the_admin_says_so(support_client, make_request):
    item = make_request()
    assert claim_email_slot("vet-REJECTED", item.user)  # an e-mail of this kind just went out

    response = confirm(support_client, "reject_requests", [item], decision_note=REASON)

    messages = [str(m) for m in response.wsgi_request._messages]
    assert mail.outbox == []
    assert any(m.startswith("E-mail neodeslán: 1") for m in messages)
    assert fresh(item).status == "REJECTED"  # the decision stands


def test_a_revocation_e_mail_is_sent(support_client, make_request):
    item = make_request(status="APPROVED")
    item.user.groups.add(Group.objects.get(name=Role.VET))

    confirm(support_client, "revoke_vet_role", [item], decision_note=REASON)

    (message,) = mail.outbox
    assert message.subject == "[BARF Nutri] Role veterinárního lékaře byla odebrána"


# --- The access log -------------------------------------------------------------------------------


def test_the_access_log_records_the_list_the_page_and_the_decision(support_client, pending):
    support_client.get(list_url())
    post_action(support_client, "approve_requests", [pending])
    confirm(support_client, "approve_requests", [pending], **NOTES)

    rows = list(AdminAccessLog.objects.order_by("pk"))
    assert [(r.action, r.model, r.object_pk) for r in rows] == [
        (Action.VIEW_LIST, "vetverificationrequest", ""),
        (Action.VIEW_OBJECT, "vetverificationrequest", str(pending.pk)),
        (Action.CHANGE, "vetverificationrequest", str(pending.pk)),
    ]
    assert {r.staff_email for r in rows} == {"podpora@example.cz"}


def test_one_decision_leaves_one_row_per_request(support_client, make_request):
    items = [make_request(f"u{number}@example.cz") for number in range(3)]

    confirm(support_client, "reject_requests", items, decision_note=REASON)

    rows = AdminAccessLog.objects.filter(action=Action.CHANGE)
    assert sorted(r.object_pk for r in rows) == sorted(str(item.pk) for item in items)


def test_a_refused_decision_is_not_logged_as_a_change(support_client, make_request):
    item = make_request(status="REJECTED")

    confirm(support_client, "approve_requests", [item], **NOTES)

    assert not AdminAccessLog.objects.filter(action=Action.CHANGE).exists()
    assert AdminAccessLog.objects.filter(action=Action.VIEW_OBJECT).exists()


def test_a_page_with_an_error_is_logged_as_a_view_not_as_a_change(support_client, pending):
    confirm(support_client, "reject_requests", [pending], decision_note="")

    assert not AdminAccessLog.objects.filter(action=Action.CHANGE).exists()
    assert [r.action for r in AdminAccessLog.objects.all()] == [Action.VIEW_OBJECT]


def test_the_history_of_a_request_is_viewable_and_logged(support_client, pending):
    url = reverse("admin:accounts_vetverificationrequest_history", args=[pending.pk])

    response = support_client.get(url)

    assert response.status_code == 200
    assert AdminAccessLog.objects.get().action == Action.VIEW_OBJECT
