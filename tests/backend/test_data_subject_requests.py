"""Requests of data subjects (docs/14 §14.12): the register, its deadline rules, the list, the
export and the erasure of an account for a verified request.

Every role against every action; the export is compared with the self-service export; the
erasure is compared with the self-service deletion and checked for completeness."""

import json
from datetime import timedelta

import pytest
from axes.models import AccessAttempt, AccessFailureLog, AccessLog
from django.apps import apps
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth.models import Permission
from django.db import IntegrityError, connection, transaction
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import data_subject, services, two_factor
from accounts.data_subject import DataSubjectRequestError
from accounts.deadlines import add_months
from accounts.export import build_export, export_json
from accounts.models import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
    User,
    VetVerificationRequest,
)
from accounts.roles import Role
from animals.models import (
    Animal,
    AnimalHealthCondition,
    AnimalShare,
    BodyMeasurement,
    HealthCondition,
)
from backoffice import access_log
from backoffice.models import AdminAccessAction as Action
from backoffice.models import AdminAccessLog
from tests.backend.helpers import PASSWORD, enroll, log_in_verified

pytestmark = pytest.mark.django_db

SUPPORT = Role.SUPPORT_ADMIN.value
ROLES = ["anonymous", "owner", "vet", SUPPORT, "data_curator", "nutrition_reviewer", "superuser"]
STAFF = {SUPPORT, "data_curator", "nutrition_reviewer", "superuser"}
ALLOWED = {SUPPORT, "superuser"}
EXPORT = "export_personal_data"
ERASE = "erase_account"


def list_url() -> str:
    return reverse("admin:accounts_datasubjectrequest_changelist")


def run(client, action, items, **extra):
    data = {"action": action, "_selected_action": [i.pk for i in items], "index": "0", **extra}
    return client.post(list_url(), data)


def messages_of(response) -> list[str]:
    return [str(m) for m in response.wsgi_request._messages]


def fresh(dsr) -> DataSubjectRequest:
    return DataSubjectRequest.objects.get(pk=dsr.pk)


def exists(user) -> bool:
    return User.objects.filter(pk=user.pk).exists()


@pytest.fixture
def make_dsr(db):
    def factory(user=None, **fields) -> DataSubjectRequest:
        values = {
            "request_type": "ERASURE",
            "received_via": "EMAIL",
            "subject_label": "účet č. 7",
            "identity_verified": True,
            "identity_note": "Ověřeno odpovědí z e-mailu účtu.",
            "user": user,
            **fields,
        }
        return DataSubjectRequest.objects.create(**values)

    return factory


@pytest.fixture
def subject(make_user) -> User:
    return make_user("subjekt@example.cz", first_name="Jana", last_name="Nováková")


@pytest.fixture
def support(make_user) -> User:
    return make_user("podpora@example.cz", roles=(Role.SUPPORT_ADMIN,))


@pytest.fixture
def support_client(client, support):
    log_in_verified(client, support)
    AdminAccessLog.objects.all().delete()
    return client


@pytest.fixture
def root_client(superuser):
    """A superuser's own client (not the shared ``client``: tests use both roles at once)."""
    client = Client()
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


def sign_in_with_device(client: Client, user: User, device) -> None:
    """Sign ``user`` in with a session that passed the second factor of their own ``device``
    (a user who enrolled must pass it at every sign-in)."""
    from django_otp import DEVICE_ID_SESSION_KEY

    client.force_login(user)
    session = client.session
    session[DEVICE_ID_SESSION_KEY] = device.persistent_id
    session.save()


def populate(owner: User, vet: User) -> dict:
    """Everything the application holds about ``owner``: animals with records, a share with a
    vet, a share received, two-factor devices, sign-in records, requests."""
    from animals.models import ActivityLevel, Sex, Species
    from animals.services import share_with_vet

    animal = Animal(
        owner=owner, name="Rex", species=Species.DOG, sex=Sex.MALE, activity_level=ActivityLevel.LOW
    )
    animal.full_clean()
    animal.save()
    animal.name = "Rex II"
    animal.save()  # a second history record
    BodyMeasurement.objects.create(
        animal=animal, measured_on=timezone.localdate(), weight_kg="20", assessed_by="OWNER"
    )
    AnimalHealthCondition.objects.create(
        animal=animal, condition=HealthCondition.objects.get(code="CKD")
    )
    share = share_with_vet(animal, vet.email, owner)
    # ``owner`` is also a vet of somebody else's animal
    other_owner = User.objects.create_user(f"majitel-{owner.pk}@example.cz")
    foreign = Animal(
        owner=other_owner,
        name="Cizí",
        species=Species.CAT,
        sex=Sex.FEMALE,
        activity_level=ActivityLevel.LOW,
    )
    foreign.full_clean()
    foreign.save()
    device = enroll(owner)
    codes = two_factor.generate_recovery_codes(owner)
    for model in (AccessLog, AccessAttempt, AccessFailureLog):
        fields = {"username": owner.email, "ip_address": "10.0.0.1", "user_agent": "x"}
        if model is AccessAttempt:
            fields["failures_since_start"] = 1
        model.objects.create(**fields)
    request = VetVerificationRequest.objects.create(user=owner, workplace="Klinika")
    return {
        "animal": animal,
        "share": share,
        "foreign": foreign,
        "device": device,
        "codes": codes,
        "vet_request": request,
    }


# --- The model and its deadline rules -------------------------------------------------------------


def test_the_register_is_marked_as_personal_data_and_has_no_personal_text(make_dsr, subject):
    dsr = make_dsr(subject)

    assert DataSubjectRequest.contains_personal_data is True
    assert str(dsr) == f"žádost subjektu údajů č. {dsr.pk}"
    assert subject.email not in str(dsr)


def test_the_label_help_text_asks_for_a_pseudonym():
    help_text = DataSubjectRequest._meta.get_field("subject_label").help_text

    assert "Pseudonym" in help_text and "Nepište celé jméno" in help_text


