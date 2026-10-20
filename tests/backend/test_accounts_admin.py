"""Admin for the e-mail based user."""

import pytest
from django.urls import reverse

from accounts.models import User
from tests.backend.helpers import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    admin = User.objects.create_superuser("admin@example.cz", PASSWORD)
    client.force_login(admin)
    return client


@pytest.mark.parametrize(
    "url_name",
    [
        "admin:index",
        "admin:accounts_user_changelist",
        "admin:accounts_user_add",
        "admin:auth_group_changelist",
    ],
)
def test_admin_pages_load(admin_client, url_name):
    assert admin_client.get(reverse(url_name)).status_code == 200


def test_admin_user_change_page_loads(admin_client, user):
    response = admin_client.get(reverse("admin:accounts_user_change", args=[user.pk]))
    assert response.status_code == 200
    assert user.email in response.content.decode()


def test_admin_user_search(admin_client, user):
    response = admin_client.get(reverse("admin:accounts_user_changelist"), {"q": "jana"})
    assert response.status_code == 200
    assert user.email in response.content.decode()


def test_admin_creates_user_by_email(admin_client):
    response = admin_client.post(
        reverse("admin:accounts_user_add"),
        {
            "email": "Novy@Example.cz",
            "usable_password": "true",
            "password1": PASSWORD,
            "password2": PASSWORD,
        },
    )

    assert response.status_code == 302
    created = User.objects.get(email="novy@example.cz")
    assert created.check_password(PASSWORD)


def test_admin_rejects_duplicate_email_in_other_case(admin_client, user):
    response = admin_client.post(
        reverse("admin:accounts_user_add"),
        {
            "email": user.email.upper(),
            "usable_password": "true",
            "password1": PASSWORD,
            "password2": PASSWORD,
        },
    )

    assert response.status_code == 200
    assert User.objects.count() == 2  # admin + existing user


def test_admin_requires_staff(logged_in_client):
    response = logged_in_client.get(reverse("admin:index"))
    assert response.status_code == 302
    assert reverse("admin:login") in response["Location"]
