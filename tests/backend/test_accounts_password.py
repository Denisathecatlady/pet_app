"""Password change and password reset."""

import pytest
from axes.models import AccessAttempt
from django.conf import settings
from django.test import Client
from django.urls import reverse

from accounts.models import User
from tests.backend.helpers import OTHER_PASSWORD, PASSWORD, extract_link

pytestmark = pytest.mark.django_db

CHANGE_URL = reverse("accounts:password_change")
RESET_URL = reverse("accounts:password_reset")
NEW_PASSWORD = "Nove-Heslo-Pro-Zkousku-77"


def change(client, old=PASSWORD, new=NEW_PASSWORD, new2=None):
    return client.post(
        CHANGE_URL,
        {"old_password": old, "new_password1": new, "new_password2": new2 or new},
    )


# --- Password change ---------------------------------------------------------------------


def test_password_change_requires_login(client):
    response = client.get(CHANGE_URL)
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("accounts:login"))


def test_password_change_page(logged_in_client):
    response = logged_in_client.get(CHANGE_URL)
    assert response.status_code == 200
    assert "Změna hesla" in response.content.decode()


def test_password_change_success_keeps_session(logged_in_client, user):
    response = change(logged_in_client)

    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:profile")
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    follow = logged_in_client.get(reverse("accounts:profile"))
    assert follow.status_code == 200
    assert "Heslo bylo změněno." in follow.content.decode()


def test_password_change_rejects_wrong_old_password(logged_in_client, user):
    response = change(logged_in_client, old=OTHER_PASSWORD)

    assert response.status_code == 200
    assert response.context["form"].errors["old_password"]
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_password_change_rejects_weak_password(logged_in_client, user):
    response = change(logged_in_client, new="kratke")

    assert response.status_code == 200
    assert response.context["form"].errors["new_password2"]


def test_password_change_old_password_guesses_are_rate_limited(logged_in_client, user):
    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        assert change(logged_in_client, old=OTHER_PASSWORD).status_code == 200

    assert change(logged_in_client, old=OTHER_PASSWORD).status_code == 429
    assert change(logged_in_client).status_code == 429
    user.refresh_from_db()
    assert user.check_password(PASSWORD)


def test_failed_attempt_records_contain_no_passwords(logged_in_client, user):
    change(logged_in_client, old=OTHER_PASSWORD)
    Client().post(reverse("accounts:login"), {"email": user.email, "password": OTHER_PASSWORD})

    stored = "\n".join(AccessAttempt.objects.values_list("post_data", flat=True))
    assert "old_password=" in stored and "email=" in stored
    for secret in (OTHER_PASSWORD, NEW_PASSWORD):
        assert secret not in stored


# --- Password reset ----------------------------------------------------------------------


def test_password_reset_page(client):
    response = client.get(RESET_URL)
    assert response.status_code == 200
    assert "Obnova hesla" in response.content.decode()


def test_password_reset_flow(client, user, mailoutbox):
    response = client.post(RESET_URL, {"email": "JANA@example.cz"})

    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:password_reset_done")
    assert len(mailoutbox) == 1
    assert mailoutbox[0].to == [user.email]
    assert "Obnova hesla" in mailoutbox[0].subject
    link = extract_link(mailoutbox[0].body)

    confirm = client.get(link, follow=True)
    assert confirm.status_code == 200
    assert confirm.context["validlink"]
    set_password_url = confirm.redirect_chain[-1][0]
    response = client.post(
        set_password_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}
    )
    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:password_reset_complete")
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)

    reused = client.get(link, follow=True)
    assert not reused.context["validlink"]
    assert "Odkaz je neplatný" in reused.content.decode()


def test_password_reset_complete_page(client):
    response = client.get(reverse("accounts:password_reset_complete"))
    assert response.status_code == 200
    assert "Heslo je nastaveno" in response.content.decode()


@pytest.mark.parametrize("case", ["unknown", "inactive"])
def test_password_reset_does_not_enumerate(client, user, make_user, mailoutbox, case):
    make_user("inactive@example.cz", is_active=False)
    reference = client.post(RESET_URL, {"email": user.email})
    mailoutbox.clear()

    response = client.post(RESET_URL, {"email": f"{case}@example.cz"})

    assert response.status_code == reference.status_code == 302
    assert response["Location"] == reference["Location"]
    assert mailoutbox == []


def test_password_reset_done_page_is_neutral(client):
    response = client.get(reverse("accounts:password_reset_done"))
    assert response.status_code == 200
    assert "Pokud k zadané adrese existuje aktivní účet" in response.content.decode()


def test_password_reset_email_is_throttled(client, user, mailoutbox):
    client.post(RESET_URL, {"email": user.email})
    client.post(RESET_URL, {"email": user.email})
    assert len(mailoutbox) == 1


def test_password_reset_does_not_activate_pending_account(client, make_user, mailoutbox):
    make_user("pending@example.cz", is_active=False, activation_pending=True)
    client.post(RESET_URL, {"email": "pending@example.cz"})
    assert mailoutbox == []
    assert not User.objects.get(email="pending@example.cz").is_active