def test_the_deadline_defaults_to_one_month_after_receipt(make_dsr):
    dsr = make_dsr(received_on=timezone.localdate().replace(day=1))

    assert dsr.due_on == add_months(dsr.received_on, 1)
    assert dsr.standard_due_date() == dsr.due_on


def test_the_period_is_a_setting(make_dsr, settings):
    settings.DATA_SUBJECT_REQUEST_PERIOD_MONTHS = 2
    dsr = make_dsr(received_on=timezone.localdate().replace(day=1))

    assert dsr.due_on == add_months(dsr.received_on, 2)


def test_the_working_period_is_one_month():
    from django.conf import settings

    assert settings.DATA_SUBJECT_REQUEST_PERIOD_MONTHS == 1


def test_saving_again_does_not_move_a_deadline_that_was_extended(make_dsr):
    dsr = make_dsr()
    dsr.due_on += timedelta(days=30)
    dsr.extension_reason = "Složitá žádost."
    dsr.save()

    again = fresh(dsr)
    again.outcome_note = "Poznámka."
    again.save()

    assert fresh(dsr).due_on == dsr.due_on


def test_another_deadline_needs_a_reason(make_dsr):
    dsr = make_dsr()
    dsr.due_on += timedelta(days=10)

    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError) as caught:
        dsr.full_clean()
    assert "extension_reason" in caught.value.error_dict

    dsr.extension_reason = "   "
    with pytest.raises(ValidationError):
        dsr.full_clean()

    dsr.extension_reason = "Složitá žádost, ověření u správce zálohování."
    dsr.full_clean()


def test_a_shorter_deadline_needs_a_reason_too(make_dsr):
    from django.core.exceptions import ValidationError

    dsr = make_dsr()
    dsr.due_on -= timedelta(days=5)

    with pytest.raises(ValidationError) as caught:
        dsr.full_clean()
    assert "extension_reason" in caught.value.error_dict


def test_the_standard_deadline_needs_no_reason(make_dsr):
    dsr = make_dsr()
    dsr.full_clean()


def test_verified_identity_needs_its_note_in_the_form_but_not_in_the_database(make_dsr):
    from django.core.exceptions import ValidationError

    dsr = make_dsr(identity_verified=True, identity_note="")

    with pytest.raises(ValidationError) as caught:
        dsr.full_clean()
    assert "identity_note" in caught.value.error_dict


def test_a_rejection_needs_its_reason(make_dsr):
    from django.core.exceptions import ValidationError

    dsr = make_dsr(status="REJECTED", outcome_note="")

    with pytest.raises(ValidationError) as caught:
        dsr.full_clean()
    assert "outcome_note" in caught.value.error_dict


@pytest.mark.parametrize("status", ["COMPLETED", "REJECTED"])
def test_a_finished_request_gets_the_date_of_completion(make_dsr, status):
    dsr = make_dsr(status=status, outcome_note="Hotovo.")

    assert dsr.completed_on == timezone.localdate()


def test_an_open_request_has_no_date_of_completion(make_dsr):
    dsr = make_dsr(status="COMPLETED", outcome_note="x")
    dsr.status = "IN_PROGRESS"
    dsr.save()

    assert fresh(dsr).completed_on is None


def test_a_given_date_of_completion_is_kept(make_dsr):
    day = timezone.localdate() - timedelta(days=3)

    dsr = make_dsr(status="COMPLETED", completed_on=day, outcome_note="x")

    assert fresh(dsr).completed_on == day


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "COMPLETED", "completed_on": None},
        {"status": "RECEIVED", "completed_on": timezone.localdate()},
        {"status": "UNKNOWN"},
        {"request_type": "UNKNOWN"},
        {"received_via": "UNKNOWN"},
        {"due_on": timezone.localdate() - timedelta(days=400)},
    ],
)
def test_the_database_refuses_an_inconsistent_record(make_dsr, changes):
    dsr = make_dsr()

    with pytest.raises(IntegrityError), transaction.atomic():
        DataSubjectRequest.objects.filter(pk=dsr.pk).update(**changes)


def test_an_update_of_chosen_fields_keeps_the_dates_consistent(make_dsr):
    dsr = make_dsr()
    dsr.status = "COMPLETED"
    dsr.save(update_fields=["status"])

    assert fresh(dsr).completed_on == timezone.localdate()


def test_the_record_survives_the_erasure_of_the_account_without_the_link(make_dsr, subject):
    dsr = make_dsr(subject)

    services.delete_account(subject)

    kept = fresh(dsr)
    assert kept.user is None and kept.subject_label == "účet č. 7"


def test_the_record_survives_the_deletion_of_the_handling_account(make_dsr, support):
    dsr = make_dsr(handled_by=support)

    support.delete()

    assert fresh(dsr).handled_by is None


def test_the_history_keeps_every_change(make_dsr):
    dsr = make_dsr()
    dsr.status = "IN_PROGRESS"
    dsr.save()

    assert [h.status for h in dsr.history.order_by("history_date")] == ["RECEIVED", "IN_PROGRESS"]


def test_the_open_and_finished_statuses_are_exact():
    from accounts.models import FINISHED_REQUEST_STATUSES, OPEN_REQUEST_STATUSES

    assert set(OPEN_REQUEST_STATUSES) | set(FINISHED_REQUEST_STATUSES) == set(
        DataSubjectRequestStatus.values
    )
    assert not set(OPEN_REQUEST_STATUSES) & set(FINISHED_REQUEST_STATUSES)


# --- The list and the form ------------------------------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
def test_who_sees_the_register(client_for, make_dsr, role):
    make_dsr(subject_label="viditelná-žádost")

    response = client_for(role).get(list_url())

    expected = 200 if role in ALLOWED else (403 if role in STAFF else 302)
    assert response.status_code == expected
    assert ("viditelná-žádost" in response.content.decode()) == (role in ALLOWED)


