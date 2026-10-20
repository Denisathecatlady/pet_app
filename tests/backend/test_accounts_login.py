"""Login (django-axes lockout), logout and the axes hooks."""

import pytest
from django.conf import settings
from django.test import RequestFactory, override_settings
from django.urls import reverse

from accounts.axes_hooks import get_client_ip, get_username
from tests.backend.helpers import OTHER_PASSWORD, PASSWORD

pytestmark = pytest.mark.django_db

LOGIN_URL = reverse("accounts:login")
LOGOUT_URL = reverse("accounts:logout")


def login(client, email="jana@example.cz", password=PASSWORD, **extra):
    return client.post(LOGIN_URL, {"email": email, "password": password}, **extra)


def test_login_page_renders(client):
    response = client.get(LOGIN_URL)
    assert response.status_code == 200
    content = response.content.decode()
    assert "Přihlášení" in content
    assert 'name="email"' in content and 'autocomplete="current-password"' in content


def test_login_success_redirects_to_dashboard(client, user):
    response = login(client)

    assert response.status_code == 302
    assert response["Location"] == reverse("core:dashboard")
    assert client.session["_auth_user_id"] == str(user.pk)


def test_login_ignores_email_case(client, user):
    assert login(client, email="  JANA@Example.cz ").status_code == 302


@pytest.mark.parametrize(
    ("email", "password"),
    [("jana@example.cz", OTHER_PASSWORD), ("nikdo@example.cz", PASSWORD)],
)
def test_login_failure_has_one_generic_message(client, user, email, password):
    response = login(client, email=email, password=password)

    assert response.status_code == 200
    assert "Zadejte správný e-mail a heslo." in response.content.decode()
    assert "_auth_user_id" not in client.session


def test_login_follows_safe_next_only(client, user):
    profile = reverse("accounts:profile")
    response = client.post(
        f"{LOGIN_URL}?next={profile}", {"email": user.email, "password": PASSWORD}
    )
    assert response["Location"] == profile

    client.post(LOGOUT_URL)
    response = client.post(
        f"{LOGIN_URL}?next=https://evil.example/", {"email": user.email, "password": PASSWORD}
    )
    assert response["Location"] == reverse("core:dashboard")


def test_signed_in_user_is_redirected_from_login(logged_in_client):
    response = logged_in_client.get(LOGIN_URL)
    assert response.status_code == 302


def test_lockout_after_failure_limit(client, user):
    limit = settings.AXES_FAILURE_LIMIT
    assert limit == 5
    for _ in range(limit - 1):
        assert login(client, password=OTHER_PASSWORD).status_code == 200

    locked = login(client, password=OTHER_PASSWORD)
    assert locked.status_code == 429
    content = locked.content.decode()
    assert "Přihlášení je dočasně zablokováno" in content
    assert "60 minut" in content

    # The correct password does not help while locked out.
    assert login(client).status_code == 429
    assert "_auth_user_id" not in client.session


def test_lockout_cannot_be_bypassed_by_changing_email_case(client, user):
    for index in range(settings.AXES_FAILURE_LIMIT):
        email = "JANA@example.cz" if index % 2 else "jana@EXAMPLE.cz"
        login(client, email=email, password=OTHER_PASSWORD)

    assert login(client).status_code == 429


def test_lockout_is_per_username_and_ip(client, user, make_user):
    for _ in range(settings.AXES_FAILURE_LIMIT):
        login(client, password=OTHER_PASSWORD)

    # Same user from another address, and another user from the same address, may log in.
    assert login(client, REMOTE_ADDR="10.0.0.9").status_code == 302
    client.post(LOGOUT_URL)
    make_user("petr@example.cz")
    assert login(client, email="petr@example.cz").status_code == 302


def test_successful_login_resets_failures(client, user):
    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        login(client, password=OTHER_PASSWORD)
    assert login(client).status_code == 302
    client.post(LOGOUT_URL)

    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        assert login(client, password=OTHER_PASSWORD).status_code == 200


def test_logout_requires_post(logged_in_client):
    response = logged_in_client.get(LOGOUT_URL)
    assert response.status_code == 405
    assert "_auth_user_id" in logged_in_client.session


def test_logout_post_logs_out(logged_in_client):
    response = logged_in_client.post(LOGOUT_URL)

    assert response.status_code == 302
    assert response["Location"] == reverse("core:home")
    assert "_auth_user_id" not in logged_in_client.session


# --- django-axes hooks -------------------------------------------------------------------


def test_get_username_normalises_credentials_and_post():
    factory = RequestFactory()
    assert get_username(factory.get("/"), {"email": " Jana@Example.CZ"}) == "jana@example.cz"
    assert get_username(factory.get("/"), {"username": "Admin@X.cz"}) == "admin@x.cz"
    request = factory.post("/", {"email": "Petr@X.cz"})
    assert get_username(request, None) == "petr@x.cz"
    assert get_username(factory.post("/", {}), None) is None
    assert get_username(None, None) is None


def test_get_client_ip_without_proxy_ignores_forwarded_header():
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="1.2.3.4")
    assert get_client_ip(request) == "10.0.0.1"


@pytest.mark.parametrize(
    ("count", "forwarded", "expected"),
    [
        (1, "6.6.6.6, 203.0.113.7", "203.0.113.7"),
        (2, "6.6.6.6, 203.0.113.7, 10.0.0.2", "203.0.113.7"),
        (2, "203.0.113.7", "10.0.0.1"),
        (1, "", "10.0.0.1"),
    ],
)
def test_get_client_ip_behind_trusted_proxies(count, forwarded, expected):
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR=forwarded)
    with override_settings(TRUSTED_PROXY_COUNT=count):
        assert get_client_ip(request) == expected
