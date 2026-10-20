"""Registration, activation and resending the activation link (no account enumeration)."""

from datetime import datetime, timedelta

import pytest
from django.core.cache import cache
from django.urls import reverse

from accounts.models import User
from accounts.tokens import ActivationTokenGenerator
from tests.backend.helpers import OTHER_PASSWORD, PASSWORD, extract_link

pytestmark = pytest.mark.django_db

REGISTER_URL = reverse("accounts:register")
RESEND_URL = reverse("accounts:resend_activation")
LOGIN_URL = reverse("accounts:login")


def register(client, email="nova@example.cz", password=PASSWORD, password2=None, consent=True):
    data = {"email": email, "password1": password, "password2": password2 or password}
    if consent:
        data["consent"] = "on"
    return client.post(REGISTER_URL, data)


def login(client, email, password=PASSWORD):
    return client.post(LOGIN_URL, {"email": email, "password": password})


def activate(client, link, password=PASSWORD):
    return client.post(link, {"password": password})


def test_registration_page_has_consent_with_links(client):
    response = client.get(REGISTER_URL)

    assert response.status_code == 200
    content = response.content.decode()
    assert "Registrace" in content
    assert 'name="consent"' in content
    assert reverse("core:terms") in content
    assert reverse("core:privacy") in content


def test_registration_requires_consent(client, mailoutbox):
    response = register(client, consent=False)

    assert response.status_code == 200
    assert "Bez souhlasu s podmínkami nelze účet založit." in response.content.decode()
    assert not User.objects.exists()
    assert mailoutbox == []


def test_registration_rejects_mismatched_passwords(client):
    response = register(client, password2=OTHER_PASSWORD)

    assert response.status_code == 200
    assert "Hesla se neshodují." in response.content.decode()
    assert not User.objects.exists()


@pytest.mark.parametrize("password", ["Kratke-1", "123456789012345", "nova@example.cz"])
def test_registration_enforces_password_validators(client, password):
    response = register(client, password=password)

    assert response.status_code == 200
    assert response.context["form"].errors["password1"]
    assert not User.objects.exists()


def test_registration_creates_inactive_owner_and_sends_activation(client, mailoutbox):
    response = register(client, email="Nova@Example.cz")

    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:register_done")
    user = User.objects.get()
    assert user.email == "nova@example.cz"
    assert not user.is_active
    assert user.activation_pending
    assert user.is_owner
    assert user.check_password(PASSWORD)
    assert len(mailoutbox) == 1
    message = mailoutbox[0]
    assert message.to == ["nova@example.cz"]
    assert "Aktivace účtu" in message.subject
    assert "/ucet/aktivace/" in message.body


def test_register_done_page(client):
    response = client.get(reverse("accounts:register_done"))
    assert response.status_code == 200
    assert "Zkontrolujte svůj e-mail" in response.content.decode()


def test_inactive_user_cannot_log_in(client):
    register(client)

    response = login(client, "nova@example.cz")

    assert response.status_code == 200
    assert "nejprve aktivujte účet" in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_activation_flow(client, mailoutbox):
    register(client)
    link = extract_link(mailoutbox[0].body)

    confirm = client.get(link)
    assert confirm.status_code == 200
    assert "Aktivovat účet" in confirm.content.decode()
    assert 'name="password"' in confirm.content.decode()
    assert "no-store" in confirm["Cache-Control"]
    assert not User.objects.get().is_active, "GET must not activate (link prefetchers)"

    response = activate(client, link)
    assert response.status_code == 302
    assert response["Location"] == LOGIN_URL
    user = User.objects.get()
    assert user.is_active and not user.activation_pending

    assert login(client, "nova@example.cz").status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)


def test_activation_link_is_one_time(client, mailoutbox):
    register(client)
    link = extract_link(mailoutbox[0].body)
    activate(client, link)

    assert client.get(link).status_code == 400
    assert activate(client, link).status_code == 400