@pytest.mark.parametrize("role", ROLES)
def test_who_adds_a_request(client_for, role):
    url = reverse("admin:accounts_datasubjectrequest_add")

    response = client_for(role).get(url)

    assert response.status_code == (200 if role in ALLOWED else (403 if role in STAFF else 302))


def test_only_a_superuser_deletes_a_record_of_a_request(client_for, make_dsr):
    dsr = make_dsr()
    url = reverse("admin:accounts_datasubjectrequest_delete", args=[dsr.pk])

    assert client_for(SUPPORT).get(url).status_code == 403
    assert client_for("superuser").get(url).status_code == 200


def deadline_cell(content: str) -> str:
    return content.split('class="field-deadline">')[1].split("</td>")[0]


@pytest.mark.parametrize(
    ("days", "status", "css", "icon", "text"),
    [
        (-3, "RECEIVED", "danger", "⛔", "po termínu o 3 d"),
        (-1, "IN_PROGRESS", "danger", "⛔", "po termínu o 1 d"),
        (0, "RECEIVED", "warning", "⚠", "blíží se termín, zbývá 0 d"),
        (5, "IN_PROGRESS", "warning", "⚠", "blíží se termín, zbývá 5 d"),
        (20, "RECEIVED", "info", "ⓘ", "v termínu, zbývá 20 d"),
        (-30, "COMPLETED", "success", "✓", "vyřízeno"),
        (-30, "REJECTED", "success", "✓", "vyřízeno"),
    ],
)
def test_the_deadline_column_is_icon_text_and_colour(
    support_client, make_dsr, days, status, css, icon, text
):
    due = timezone.localdate() + timedelta(days=days)
    make_dsr(
        status=status,
        outcome_note="x",
        received_on=min(due, timezone.localdate()),
        due_on=due,
        extension_reason="x",
    )

    cell = deadline_cell(support_client.get(list_url()).content.decode())

    assert f'class="barf-status barf-status--{css}"' in cell
    assert f'<span aria-hidden="true">{icon}</span>' in cell
    assert text in cell  # the text carries the meaning, the colour and the icon only add


def test_the_filter_on_the_deadline(support_client, make_dsr):
    today = timezone.localdate()
    make_dsr(
        subject_label="pozdní",
        received_on=today - timedelta(days=40),
        due_on=today - timedelta(days=10),
        extension_reason="x",
    )
    make_dsr(subject_label="včasná")
    make_dsr(
        subject_label="vyřízená-pozdní",
        status="COMPLETED",
        outcome_note="x",
        received_on=today - timedelta(days=40),
        due_on=today - timedelta(days=10),
        extension_reason="x",
    )

    late = support_client.get(list_url(), {"po_terminu": "ano"}).content.decode()
    other = support_client.get(list_url(), {"po_terminu": "ne"}).content.decode()

    assert "pozdní" in late and "včasná" not in late and "vyřízená-pozdní" not in late
    assert "včasná" in other and "vyřízená-pozdní" in other and ">pozdní<" not in other


def test_the_other_filters_and_the_search(support_client, make_dsr, subject):
    make_dsr(subject, subject_label="a-výmaz", request_type="ERASURE")
    make_dsr(
        subject_label="b-přístup",
        request_type="ACCESS",
        identity_verified=False,
        identity_note="",
        received_via="POST",
    )

    erasure = support_client.get(list_url(), {"request_type__exact": "ERASURE"}).content.decode()
    verified = support_client.get(list_url(), {"identity_verified__exact": "0"}).content.decode()
    post = support_client.get(list_url(), {"received_via__exact": "POST"}).content.decode()
    by_account = support_client.get(list_url(), {"q": "subjekt@"}).content.decode()
    by_label = support_client.get(list_url(), {"q": "b-přístup"}).content.decode()

    assert "a-výmaz" in erasure and "b-přístup" not in erasure
    assert "b-přístup" in verified and "a-výmaz" not in verified
    assert "b-přístup" in post and "a-výmaz" not in post
    assert "a-výmaz" in by_account and "b-přístup" not in by_account
    assert "b-přístup" in by_label and "a-výmaz" not in by_label


def test_the_list_costs_the_same_queries_for_one_request_and_for_many(
    support_client, make_dsr, make_user
):
    make_dsr(make_user("u0@example.cz"))
    with CaptureQueriesContext(connection) as one:
        support_client.get(list_url())
    for number in range(1, 9):
        make_dsr(make_user(f"u{number}@example.cz"), status="IN_PROGRESS")
    with CaptureQueriesContext(connection) as many:
        support_client.get(list_url())

    assert len(many) == len(one)


def add_data(**changes) -> dict:
    data = {
        "request_type": "ACCESS",
        "received_on": timezone.localdate().isoformat(),
        "received_via": "EMAIL",
        "subject_label": "účet č. 15",
        "identity_verified": "",
        "identity_note": "",
        "due_on": "",
        "extension_reason": "",
        "status": "RECEIVED",
        "outcome_note": "",
        **changes,
    }
    return {key: value for key, value in data.items() if value != ""}


def test_adding_a_request_fills_the_deadline_and_the_handler(support_client, support):
    response = support_client.post(
        reverse("admin:accounts_datasubjectrequest_add"), add_data(), follow=True
    )

    dsr = DataSubjectRequest.objects.get()
    assert response.status_code == 200
    assert dsr.due_on == add_months(dsr.received_on, 1)
    assert dsr.handled_by == support and dsr.status == "RECEIVED"


