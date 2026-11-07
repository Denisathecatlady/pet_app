"""Verification of veterinarians, the applicant's side and the rules of the decision
(docs/14 §14.11): the model, the services, the page ``/ucet/veterinar/`` and the e-mails.

The administration actions that call these services are tested in
``test_vet_verification_admin.py``."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounts import vet_verification
from accounts.export import build_export
from accounts.models import User, VetVerificationRequest, VetVerificationStatus
from accounts.roles import Role
from accounts.vet_verification import Decision, VetVerificationError
from animals.models import Animal, TargetWeightStatus
from animals.permissions import Action, get_animal_for
from animals.services import confirm_target_weight, share_with_vet
from tests.backend.helpers import extract_link

pytestmark = pytest.mark.django_db

PAGE = "accounts:vet_verification"
METHOD = "Totožnost ověřena podle občanského průkazu a výpisu z evidence."
REASON = "Nepodařilo se dohledat vaše oprávnění."


@pytest.fixture
def applicant(make_user) -> User:
    return make_user("zadatel@example.cz")


@pytest.fixture
def decider(make_user) -> User:
    return make_user("podpora@example.cz", roles=(Role.SUPPORT_ADMIN,))


@pytest.fixture
def pending(applicant) -> VetVerificationRequest:
    return VetVerificationRequest.objects.create(
        user=applicant, workplace="Klinika Praha", professional_id="1234", message="Prosím."
    )


def is_vet(user: User) -> bool:
    return User.objects.get(pk=user.pk).groups.filter(name=Role.VET).exists()


def fresh(item: VetVerificationRequest) -> VetVerificationRequest:
    return VetVerificationRequest.objects.get(pk=item.pk)


# --- The model ----------------------------------------------------------------------------------


def test_the_labels_and_names_of_the_model():
    field = VetVerificationRequest._meta.get_field("professional_id")
    assert field.verbose_name == "Evidenční číslo v profesní evidenci, pokud existuje"
    assert VetVerificationRequest._meta.get_field("verification_method_note").verbose_name == (
        "Jak byla totožnost a oprávnění ověřena"
    )
    assert VetVerificationStatus.values == ["PENDING", "APPROVED", "REJECTED", "REVOKED"]
    assert VetVerificationRequest.contains_personal_data is True


def test_the_label_of_the_registration_number_names_no_real_registry():
    text = (
        VetVerificationRequest._meta.get_field("professional_id").verbose_name
        + VetVerificationRequest._meta.get_field("professional_id").help_text
    ).lower()
    for name in ("komor", "mvdr", "ukzuz", "úkzúz", "vfu", "registr"):
        assert name not in text, name


def test_the_text_of_a_request_holds_no_personal_data(pending):
    """The administration log keeps this text after the account is gone."""
    assert str(pending) == f"žádost o ověření veterináře č. {pending.pk}"
    assert pending.user.email not in str(pending)


def test_the_history_keeps_every_change(pending, decider):
    vet_verification.decide(pending, Decision.APPROVE, staff=decider, verification_method_note="x")

    kinds = list(pending.history.order_by("history_date").values_list("status", flat=True))

    assert kinds == ["PENDING", "APPROVED"]


def test_a_user_has_at_most_one_pending_request(applicant, pending):
    with pytest.raises(IntegrityError), transaction.atomic():
        VetVerificationRequest.objects.create(user=applicant, workplace="Jiná klinika")


def test_decided_requests_do_not_count_as_pending(applicant, pending):
    VetVerificationRequest.objects.filter(pk=pending.pk).update(
        status="REJECTED", decided_at=timezone.now(), decision_note="x"
    )

    second = VetVerificationRequest.objects.create(user=applicant, workplace="Jiná klinika")
    VetVerificationRequest.objects.filter(pk=second.pk).update(
        status="REJECTED", decided_at=timezone.now(), decision_note="x"
    )
    VetVerificationRequest.objects.create(user=applicant, workplace="Třetí klinika")

    assert applicant.vet_verification_requests.count() == 3


def test_two_users_may_both_have_a_pending_request(pending, make_user):
    VetVerificationRequest.objects.create(user=make_user("jiny@example.cz"), workplace="X")


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "APPROVED", "decided_at": timezone.now(), "verification_method_note": " "},
        {"status": "REJECTED", "decided_at": timezone.now(), "decision_note": ""},
        {"status": "REVOKED", "decided_at": timezone.now(), "decision_note": "  "},
        {"status": "APPROVED", "verification_method_note": "x"},  # no time of the decision
        {"status": "PENDING", "decided_at": timezone.now()},
        {"status": "UNKNOWN"},
    ],
)
def test_the_database_refuses_an_inconsistent_state(pending, changes):
    with pytest.raises(IntegrityError), transaction.atomic():
        VetVerificationRequest.objects.filter(pk=pending.pk).update(**changes)


def test_clean_names_the_missing_note(pending):
    pending.status = "APPROVED"
    with pytest.raises(ValidationError) as caught:
        pending.clean()
    assert "verification_method_note" in caught.value.error_dict
    pending.status = "REJECTED"
    with pytest.raises(ValidationError) as caught:
        pending.clean()
    assert "decision_note" in caught.value.error_dict


def test_deleting_the_account_deletes_its_requests_and_their_history(applicant, pending):
    pk = pending.pk
    assert pending.history.exists()

    applicant.delete()

    assert not VetVerificationRequest.objects.filter(pk=pk).exists()
    assert not VetVerificationRequest.history.model.objects.filter(id=pk).exists()


def test_deleting_the_deciding_account_keeps_the_record(applicant, pending, decider):
    vet_verification.decide(pending, Decision.REJECT, staff=decider, decision_note=REASON)

    decider.delete()

    kept = fresh(pending)
    assert kept.decided_by is None and kept.status == "REJECTED"


# --- Filing a request ---------------------------------------------------------------------------


def test_submit_creates_a_pending_request(applicant):
    item = vet_verification.submit_request(
        applicant, professional_id="42", workplace="Klinika", message="Dobrý den"
    )

    assert item.status == "PENDING" and item.user == applicant
    assert (item.professional_id, item.workplace, item.message) == ("42", "Klinika", "Dobrý den")
    assert item.decided_at is None and item.decided_by is None


def test_submit_refuses_a_user_who_is_a_vet(vet_user):
    with pytest.raises(VetVerificationError, match="už máte"):
        vet_verification.submit_request(vet_user, workplace="Klinika")
    assert not VetVerificationRequest.objects.exists()


def test_submit_refuses_a_second_pending_request(applicant, pending):
    with pytest.raises(VetVerificationError, match="nevyřízenou"):
        vet_verification.submit_request(applicant, workplace="Klinika")
    assert applicant.vet_verification_requests.count() == 1


def test_submit_turns_a_concurrent_duplicate_into_the_same_error(applicant, monkeypatch):
    """Two requests filed at the same moment pass the check; the database allows one."""
    VetVerificationRequest.objects.create(user=applicant, workplace="První")
    stale = vet_verification.RequestState(is_vet=False, pending=None, latest=None)
    monkeypatch.setattr(vet_verification, "request_state", lambda user: stale)

    with pytest.raises(VetVerificationError, match="nevyřízenou"):
        vet_verification.submit_request(applicant, workplace="Druhá")

    assert applicant.vet_verification_requests.count() == 1


def test_the_operator_is_told_about_a_new_request(applicant, settings):
    settings.CONTACT_EMAIL = "podpora@barf.example.cz"

    vet_verification.submit_request(applicant, workplace="Klinika Praha", message="Tajné")

    (message,) = mail.outbox
    assert message.to == ["podpora@barf.example.cz"]
    assert message.subject == "[BARF Nutri] Nová žádost o roli veterinárního lékaře"
    assert "zadatel@example.cz" in message.body
    # Nothing more than who and where to decide: no workplace, no message, no link.
    assert "Klinika Praha" not in message.body and "Tajné" not in message.body
    assert "http" not in message.body and "/admin" not in message.body


def test_no_notice_without_a_contact_address(applicant, settings):
    settings.CONTACT_EMAIL = ""

    vet_verification.submit_request(applicant, workplace="Klinika")

    assert mail.outbox == []


def test_the_notice_is_throttled_like_the_other_account_e_mails(applicant, settings):
    settings.CONTACT_EMAIL = "podpora@barf.example.cz"
    first = vet_verification.submit_request(applicant, workplace="A")
    VetVerificationRequest.objects.filter(pk=first.pk).update(
        status="REJECTED", decided_at=timezone.now(), decision_note="x"
    )

    vet_verification.submit_request(applicant, workplace="B")  # at once again

    assert len(mail.outbox) == 1  # the second notice waited for the throttle window


# --- Deciding: the rules ------------------------------------------------------------------------


def test_approving_adds_the_role_and_records_the_decision(pending, decider):
    decided = vet_verification.decide(
        pending, Decision.APPROVE, staff=decider, verification_method_note=f"  {METHOD}  "
    )

    assert is_vet(pending.user)
    assert decided.status == "APPROVED"
    assert decided.decided_by == decider and decided.decided_at is not None
    assert decided.verification_method_note == METHOD  # stripped
    assert fresh(pending).status == "APPROVED"


def test_rejecting_records_the_reason_and_changes_no_role(pending, decider):
    vet_verification.decide(pending, Decision.REJECT, staff=decider, decision_note=REASON)

    assert not is_vet(pending.user)
    assert fresh(pending).status == "REJECTED"
    assert fresh(pending).decision_note == REASON


def test_revoking_removes_the_role(pending, decider):
    vet_verification.decide(pending, Decision.APPROVE, staff=decider, verification_method_note="x")
    assert is_vet(pending.user)

    vet_verification.decide(pending, Decision.REVOKE, staff=decider, decision_note=REASON)

    assert not is_vet(pending.user)
    assert fresh(pending).status == "REVOKED" and fresh(pending).decision_note == REASON


@pytest.mark.parametrize(
    ("decision", "note_field"),
    [
        (Decision.APPROVE, "verification_method_note"),
        (Decision.REJECT, "decision_note"),
        (Decision.REVOKE, "decision_note"),
    ],
)
@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_the_note_of_each_decision_is_required(pending, decider, decision, note_field, blank):
    if decision is Decision.REVOKE:
        vet_verification.decide(
            pending, Decision.APPROVE, staff=decider, verification_method_note="x"
        )
    before = fresh(pending).status

    with pytest.raises(VetVerificationError):
        vet_verification.decide(pending, decision, staff=decider, **{note_field: blank})

    assert fresh(pending).status == before
    assert is_vet(pending.user) == (decision is Decision.REVOKE)


def test_the_note_that_is_not_needed_may_be_empty(pending, decider):
    vet_verification.decide(pending, Decision.APPROVE, staff=decider, verification_method_note="x")

    assert fresh(pending).decision_note == ""


def test_a_decision_cannot_be_applied_to_the_own_request(decider):
    own = VetVerificationRequest.objects.create(user=decider, workplace="Klinika")

    for decision in (Decision.APPROVE, Decision.REJECT):
        with pytest.raises(VetVerificationError, match="Vlastní žádost"):
            vet_verification.decide(
                own, decision, staff=decider, decision_note="x", verification_method_note="x"
            )

    assert fresh(own).status == "PENDING" and not is_vet(decider)


def test_a_superuser_cannot_decide_the_own_request_either(superuser):
    own = VetVerificationRequest.objects.create(user=superuser, workplace="Klinika")

    with pytest.raises(VetVerificationError, match="Vlastní žádost"):
        vet_verification.decide(
            own, Decision.APPROVE, staff=superuser, verification_method_note="x"
        )

    assert fresh(own).status == "PENDING"


def test_nobody_revokes_the_own_role_through_a_request(decider):
    own = VetVerificationRequest.objects.create(user=decider, workplace="X")
    VetVerificationRequest.objects.filter(pk=own.pk).update(
        status="APPROVED", decided_at=timezone.now(), verification_method_note="x"
    )

    with pytest.raises(VetVerificationError, match="Vlastní žádost"):
        vet_verification.decide(own, Decision.REVOKE, staff=decider, decision_note="x")


@pytest.mark.parametrize("first", [Decision.APPROVE, Decision.REJECT])
@pytest.mark.parametrize("second", [Decision.APPROVE, Decision.REJECT])
def test_a_decided_request_is_final(pending, decider, first, second):
    notes = {"decision_note": "důvod", "verification_method_note": "způsob"}
    vet_verification.decide(pending, first, staff=decider, **notes)
    state = fresh(pending)

    with pytest.raises(VetVerificationError, match="už byla vyřízena"):
        vet_verification.decide(pending, second, staff=decider, **notes)

    assert fresh(pending).status == state.status
    assert fresh(pending).decided_at == state.decided_at


def test_only_an_approved_request_can_be_revoked(pending, decider):
    with pytest.raises(VetVerificationError, match="jen u schválené"):
        vet_verification.decide(pending, Decision.REVOKE, staff=decider, decision_note="x")

    vet_verification.decide(pending, Decision.REJECT, staff=decider, decision_note="x")
    with pytest.raises(VetVerificationError, match="jen u schválené"):
        vet_verification.decide(pending, Decision.REVOKE, staff=decider, decision_note="x")


def test_a_revoked_request_is_closed(pending, decider):
    vet_verification.decide(pending, Decision.APPROVE, staff=decider, verification_method_note="x")
    vet_verification.decide(pending, Decision.REVOKE, staff=decider, decision_note="x")

    for decision in Decision:
        with pytest.raises(VetVerificationError):
            vet_verification.decide(
                pending, decision, staff=decider, decision_note="x", verification_method_note="x"
            )
    assert not is_vet(pending.user)


def test_a_deactivated_account_is_not_approved(pending, decider):
    User.objects.filter(pk=pending.user_id).update(is_active=False)
    pending.refresh_from_db()

    with pytest.raises(VetVerificationError, match="není aktivní"):
        vet_verification.decide(
            pending, Decision.APPROVE, staff=decider, verification_method_note="x"
        )

    assert fresh(pending).status == "PENDING"


def test_the_decision_sees_a_request_decided_meanwhile(pending, decider, make_user):
    """The caller holds a stale object; the state is re-read under a lock."""
    stale = fresh(pending)
    colleague = make_user("kolega@example.cz", roles=(Role.SUPPORT_ADMIN,))
    vet_verification.decide(pending, Decision.REJECT, staff=colleague, decision_note="x")

    with pytest.raises(VetVerificationError, match="už byla vyřízena"):
        vet_verification.decide(
            stale, Decision.APPROVE, staff=decider, verification_method_note="x"
        )

    assert not is_vet(pending.user)


@pytest.mark.parametrize("role", [Role.OWNER, Role.VET, Role.DATA_CURATOR, Role.NUTRITION_REVIEWER])
def test_only_support_and_superusers_may_decide(pending, make_user, role):
    other = make_user("jiny@example.cz", roles=(role,))

    with pytest.raises(PermissionDenied):
        vet_verification.decide(
            pending, Decision.APPROVE, staff=other, verification_method_note="x"
        )

    assert fresh(pending).status == "PENDING" and not is_vet(pending.user)


def test_a_superuser_and_support_may_decide(pending, superuser, decider, make_user):
    second = VetVerificationRequest.objects.create(
        user=make_user("druhy@example.cz"), workplace="Klinika"
    )

    vet_verification.decide(
        pending, Decision.APPROVE, staff=superuser, verification_method_note="x"
    )
    vet_verification.decide(second, Decision.APPROVE, staff=decider, verification_method_note="x")

    assert is_vet(pending.user) and is_vet(second.user)


def test_an_inactive_administrator_may_not_decide(pending, decider):
    User.objects.filter(pk=decider.pk).update(is_active=False)
    decider.refresh_from_db()

    with pytest.raises(PermissionDenied):
        vet_verification.decide(pending, Decision.REJECT, staff=decider, decision_note="x")


def test_the_permission_can_be_given_to_another_account_by_hand_only(pending, make_user):
    """The permission is the switch: whoever has it may decide, nobody gets it from a role."""
    from django.contrib.auth.models import Permission

    curator = make_user("sberatel@example.cz", roles=(Role.DATA_CURATOR,))
    curator.user_permissions.add(Permission.objects.get(codename="decide_vetverificationrequest"))
    curator = User.objects.get(pk=curator.pk)

    vet_verification.decide(pending, Decision.REJECT, staff=curator, decision_note="x")

    assert fresh(pending).status == "REJECTED"


def test_the_decision_and_the_role_are_one_transaction(pending, decider, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("the group cannot be added")

    monkeypatch.setattr(vet_verification.Group.objects, "get_or_create", broken)

    with pytest.raises(RuntimeError):
        vet_verification.decide(
            pending, Decision.APPROVE, staff=decider, verification_method_note="x"
        )

    assert fresh(pending).status == "PENDING" and fresh(pending).decided_at is None
    assert not is_vet(pending.user)


def test_approving_creates_the_group_when_it_is_missing(pending, decider):
    Group.objects.filter(name=Role.VET).delete()

    vet_verification.decide(pending, Decision.APPROVE, staff=decider, verification_method_note="x")

    assert is_vet(pending.user)


def test_refusal_reason_is_none_for_a_decidable_request(pending, decider):
    for decision in (Decision.APPROVE, Decision.REJECT):
        assert vet_verification.refusal_reason(pending, decision, decider) is None
    assert "jen u schválené" in vet_verification.refusal_reason(pending, Decision.REVOKE, decider)


# --- What approval and revocation do to shares and confirmed target weights --------------------


@pytest.fixture
def shared_animal(make_user, make_animal, pending, decider):
    """An animal whose owner shared it with the applicant after the approval, with a confirmed
    target weight."""
    owner = make_user("majitel@example.cz")
    animal = make_animal(owner, target_weight_kg=Decimal("20"))
    vet_verification.decide(pending, Decision.APPROVE, staff=decider, verification_method_note="x")
    share_with_vet(animal, pending.user.email, owner)
    confirm_target_weight(animal, pending.user, Decimal("20"))
    return animal


def test_before_the_approval_the_applicant_cannot_be_given_a_share(make_user, make_animal, pending):
    owner = make_user("majitel@example.cz")
    animal = make_animal(owner)

    with pytest.raises(ValidationError):
        share_with_vet(animal, pending.user.email, owner)


def test_after_the_approval_the_owner_can_share_and_the_vet_sees_the_animal(shared_animal, pending):
    access = get_animal_for(pending.user, shared_animal.uuid, Action.VIEW)

    assert access.animal == shared_animal
    assert Animal.objects.get(pk=shared_animal.pk).target_weight_status == "VET_CONFIRMED"


def test_revoking_ends_the_access_and_cancels_the_confirmation_but_keeps_the_share(
    shared_animal, pending, decider
):
    from django.http import Http404

    vet_verification.decide(pending, Decision.REVOKE, staff=decider, decision_note=REASON)

    with pytest.raises(Http404):
        get_animal_for(pending.user, shared_animal.uuid, Action.VIEW)
    animal = Animal.objects.get(pk=shared_animal.pk)
    assert animal.target_weight_status == TargetWeightStatus.UNVERIFIED
    assert animal.target_weight_confirmed_by is None and animal.target_weight_confirmed_at is None
    share = shared_animal.shares.get()
    assert share.revoked_at is None  # the owner's consent record stays; it grants nothing now


def test_revoking_does_not_touch_confirmations_of_other_vets(
    shared_animal, pending, decider, make_user, make_animal, vet_user
):
    owner = shared_animal.owner
    other = make_animal(owner, name="Mourek", target_weight_kg=Decimal("5"))
    share_with_vet(other, vet_user.email, owner)
    confirm_target_weight(other, vet_user, Decimal("5"))

    vet_verification.decide(pending, Decision.REVOKE, staff=decider, decision_note=REASON)

    assert Animal.objects.get(pk=other.pk).target_weight_status == "VET_CONFIRMED"


def test_a_new_approval_restores_access_without_restoring_the_confirmation(
    shared_animal, pending, decider
):
    vet_verification.decide(pending, Decision.REVOKE, staff=decider, decision_note=REASON)
    again = vet_verification.submit_request(pending.user, workplace="Nová klinika")

    vet_verification.decide(again, Decision.APPROVE, staff=decider, verification_method_note="y")

    assert get_animal_for(pending.user, shared_animal.uuid, Action.VIEW).animal == shared_animal
    assert Animal.objects.get(pk=shared_animal.pk).target_weight_status == "UNVERIFIED"


# --- The e-mails to the applicant ---------------------------------------------------------------


def test_the_approval_e_mail(pending, decider, rf, settings):
    decided = vet_verification.decide(
        pending,
        Decision.APPROVE,
        staff=decider,
        verification_method_note=METHOD,
        decision_note="Vítejte.",
    )

    assert vet_verification.send_decision_email(decided, rf.get("/"))

    (message,) = mail.outbox
    assert message.to == ["zadatel@example.cz"]
    assert message.subject == "[BARF Nutri] Role veterinárního lékaře byla přidělena"
    assert "schválil vaši žádost" in message.body and "Vítejte." in message.body
    assert METHOD not in message.body  # the internal note never leaves the administration
    assert "příloha" not in message.body.lower()


def test_the_rejection_e_mail_gives_the_reason_and_the_way_to_a_new_request(pending, decider, rf):
    decided = vet_verification.decide(pending, Decision.REJECT, staff=decider, decision_note=REASON)

    vet_verification.send_decision_email(decided, rf.get("/"))

    (message,) = mail.outbox
    assert message.subject == "[BARF Nutri] Žádost o roli veterinárního lékaře byla zamítnuta"
    assert REASON in message.body and "zamítl vaši žádost" in message.body
    assert extract_link(message.body) == reverse(PAGE)


def test_the_revocation_e_mail_says_what_is_lost(pending, decider, rf):
    vet_verification.decide(pending, Decision.APPROVE, staff=decider, verification_method_note="x")
    revoked = vet_verification.decide(pending, Decision.REVOKE, staff=decider, decision_note=REASON)

    vet_verification.send_decision_email(revoked, rf.get("/"))

    (message,) = mail.outbox
    assert message.subject == "[BARF Nutri] Role veterinárního lékaře byla odebrána"
    assert REASON in message.body
    assert "ztratili" in message.body and "orientační" in message.body


def test_the_decision_e_mail_is_throttled_per_kind_and_account(pending, decider, rf):
    decided = vet_verification.decide(pending, Decision.REJECT, staff=decider, decision_note="x")

    assert vet_verification.send_decision_email(decided, rf.get("/")) is True
    assert vet_verification.send_decision_email(decided, rf.get("/")) is False
    assert len(mail.outbox) == 1


def test_an_approval_and_a_revocation_in_a_row_both_reach_the_user(pending, decider, rf):
    approved = vet_verification.decide(
        pending, Decision.APPROVE, staff=decider, verification_method_note="x"
    )
    revoked = vet_verification.decide(pending, Decision.REVOKE, staff=decider, decision_note="x")

    assert vet_verification.send_decision_email(approved, rf.get("/"))
    assert vet_verification.send_decision_email(revoked, rf.get("/"))


def test_no_e_mail_goes_to_an_inactive_account(pending, decider, rf):
    decided = vet_verification.decide(pending, Decision.REJECT, staff=decider, decision_note="x")
    User.objects.filter(pk=pending.user_id).update(is_active=False)
    decided = fresh(decided)

    assert vet_verification.send_decision_email(decided, rf.get("/")) is False
    assert mail.outbox == []


def test_the_daily_limit_of_account_e_mails_applies(pending, decider, rf, settings):
    settings.ACCOUNT_EMAIL_DAILY_LIMIT = 0
    decided = vet_verification.decide(pending, Decision.REJECT, staff=decider, decision_note="x")

    assert vet_verification.send_decision_email(decided, rf.get("/")) is False


# --- The page /ucet/veterinar/ -------------------------------------------------------------------


def test_the_page_needs_a_login(client):
    response = client.get(reverse(PAGE))

    assert response.status_code == 302
    assert response["Location"].startswith(reverse("accounts:login"))
    assert client.post(reverse(PAGE), {"workplace": "x"}).status_code == 302
    assert not VetVerificationRequest.objects.exists()


def test_the_page_explains_the_role_and_offers_the_form(logged_in_client):
    response = logged_in_client.get(reverse(PAGE))
    content = " ".join(response.content.decode().split())

    assert response.status_code == 200
    assert "Co role umožňuje" in content
    assert "Majitel s vámi může sdílet své zvíře" in content
    assert "jen dokud máte roli <strong>a</strong> majitel sdílení nezrušil" in content
    assert "Role neotevírá žádná zvířata, která s vámi nikdo nesdílí" in content
    assert "Zatím jste žádost nepodali" in content
    for name in ("workplace", "professional_id", "message"):
        assert f'name="{name}"' in content
    assert "Evidenční číslo v profesní evidenci, pokud existuje" in content
    assert "Odeslat žádost" in content
    assert "nepište rodné číslo" in content.lower()


def test_posting_the_request_needs_the_csrf_token(user):
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)

    response = client.post(reverse(PAGE), {"workplace": "Klinika"})

    assert response.status_code == 403
    assert not VetVerificationRequest.objects.exists()
    assert "csrfmiddlewaretoken" in client.get(reverse(PAGE)).content.decode()


def test_the_page_is_not_cached(logged_in_client):
    assert "no-store" in logged_in_client.get(reverse(PAGE))["Cache-Control"]


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_the_page_answers_only_get_and_post(logged_in_client, method):
    assert getattr(logged_in_client, method)(reverse(PAGE)).status_code == 405


def test_filing_a_request(logged_in_client, user, settings):
    settings.CONTACT_EMAIL = "podpora@barf.example.cz"
    data = {"workplace": "  Klinika   Praha ", "professional_id": " 1234 ", "message": "Dobrý den"}

    response = logged_in_client.post(reverse(PAGE), data, follow=True)

    item = VetVerificationRequest.objects.get(user=user)
    assert (item.workplace, item.professional_id, item.message) == (
        "Klinika Praha",
        "1234",
        "Dobrý den",
    )
    assert item.status == "PENDING"
    assert response.redirect_chain == [(reverse(PAGE), 302)]
    content = response.content.decode()
    assert "Žádost byla odeslána" in content
    assert "čeká na posouzení" in content
    assert 'name="workplace"' not in content  # no second request while one is pending
    assert [m.to for m in mail.outbox] == [["podpora@barf.example.cz"]]


def test_the_professional_number_and_the_message_are_optional(logged_in_client, user):
    logged_in_client.post(reverse(PAGE), {"workplace": "Klinika"})

    assert VetVerificationRequest.objects.get(user=user).professional_id == ""


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"workplace": "   "},
        {"workplace": "x" * 201},
        {"workplace": "Klinika", "professional_id": "1" * 65},
        {"workplace": "Klinika", "message": "z" * 1001},
    ],
)
def test_an_invalid_form_files_nothing(logged_in_client, data):
    response = logged_in_client.post(reverse(PAGE), data)

    assert response.status_code == 200
    assert "Formulář obsahuje chyby" in response.content.decode()
    assert not VetVerificationRequest.objects.exists()


def test_a_pending_request_is_shown_and_blocks_a_second_one(logged_in_client, pending, user):
    VetVerificationRequest.objects.filter(pk=pending.pk).update(user=user)

    page = logged_in_client.get(reverse(PAGE))
    content = " ".join(page.content.decode().split())
    assert "čeká na posouzení" in content and "Klinika Praha" in content
    assert "Do té doby další žádost podat nelze" in content
    assert 'name="workplace"' not in content

    response = logged_in_client.post(reverse(PAGE), {"workplace": "Jiná"}, follow=True)
    assert user.vet_verification_requests.count() == 1
    assert "Žádost teď nelze odeslat" in response.content.decode()


def test_a_vet_sees_the_role_and_no_form(logged_in_client, user, pending):
    user.groups.add(Group.objects.get(name=Role.VET))

    content = logged_in_client.get(reverse(PAGE)).content.decode()
    assert "Roli veterinárního lékaře máte" in content
    assert 'name="workplace"' not in content

    response = logged_in_client.post(reverse(PAGE), {"workplace": "Jiná"}, follow=True)
    assert not VetVerificationRequest.objects.filter(workplace="Jiná").exists()
    assert "Žádost teď nelze odeslat" in response.content.decode()


def test_a_rejected_applicant_reads_the_reason_and_may_apply_again(
    logged_in_client, user, decider, rf
):
    first = vet_verification.submit_request(user, workplace="První klinika")
    vet_verification.decide(first, Decision.REJECT, staff=decider, decision_note=REASON)

    content = " ".join(logged_in_client.get(reverse(PAGE)).content.decode().split())
    assert "zamítnuto" in content and REASON in content
    assert "Podat novou žádost" in content

    logged_in_client.post(reverse(PAGE), {"workplace": "Nová klinika"})
    assert [r.status for r in user.vet_verification_requests.order_by("pk")] == [
        "REJECTED",
        "PENDING",
    ]
    content = logged_in_client.get(reverse(PAGE)).content.decode()
    assert "Nová klinika" in content and "čeká na posouzení" in content


def test_a_revoked_applicant_sees_it_and_may_apply_again(logged_in_client, user, decider):
    item = vet_verification.submit_request(user, workplace="Klinika")
    vet_verification.decide(item, Decision.APPROVE, staff=decider, verification_method_note="x")
    vet_verification.decide(item, Decision.REVOKE, staff=decider, decision_note=REASON)

    content = " ".join(logged_in_client.get(reverse(PAGE)).content.decode().split())

    assert "role odebrána" in content and REASON in content
    assert "Podat novou žádost" in content


def test_an_approved_applicant_sees_the_approval(logged_in_client, user, decider):
    item = vet_verification.submit_request(user, workplace="Klinika")
    vet_verification.decide(
        item,
        Decision.APPROVE,
        staff=decider,
        verification_method_note=METHOD,
        decision_note="Vítejte mezi veterináři.",
    )

    content = logged_in_client.get(reverse(PAGE)).content.decode()

    assert "Roli veterinárního lékaře máte" in content
    assert "schváleno" in content and "Vítejte mezi veterináři." in content
    assert METHOD not in content  # the internal note is never shown to the applicant


def test_the_page_shows_only_the_own_requests(logged_in_client, pending):
    """``pending`` belongs to another account."""
    content = logged_in_client.get(reverse(PAGE)).content.decode()

    assert "Klinika Praha" not in content and "zadatel@example.cz" not in content
    assert "Zatím jste žádost nepodali" in content


def test_what_the_applicant_and_the_deciding_staff_wrote_is_escaped(
    logged_in_client, user, decider
):
    hostile = "<script>alert('x')</script><b onclick=1>"
    item = vet_verification.submit_request(
        user, workplace=hostile, professional_id=hostile, message=hostile
    )
    vet_verification.decide(item, Decision.REJECT, staff=decider, decision_note=hostile)

    content = logged_in_client.get(reverse(PAGE)).content.decode()

    assert "<script>alert" not in content and "<b onclick" not in content
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in content
    assert content.count("&lt;script&gt;") >= 2  # the workplace and the reason


def test_the_page_has_no_inline_script_or_style(logged_in_client):
    content = logged_in_client.get(reverse(PAGE)).content.decode()

    assert "<script" not in content and "style=" not in content
    assert "unsafe-inline" not in logged_in_client.get(reverse(PAGE))["Content-Security-Policy"]


def test_the_page_has_headings_in_order_and_labelled_sections(logged_in_client):
    content = logged_in_client.get(reverse(PAGE)).content.decode()

    assert content.count("<h1") == 1
    for section in ("vet-role-title", "vet-state-title", "vet-form-title"):
        assert f'aria-labelledby="{section}"' in content and f'id="{section}"' in content
    assert 'for="id_workplace"' in content


def test_the_status_is_icon_text_and_colour(logged_in_client, pending, user):
    VetVerificationRequest.objects.filter(pk=pending.pk).update(user=user)

    content = logged_in_client.get(reverse(PAGE)).content.decode()

    assert 'class="status status--info"' in content
    assert 'class="status__icon" aria-hidden="true">ⓘ</span>' in content
    assert "čeká na posouzení</span>" in content


def test_the_page_costs_a_constant_number_of_queries(
    logged_in_client, user, decider, django_assert_max_num_queries
):
    for number in range(4):
        item = vet_verification.submit_request(user, workplace=f"Klinika {number}")
        vet_verification.decide(item, Decision.REJECT, staff=decider, decision_note="x")

    with django_assert_max_num_queries(12):
        assert logged_in_client.get(reverse(PAGE)).status_code == 200


def test_the_profile_links_to_the_page_only_with_the_role_state_text(logged_in_client):
    content = " ".join(logged_in_client.get(reverse("accounts:profile")).content.decode().split())

    assert f'<a href="{reverse(PAGE)}">požádat o roli</a>' in content


# --- Export and deletion of the account ---------------------------------------------------------


def test_the_export_holds_what_the_user_wrote_and_was_told_but_no_internal_note(
    applicant, pending, decider
):
    vet_verification.decide(
        pending,
        Decision.APPROVE,
        staff=decider,
        verification_method_note=METHOD,
        decision_note="Vítejte.",
    )
    other = User.objects.create_user("jiny@example.cz")
    VetVerificationRequest.objects.create(user=other, workplace="Cizí klinika")

    section = build_export(applicant)["data"]["vet_verification"]

    assert section == [
        {
            "submitted_at": section[0]["submitted_at"],
            "professional_id": "1234",
            "workplace": "Klinika Praha",
            "message": "Prosím.",
            "status": {"code": "APPROVED", "label": "schváleno"},
            "decided_at": section[0]["decided_at"],
            "decision_note": "Vítejte.",
        }
    ]
    raw = str(build_export(applicant))
    assert METHOD not in raw and decider.email not in raw and "Cizí klinika" not in raw


def test_the_export_of_a_user_without_requests_has_an_empty_section(user):
    assert build_export(user)["data"]["vet_verification"] == []


def test_the_export_lists_the_requests_oldest_first(applicant, decider):
    first = vet_verification.submit_request(applicant, workplace="Starší")
    vet_verification.decide(first, Decision.REJECT, staff=decider, decision_note="x")
    VetVerificationRequest.objects.filter(pk=first.pk).update(
        submitted_at=timezone.now() - timedelta(days=3)
    )
    vet_verification.submit_request(applicant, workplace="Novější")

    names = [item["workplace"] for item in build_export(applicant)["data"]["vet_verification"]]

    assert names == ["Starší", "Novější"]