@pytest.mark.parametrize("password", [None, OTHER_PASSWORD])
def test_activation_requires_the_registration_password(client, mailoutbox, password):
    register(client)
    link = extract_link(mailoutbox[0].body)

    response = client.post(link, {} if password is None else {"password": password})

    assert response.status_code == 200
    if password:
        assert "Heslo nesouhlasí s heslem z poslední registrace" in response.content.decode()
    assert not User.objects.get().is_active


# --- Account pre-hijacking: someone registers another person's e-mail first ----------------


def test_attacker_who_registers_first_cannot_set_the_password(client, mailoutbox):
    register(client, email="victim@example.cz", password=OTHER_PASSWORD)  # attacker
    cache.clear()  # the e-mail limit window has passed
    mailoutbox.clear()

    register(client, email="victim@example.cz", password=PASSWORD)  # the real owner
    response = activate(client, extract_link(mailoutbox[0].body), PASSWORD)

    assert response.status_code == 302
    user = User.objects.get()
    assert user.is_active
    assert user.check_password(PASSWORD) and not user.check_password(OTHER_PASSWORD)
    assert login(client, "victim@example.cz", OTHER_PASSWORD).status_code == 200
    assert "_auth_user_id" not in client.session


def test_attacker_who_registers_last_cannot_get_an_active_account(client, mailoutbox):
    register(client, email="victim@example.cz", password=PASSWORD)  # the real owner
    link = extract_link(mailoutbox[0].body)
    cache.clear()
    register(client, email="victim@example.cz", password=OTHER_PASSWORD)  # attacker
    assert len(mailoutbox) == 2  # both links go to the owner's mailbox

    # The owner knows only their own password: neither link activates the account.
    for message in mailoutbox:
        assert activate(client, extract_link(message.body), PASSWORD).status_code == 200
    assert not User.objects.get().is_active

    # Registering again restores the owner's password and the account can be activated.
    cache.clear()
    register(client, email="victim@example.cz", password=PASSWORD)
    assert activate(client, link, PASSWORD).status_code == 302
    user = User.objects.get()
    assert user.is_active and user.check_password(PASSWORD)


@pytest.mark.parametrize(
    "path",
    [
        "/ucet/aktivace/MQ/neplatny-token/",
        "/ucet/aktivace/!!!/abc-def/",
        "/ucet/aktivace/OTk5OTk5/abc-def/",
    ],
)
def test_invalid_activation_links(client, path):
    response = client.get(path)
    assert response.status_code == 400
    assert "Aktivační odkaz je neplatný" in response.content.decode()


def test_tampered_activation_token_is_rejected(client, mailoutbox):
    register(client)
    link = extract_link(mailoutbox[0].body)
    tampered = link[:-2] + ("a/" if link[-2] != "a" else "b/")

    assert activate(client, tampered).status_code == 400
    assert not User.objects.get().is_active


def test_expired_activation_link_is_rejected(client, mailoutbox, monkeypatch):
    register(client)
    link = extract_link(mailoutbox[0].body)
    later = datetime.now() + timedelta(days=2)
    monkeypatch.setattr(ActivationTokenGenerator, "_now", lambda self: later)

    assert activate(client, link).status_code == 400
    assert not User.objects.get().is_active


def test_admin_deactivated_user_cannot_reactivate_with_old_link(client, mailoutbox):
    register(client)
    link = extract_link(mailoutbox[0].body)
    user = User.objects.get()
    user.is_active = True
    user.save()  # admin activates ...
    user.is_active = False
    user.save()  # ... and later deactivates

    assert activate(client, link).status_code == 400
    user.refresh_from_db()
    assert not user.is_active


def test_registering_existing_email_sends_notice_and_keeps_password(client, user, mailoutbox):
    response = register(client, email=user.email.upper(), password=OTHER_PASSWORD)

    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:register_done")
    assert User.objects.count() == 1
    user.refresh_from_db()
    assert user.check_password(PASSWORD)
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [user.email]
    assert "Pokus o registraci" in mailoutbox[0].subject