def test_another_deadline_is_accepted_only_with_a_reason(support_client):
    url = reverse("admin:accounts_datasubjectrequest_add")
    later = (timezone.localdate() + timedelta(days=90)).isoformat()

    refused = support_client.post(url, add_data(due_on=later))
    assert refused.status_code == 200 and not DataSubjectRequest.objects.exists()
    assert "Jiný termín než standardní lhůtu" in refused.content.decode()

    accepted = support_client.post(url, add_data(due_on=later, extension_reason="Složitá žádost."))
    assert accepted.status_code == 302
    dsr = DataSubjectRequest.objects.get()
    assert dsr.due_on.isoformat() == later and dsr.extension_reason == "Složitá žádost."


def test_changing_the_deadline_of_a_recorded_request_needs_a_reason(support_client, make_dsr):
    dsr = make_dsr()
    url = reverse("admin:accounts_datasubjectrequest_change", args=[dsr.pk])
    data = add_data(due_on=(dsr.due_on + timedelta(days=20)).isoformat())
    data.pop("received_on")  # read-only once recorded

    refused = support_client.post(url, data)
    assert refused.status_code == 200 and fresh(dsr).due_on == dsr.due_on

    data["extension_reason"] = "Složitá žádost."
    assert support_client.post(url, data).status_code == 302
    assert fresh(dsr).due_on == dsr.due_on + timedelta(days=20)


def test_the_day_of_receipt_cannot_be_edited_once_recorded(support_client, make_dsr):
    dsr = make_dsr()
    url = reverse("admin:accounts_datasubjectrequest_change", args=[dsr.pk])

    content = support_client.get(url).content.decode()
    assert 'name="received_on"' not in content
    assert 'name="handled_by"' not in content and 'name="completed_on"' not in content

    data = add_data(received_on="2020-01-01", due_on=dsr.due_on.isoformat())
    support_client.post(url, data)
    assert fresh(dsr).received_on == dsr.received_on


def test_support_cannot_link_a_staff_account_but_a_superuser_can(
    support_client, root_client, make_user
):
    staff = make_user("kolega@example.cz", roles=(Role.DATA_CURATOR,))
    url = reverse("admin:accounts_datasubjectrequest_add")

    refused = support_client.post(url, add_data(user=staff.pk))
    assert refused.status_code == 200 and not DataSubjectRequest.objects.exists()

    accepted = root_client.post(url, add_data(user=staff.pk))
    assert accepted.status_code == 302 and DataSubjectRequest.objects.get().user == staff


def test_a_subject_label_with_markup_is_escaped(support_client, make_dsr):
    hostile = "<script>alert(1)</script>"
    dsr = make_dsr(subject_label=hostile, identity_note=hostile, outcome_note=hostile)

    pages = [
        support_client.get(list_url()).content.decode(),
        support_client.get(
            reverse("admin:accounts_datasubjectrequest_change", args=[dsr.pk])
        ).content.decode(),
    ]

    for content in pages:
        assert "<script>alert(1)" not in content
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in content


def test_changes_are_in_the_history_and_the_access_log(support_client, make_dsr):
    dsr = make_dsr()
    AdminAccessLog.objects.all().delete()
    url = reverse("admin:accounts_datasubjectrequest_change", args=[dsr.pk])

    support_client.get(url)
    data = add_data(status="IN_PROGRESS", due_on=dsr.due_on.isoformat())
    data.pop("received_on")
    support_client.post(url, data)
    support_client.get(reverse("admin:accounts_datasubjectrequest_history", args=[dsr.pk]))

    assert [r.action for r in AdminAccessLog.objects.order_by("pk")] == [
        Action.VIEW_OBJECT,
        Action.CHANGE,
        Action.VIEW_OBJECT,
    ]
    assert [h.status for h in dsr.history.order_by("history_date")] == ["RECEIVED", "IN_PROGRESS"]


# --- Exporting the data of an account -------------------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
def test_who_exports(client_for, make_dsr, subject, role):
    dsr = make_dsr(subject, request_type="ACCESS")

    response = run(client_for(role), EXPORT, [dsr])

    if role in ALLOWED:
        assert response.status_code == 200
        assert response["Content-Type"] == "application/json; charset=utf-8"
    else:
        assert response.status_code == (403 if role in STAFF else 302)


def test_a_staff_member_with_other_permissions_cannot_export(client, make_user, make_dsr, subject):
    viewer = make_user("revizor@example.cz", roles=(Role.DATA_CURATOR,))
    viewer.user_permissions.add(
        *Permission.objects.filter(
            codename__in=["view_datasubjectrequest", "change_datasubjectrequest"]
        )
    )
    log_in_verified(client, viewer)
    dsr = make_dsr(subject)

    page = client.get(list_url())
    response = run(client, EXPORT, [dsr])

    assert page.status_code == 200 and f'value="{EXPORT}"' not in page.content.decode()
    assert response.status_code == 200 and "attachment" not in response.get(
        "Content-Disposition", ""
    )


def test_the_export_is_the_file_of_the_self_service_download(
    support_client, make_dsr, subject, vet_user
):
    world = populate(subject, vet_user)
    dsr = make_dsr(subject, request_type="ACCESS")

    mine = Client()
    sign_in_with_device(mine, subject, world["device"])  # (this sign-in is part of the data)
    response = run(support_client, EXPORT, [dsr])
    own = mine.get(reverse("accounts:export"))

    def body(raw: bytes) -> dict:
        data = json.loads(raw)
        data.pop("generated_at")
        return data

    assert body(response.content) == body(own.content)
    assert response.content.decode().startswith('{\n  "format": "barf-nutri-personal-data"')


def test_the_export_function_is_the_same_one(subject):
    first, second = json.loads(export_json(subject)), build_export(subject)

    first.pop("generated_at"), second.pop("generated_at")
    assert first == second


def test_the_file_is_an_attachment_named_after_the_request_not_the_account(
    support_client, make_dsr, subject
):
    dsr = make_dsr(subject)

    response = run(support_client, EXPORT, [dsr])

    disposition = response["Content-Disposition"]
    assert disposition == (
        f'attachment; filename="barf-nutri-export-zadost-{dsr.pk}-'
        f'{timezone.localdate().isoformat()}.json"'
    )
    assert "subjekt" not in disposition and "no-store" in response["Cache-Control"]


def test_the_export_holds_the_data_of_the_account_and_no_secret(
    support_client, make_dsr, subject, vet_user
):
    world = populate(subject, vet_user)
    dsr = make_dsr(subject)

    content = run(support_client, EXPORT, [dsr]).content.decode()
    data = json.loads(content)["data"]

    assert data["account"]["email"] == subject.email
    assert [a["name"] for a in data["animals"]["owned_animals"]] == ["Rex II"]
    assert data["two_factor"] == {
        "enrolled": True,
        "confirmed_at": data["two_factor"]["confirmed_at"],
        "unused_recovery_codes": 10,
    }
    assert data["vet_verification"][0]["workplace"] == "Klinika"
    assert data["data_subject_requests"][0]["request_type"]["code"] == "ERASURE"
    # No password hash, no secret of the authenticator, no recovery code, nobody else.
    assert subject.password not in content
    assert world["device"].key not in content
    for code in world["codes"]:
        assert code.replace("-", "").lower() not in content.lower()
    assert world["foreign"].name not in content and vet_user.email in content  # (the shared vet)


def test_the_export_leaves_two_rows_in_the_access_log_and_a_note_in_the_history(
    support_client, make_dsr, subject
):
    dsr = make_dsr(subject)

    run(support_client, EXPORT, [dsr])

    rows = list(AdminAccessLog.objects.order_by("pk"))
    assert [(r.action, r.model, r.object_pk) for r in rows] == [
        (Action.EXPORT, "datasubjectrequest", str(dsr.pk)),
        (Action.EXPORT, "user", str(subject.pk)),
    ]
    entry = LogEntry.objects.get(action_flag=CHANGE, object_id=str(dsr.pk))
    assert entry.change_message == "Vytvořen export osobních údajů účtu."
    assert subject.email not in entry.change_message + entry.object_repr


def test_the_export_does_not_change_the_request(support_client, make_dsr, subject):
    dsr = make_dsr(subject)
    before = fresh(dsr)

    run(support_client, EXPORT, [dsr])

    after = fresh(dsr)
    assert (after.status, after.user, after.completed_on) == (
        before.status,
        before.user,
        before.completed_on,
    )


@pytest.mark.parametrize(
    ("changes", "text"),
    [
        ({"identity_verified": False, "identity_note": ""}, "Totožnost žadatele není ověřena."),
        ({"status": "COMPLETED", "outcome_note": "x"}, "Žádost už je vyřízena."),
        ({"status": "REJECTED", "outcome_note": "x"}, "Žádost už je vyřízena."),
    ],
)
def test_an_export_is_refused_for_an_unverified_or_finished_request(
    support_client, make_dsr, subject, changes, text
):
    dsr = make_dsr(subject, **changes)

    response = run(support_client, EXPORT, [dsr])

    assert response.status_code == 302
    assert f"Export nelze vytvořit: {text}" in messages_of(response)
    assert not AdminAccessLog.objects.filter(action=Action.EXPORT).exists()
    assert [r.action for r in AdminAccessLog.objects.all()] == [Action.VIEW_OBJECT]


def test_an_export_is_refused_without_a_linked_account(support_client, make_dsr):
    dsr = make_dsr(None)

    response = run(support_client, EXPORT, [dsr])

    assert "Export nelze vytvořit: K žádosti není přiřazen účet žadatele." in messages_of(response)


def test_one_request_at_a_time(support_client, make_dsr, subject, make_user):
    first, second = make_dsr(subject), make_dsr(make_user("druhy@example.cz"))

    response = run(support_client, EXPORT, [first, second])

    assert messages_of(response) == ["Vyberte právě jednu žádost."]
    assert not AdminAccessLog.objects.filter(action=Action.EXPORT).exists()


def test_support_cannot_export_a_staff_account_but_a_superuser_can(
    support_client, root_client, make_dsr, make_user
):
    staff = make_user("kolega@example.cz", roles=(Role.DATA_CURATOR,))
    dsr = make_dsr(staff)

    refused = run(support_client, EXPORT, [dsr])
    granted = run(root_client, EXPORT, [dsr])

    assert "Export nelze vytvořit: Účty správců vyřizuje jen superuživatel." in messages_of(refused)
    assert granted.status_code == 200 and "attachment" in granted["Content-Disposition"]


def test_the_service_checks_the_permission_itself(make_dsr, subject, make_user):
    dsr = make_dsr(subject)
    from django.core.exceptions import PermissionDenied

    for role in (Role.OWNER, Role.VET, Role.DATA_CURATOR, Role.NUTRITION_REVIEWER):
        with pytest.raises(PermissionDenied):
            data_subject.export_for_request(dsr, make_user(f"{role}@example.cz", roles=(role,)))


# --- Erasing an account ---------------------------------------------------------------------------


def erase(client, dsr, email="subjekt@example.cz", **extra):
    return run(client, ERASE, [dsr], post="yes", confirm_email=email, **extra)


@pytest.mark.parametrize("role", ROLES)
def test_who_erases(client_for, make_dsr, subject, role):
    dsr = make_dsr(subject)
    client = client_for(role)

    shown = run(client, ERASE, [dsr])
    done = erase(client, dsr)

    if role in ALLOWED:
        assert shown.status_code == 200 and done.status_code == 302
        assert not exists(subject) and fresh(dsr).status == "COMPLETED"
    else:
        expected = 403 if role in STAFF else 302
        assert shown.status_code == done.status_code == expected
        assert exists(subject) and fresh(dsr).status == "RECEIVED"