def test_registering_pending_email_resends_activation(client, mailoutbox):
    register(client)
    register(client, password=OTHER_PASSWORD)  # within the throttle window: no second e-mail
    assert len(mailoutbox) == 1
    assert User.objects.count() == 1
    # The latest registration's password applies (activation asks for it).
    assert User.objects.get().check_password(OTHER_PASSWORD)

    cache.clear()
    register(client)
    assert len(mailoutbox) == 2
    assert User.objects.get().check_password(PASSWORD)


def test_registration_redirects_signed_in_user(logged_in_client):
    response = logged_in_client.get(REGISTER_URL)
    assert response.status_code == 302
    assert response["Location"] == reverse("core:dashboard")


# --- Resend activation -------------------------------------------------------------------


def test_resend_activation_page(client):
    response = client.get(RESEND_URL)
    assert response.status_code == 200
    assert "Nový aktivační odkaz" in response.content.decode()


def test_resend_activation_for_pending_account(client, make_user, mailoutbox):
    make_user("pending@example.cz", is_active=False, activation_pending=True)

    response = client.post(RESEND_URL, {"email": "Pending@Example.cz"})

    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:resend_activation_done")
    assert len(mailoutbox) == 1
    link = extract_link(mailoutbox[0].body)
    activate(client, link)
    assert User.objects.get(email="pending@example.cz").is_active


@pytest.mark.parametrize("case", ["unknown", "active", "deactivated"])
def test_resend_activation_does_not_enumerate(client, make_user, mailoutbox, case):
    make_user("active@example.cz")
    make_user("deactivated@example.cz", is_active=False)
    pending = make_user("pending@example.cz", is_active=False, activation_pending=True)
    reference = client.post(RESEND_URL, {"email": pending.email})
    mailoutbox.clear()

    response = client.post(RESEND_URL, {"email": f"{case}@example.cz"})

    assert response.status_code == reference.status_code == 302
    assert response["Location"] == reference["Location"]
    assert mailoutbox == []


def test_resend_activation_done_page_is_neutral(client):
    response = client.get(reverse("accounts:resend_activation_done"))
    assert response.status_code == 200
    assert "Pokud k zadané adrese existuje účet" in response.content.decode()


def test_resend_activation_is_throttled(client, make_user, mailoutbox):
    make_user("pending@example.cz", is_active=False, activation_pending=True)

    client.post(RESEND_URL, {"email": "pending@example.cz"})
    client.post(RESEND_URL, {"email": "pending@example.cz"})

    assert len(mailoutbox) == 1


def test_email_delivery_failure_does_not_change_response(client, mailoutbox, monkeypatch):
    def broken_send(self, *args, **kwargs):
        raise ConnectionError("SMTP down")

    monkeypatch.setattr("django.core.mail.EmailMessage.send", broken_send)

    response = register(client)

    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:register_done")


def test_all_password_errors_show_after_one_submission(client):
    response = register(client, password="a", password2="b")

    form = response.context["form"]
    assert form.errors["password2"] == ["Hesla se neshodují."]
    assert any("příliš krátké" in error for error in form.errors["password1"])


def test_short_password_error_is_czech(client):
    response = register(client, password="Kratke-1")
    assert "Heslo je příliš krátké. Musí mít alespoň 12 znaků." in response.content.decode()


@pytest.mark.parametrize(("length", "unit"), [(1, "znak"), (3, "znaky"), (12, "znaků")])
def test_minimum_length_message_plural(length, unit):
    from accounts.validators import MinimumLengthValidator

    message = MinimumLengthValidator(min_length=length).get_error_message()
    assert message.endswith(f"alespoň {length} {unit}.")


def test_consent_label_has_no_stray_suffix(client):
    content = client.get(REGISTER_URL).content.decode()
    assert "osobních údajů</a>.</label>" in content