def test_support_may_erase_only_a_non_staff_account(
    support_client, root_client, make_dsr, make_user
):
    staff = make_user("kolega@example.cz", roles=(Role.DATA_CURATOR,))
    dsr = make_dsr(staff)

    refused = erase(support_client, dsr, "kolega@example.cz")
    still = exists(staff)
    granted = erase(root_client, dsr, "kolega@example.cz")

    assert "Výmaz nelze provést: Účty správců vyřizuje jen superuživatel." in messages_of(refused)
    assert still and not exists(staff)
    assert granted.status_code == 302 and fresh(dsr).status == "COMPLETED"


def test_a_superuser_account_needs_a_superuser(support_client, make_dsr, superuser, make_user):
    make_user("druhy-root@example.cz", roles=(), is_superuser=True)
    dsr = make_dsr(superuser)

    response = erase(support_client, dsr, superuser.email)

    assert exists(superuser)
    assert "Účty správců vyřizuje jen superuživatel." in " ".join(messages_of(response))


def test_nobody_erases_the_own_account_this_way(root_client, make_dsr, superuser, make_user):
    make_user("druhy-root@example.cz", roles=(), is_superuser=True)
    dsr = make_dsr(superuser)

    page = run(root_client, ERASE, [dsr])
    response = erase(root_client, dsr, superuser.email)

    assert page.status_code == 302 and response.status_code == 302
    assert "Vlastní účet tímto postupem smazat nelze" in " ".join(messages_of(response))
    assert exists(superuser) and fresh(dsr).status == "RECEIVED"


def test_a_superuser_may_erase_another_superuser_who_is_not_the_last(
    root_client, make_dsr, make_user
):
    """The actor is an active superuser too, so a superuser account can go without leaving the
    administration without one."""
    other = make_user("druhy-root@example.cz", roles=(), is_superuser=True)
    dsr = make_dsr(other)

    response = erase(root_client, dsr, other.email)

    assert response.status_code == 302 and not exists(other)
    assert User.objects.filter(is_superuser=True, is_active=True).exists()


@pytest.mark.parametrize(
    ("changes", "text"),
    [
        ({"identity_verified": False, "identity_note": ""}, "Totožnost žadatele není ověřena."),
        ({"status": "COMPLETED", "outcome_note": "x"}, "Žádost už je vyřízena."),
    ],
)
def test_an_erasure_is_refused_for_an_unverified_or_finished_request(
    support_client, make_dsr, subject, changes, text
):
    dsr = make_dsr(subject, **changes)

    shown = run(support_client, ERASE, [dsr])
    done = erase(support_client, dsr)

    for response in (shown, done):
        assert response.status_code == 302
        assert f"Výmaz nelze provést: {text}" in messages_of(response)
    assert exists(subject)


def test_an_erasure_is_refused_without_a_linked_account(support_client, make_dsr):
    dsr = make_dsr(None)

    response = run(support_client, ERASE, [dsr])

    assert "Výmaz nelze provést: K žádosti není přiřazen účet žadatele." in messages_of(response)


def test_the_page_names_the_account_and_lists_what_will_be_deleted(
    support_client, make_dsr, subject, vet_user
):
    populate(subject, vet_user)
    dsr = make_dsr(subject)

    response = run(support_client, ERASE, [dsr])
    content = " ".join(response.content.decode().split())

    assert response.status_code == 200
    assert "Provést výmaz účtu" in content
    assert f"Žádost č. {dsr.pk}: výmaz (čl. 17)" in content
    assert "<strong>subjekt@example.cz</strong>" in content
    for line in (
        "Zvířata: 1",
        "Měření hmotnosti a kondice: 1",
        "Zdravotní stavy zvířat: 1",
        "Sdílení s veterináři: 1",
        "Uživatelé: 1",
        "Žádosti o ověření veterináře: 1",
        "Záznamy o přihlášení (django-axes): 3",
    ):
        assert f"<li>{line}</li>" in content, line
    assert "Smazání nelze vrátit" in content
    assert 'name="confirm_email"' in content
    assert "Trvale smazat účet" in content
    assert 'class="barf-danger"' in content  # a destructive action: the red button
    assert "Vazby z" not in content  # the table behind the many-to-many field is no record
    assert exists(subject)


def test_the_page_costs_a_bounded_number_of_queries(
    support_client, make_dsr, subject, vet_user, django_assert_max_num_queries
):
    populate(subject, vet_user)
    dsr = make_dsr(subject)

    with django_assert_max_num_queries(60):
        assert run(support_client, ERASE, [dsr]).status_code == 200


def test_the_page_escapes_the_names_it_shows(support_client, make_dsr, make_user):
    hostile = make_user("<b>x</b>@example.cz")
    dsr = make_dsr(hostile)

    content = run(support_client, ERASE, [dsr]).content.decode()

    assert "<b>x</b>@" not in content and "&lt;b&gt;x&lt;/b&gt;@example.cz" in content


@pytest.mark.parametrize("typed", ["", "jiny@example.cz", "subjekt@example.cz.cz", "Subjekt"])
def test_a_wrong_e_mail_deletes_nothing(support_client, make_dsr, subject, typed):
    dsr = make_dsr(subject)

    response = erase(support_client, dsr, typed)

    assert response.status_code == 200  # the page again, with the error
    assert "není e-mailem tohoto účtu" in response.content.decode() or typed == ""
    assert exists(subject) and fresh(dsr).status == "RECEIVED"


@pytest.mark.parametrize("typed", ["subjekt@example.cz", "  SUBJEKT@Example.CZ  "])
def test_the_typed_e_mail_ignores_case_and_spaces(support_client, make_dsr, subject, typed):
    dsr = make_dsr(subject)

    response = erase(support_client, dsr, typed)

    assert response.status_code == 302 and not exists(subject)


def test_the_request_is_completed_with_an_automatic_note(
    support_client, support, make_dsr, subject, vet_user
):
    populate(subject, vet_user)
    dsr = make_dsr(subject, status="IN_PROGRESS")

    response = erase(support_client, dsr)

    done = fresh(dsr)
    assert response.status_code == 302
    assert messages_of(response) == ["Účet byl smazán a žádost označena jako vyřízená."]
    assert done.status == "COMPLETED" and done.completed_on == timezone.localdate()
    assert done.user is None and done.handled_by == support
    note = done.outcome_note
    assert note.startswith("Výmaz účtu proveden správcem dne ")
    assert "zvířata: 1" in note and "měření hmotnosti a kondice: 1" in note
    assert "Zálohy databáze obsahují údaje do uplynutí doby uchování záloh." in note
    assert "subjekt" not in note and "Nováková" not in note  # no personal data in the record
    assert [h.status for h in done.history.order_by("history_date")][-1] == "COMPLETED"


def test_the_handler_who_was_set_stays(support_client, make_dsr, subject, make_user):
    colleague = make_user("kolega@example.cz", roles=(Role.SUPPORT_ADMIN,))
    dsr = make_dsr(subject, handled_by=colleague)

    erase(support_client, dsr)

    assert fresh(dsr).handled_by == colleague


def test_nothing_of_the_account_is_left(support_client, make_dsr, subject, vet_user):
    world = populate(subject, vet_user)
    dsr = make_dsr(subject)
    animal_history = Animal.history.model
    assert animal_history.objects.filter(id=world["animal"].pk).count() == 2

    erase(support_client, dsr)

    assert not exists(subject)
    assert not Animal.objects.filter(pk=world["animal"].pk).exists()
    assert not BodyMeasurement.objects.exists() and not AnimalHealthCondition.objects.exists()
    assert not AnimalShare.objects.exists()
    assert not animal_history.objects.filter(id=world["animal"].pk).exists()
    assert not BodyMeasurement.history.model.objects.exists()
    assert not AnimalShare.history.model.objects.exists()
    assert not AnimalHealthCondition.history.model.objects.exists()
    assert not TOTPDevice.objects.filter(pk=world["device"].pk).exists()
    assert not StaticDevice.objects.filter(user_id=subject.pk).exists()
    assert not StaticToken.objects.filter(device__user_id=subject.pk).exists()
    for model in (AccessLog, AccessAttempt, AccessFailureLog):
        assert not model.objects.filter(username="subjekt@example.cz").exists()
    assert not VetVerificationRequest.objects.exists()
    assert not VetVerificationRequest.history.model.objects.exists()
    assert Animal.objects.filter(pk=world["foreign"].pk).exists()  # nobody else's data
    assert User.objects.filter(pk=vet_user.pk).exists()


def test_the_log_of_the_administration_keeps_no_text_of_the_account(
    support_client, make_dsr, subject, vet_user, support
):
    world = populate(subject, vet_user)
    from django.contrib.admin.models import ADDITION

    LogEntry.objects.log_actions(support.pk, [subject], CHANGE, "x", single_object=True)
    LogEntry.objects.log_actions(support.pk, [world["animal"]], ADDITION, "x", single_object=True)
    dsr = make_dsr(subject)

    erase(support_client, dsr)

    texts = " ".join(LogEntry.objects.values_list("object_repr", flat=True))
    assert "subjekt@example.cz" not in texts and "Rex" not in texts
    assert "[smazaný záznam]" in texts


def test_it_is_the_function_of_the_self_service_deletion(
    support_client, make_dsr, subject, monkeypatch
):
    assert data_subject.services.delete_account is services.delete_account
    calls = []
    real = services.delete_account

    def spy(user):
        calls.append(user.pk)
        return real(user)

    monkeypatch.setattr(services, "delete_account", spy)
    dsr = make_dsr(subject)

    erase(support_client, dsr)

    assert calls == [subject.pk]


def test_the_view_of_the_self_service_deletion_calls_the_same_function(
    client, subject, monkeypatch
):
    calls = []
    real = services.delete_account
    monkeypatch.setattr(
        services, "delete_account", lambda user: (calls.append(user.pk), real(user))
    )
    client.force_login(subject)

    client.post(reverse("accounts:delete"), {"password": PASSWORD})

    assert calls == [subject.pk]


def table_counts() -> dict[str, int]:
    """The number of rows in every table the account's data can live in."""
    skip = {
        "accounts.DataSubjectRequest",
        "accounts.HistoricalDataSubjectRequest",
        "admin.LogEntry",
        "backoffice.AdminAccessLog",
        "sessions.Session",
    }
    return {
        model._meta.label: model.objects.count()
        for model in apps.get_models()
        if model._meta.label not in skip and not model._meta.auto_created
    }


def test_the_erasure_leaves_the_same_database_as_the_self_service_deletion(
    support_client, make_dsr, make_user, vet_user
):
    """Two accounts with the same data: one deleted by its owner, one for a request. Whatever
    the first deletion removes, the second removes as well, and nothing more."""
    left, right = make_user("leva@example.cz"), make_user("prava@example.cz")
    left_world = populate(left, vet_user)
    populate(right, vet_user)
    dsr = make_dsr(right)
    before = table_counts()

    owner_client = Client()
    sign_in_with_device(owner_client, left, left_world["device"])
    owner_client.post(reverse("accounts:delete"), {"password": PASSWORD})
    after_self_service = table_counts()
    erase(support_client, dsr, "prava@example.cz")
    after_erasure = table_counts()

    removed_by_owner = {k: before[k] - after_self_service[k] for k in before}
    removed_for_request = {k: after_self_service[k] - after_erasure[k] for k in before}
    assert removed_by_owner == removed_for_request
    assert sum(removed_by_owner.values()) > 10  # (the data was really there)


def test_the_erasure_is_one_transaction_with_its_log(
    support_client, make_dsr, subject, vet_user, monkeypatch
):
    """If the access log cannot be written, the account is not deleted either."""
    from accounts import data_subject_admin

    populate(subject, vet_user)
    dsr = make_dsr(subject)

    def broken(*args, **kwargs):
        raise RuntimeError("the log cannot be written")

    monkeypatch.setattr(data_subject_admin, "log_admin_access", broken)
    support_client.raise_request_exception = False

    response = erase(support_client, dsr)

    assert response.status_code == 500
    assert exists(subject) and Animal.objects.filter(owner=subject).exists()
    assert fresh(dsr).status == "RECEIVED" and fresh(dsr).user == subject


def test_the_erasure_is_one_transaction_with_the_completion_of_the_request(
    make_dsr, subject, support, monkeypatch
):
    dsr = make_dsr(subject)
    real = DataSubjectRequest.save

    def broken(self, *args, **kwargs):
        raise RuntimeError("the request cannot be saved")

    monkeypatch.setattr(DataSubjectRequest, "save", broken)

    with pytest.raises(RuntimeError):
        data_subject.erase_account(dsr, support, confirm_email=subject.email)

    monkeypatch.setattr(DataSubjectRequest, "save", real)
    assert exists(subject) and fresh(dsr).user == subject


def test_the_erasure_needs_the_csrf_token(make_user, make_dsr, subject):
    client = Client(enforce_csrf_checks=True)
    log_in_verified(client, make_user("podpora@example.cz", roles=(Role.SUPPORT_ADMIN,)))
    dsr = make_dsr(subject)
    data = {
        "action": ERASE,
        "_selected_action": [dsr.pk],
        "post": "yes",
        "confirm_email": subject.email,
    }

    response = client.post(list_url(), data)

    assert response.status_code == 403 and exists(subject)


def test_an_erasure_is_written_to_the_access_log(support_client, make_dsr, subject):
    dsr = make_dsr(subject)
    pk = subject.pk

    run(support_client, ERASE, [dsr])
    erase(support_client, dsr)

    rows = [(r.action, r.model, r.object_pk) for r in AdminAccessLog.objects.order_by("pk")]
    assert rows == [
        (Action.VIEW_OBJECT, "datasubjectrequest", str(dsr.pk)),
        (Action.DELETE, "user", str(pk)),
        (Action.CHANGE, "datasubjectrequest", str(dsr.pk)),
    ]
    entry = LogEntry.objects.get(action_flag=CHANGE, object_id=str(dsr.pk))
    assert entry.change_message == "Proveden výmaz účtu, žádost vyřízena."


def test_a_wrong_e_mail_is_a_view_in_the_log_not_a_deletion(support_client, make_dsr, subject):
    dsr = make_dsr(subject)

    erase(support_client, dsr, "jiny@example.cz")

    assert [r.action for r in AdminAccessLog.objects.all()] == [Action.VIEW_OBJECT]


def test_a_request_decided_meanwhile_is_not_erased_twice(make_dsr, subject, support):
    dsr = make_dsr(subject)
    stale = fresh(dsr)
    data_subject.erase_account(dsr, support, confirm_email=subject.email)

    with pytest.raises(DataSubjectRequestError, match="už je vyřízena"):
        data_subject.erase_account(stale, support, confirm_email=subject.email)


def test_the_service_refuses_a_wrong_e_mail_and_a_missing_permission(
    make_dsr, subject, support, make_user
):
    from django.core.exceptions import PermissionDenied

    dsr = make_dsr(subject)

    with pytest.raises(DataSubjectRequestError, match="není e-mailem tohoto účtu"):
        data_subject.erase_account(dsr, support, confirm_email="jiny@example.cz")
    with pytest.raises(PermissionDenied):
        data_subject.erase_account(
            dsr,
            make_user("sber@example.cz", roles=(Role.DATA_CURATOR,)),
            confirm_email=subject.email,
        )
    assert exists(subject)


def test_the_erasure_of_an_account_with_a_second_request_keeps_both_records(
    support_client, make_dsr, subject
):
    done = make_dsr(subject)
    other = make_dsr(subject, request_type="ACCESS")

    erase(support_client, done)

    assert fresh(done).status == "COMPLETED"
    assert fresh(other).user is None and fresh(other).status == "RECEIVED"


def test_the_confirmation_page_has_no_inline_script_or_style(support_client, make_dsr, subject):
    content = run(support_client, ERASE, [make_dsr(subject)]).content.decode()

    assert "style=" not in content and "<script>" not in content


def test_the_actions_are_named_in_czech(support_client, make_dsr):
    make_dsr()

    content = support_client.get(list_url()).content.decode()

    assert "Vytvořit export osobních údajů" in content and "Provést výmaz účtu" in content


def test_the_register_admin_uses_the_access_log_mixin():
    from django.contrib import admin

    model_admin = admin.site._registry[DataSubjectRequest]

    assert isinstance(model_admin, access_log.AccessLoggedAdminMixin)
    assert access_log.is_personal_data(DataSubjectRequest)
    assert access_log.is_personal_data(DataSubjectRequest.history.model)


# --- The export of the requests themselves --------------------------------------------------------


def test_the_user_export_lists_the_own_requests_without_the_notes_of_the_staff(
    make_dsr, subject, make_user
):
    make_dsr(
        subject,
        request_type="ACCESS",
        subject_label="tajné-označení",
        identity_note="tajná poznámka k totožnosti",
        outcome_note="tajná poznámka k vyřízení",
    )
    make_dsr(make_user("jiny@example.cz"), subject_label="cizí-žádost")

    section = build_export(subject)["data"]["data_subject_requests"]
    raw = json.dumps(section, ensure_ascii=False)

    assert [item["request_type"]["code"] for item in section] == ["ACCESS"]
    assert set(section[0]) == {"request_type", "received_on", "due_on", "status", "completed_on"}
    for secret in ("tajné-označení", "tajná poznámka", "cizí-žádost"):
        assert secret not in raw
