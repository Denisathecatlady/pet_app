"""Profile page, GDPR data export (registry) and account deletion."""

import json

import pytest
from axes.models import AccessAttempt, AccessLog
from django.conf import settings
from django.urls import reverse

from accounts import export as export_module
from accounts.export import build_export, register_exporter, registered_exporters
from accounts.models import User
from tests.backend.helpers import OTHER_PASSWORD, PASSWORD

pytestmark = pytest.mark.django_db

PROFILE_URL = reverse("accounts:profile")
EXPORT_URL = reverse("accounts:export")
DELETE_URL = reverse("accounts:delete")


@pytest.mark.parametrize("url", [PROFILE_URL, EXPORT_URL, DELETE_URL])
def test_account_pages_require_login(client, url):
    response = client.get(url)
    assert response.status_code == 302
    assert response["Location"] == f"{reverse('accounts:login')}?next={url}"


# --- Profile -----------------------------------------------------------------------------


def test_profile_shows_email_and_roles(logged_in_client, user):
    response = logged_in_client.get(PROFILE_URL)

    content = response.content.decode()
    assert response.status_code == 200
    assert user.email in content
    assert "Majitel zvířat" in content
    assert reverse("accounts:export") in content
    assert reverse("accounts:delete") in content


def test_profile_updates_names_but_not_email(logged_in_client, user):
    response = logged_in_client.post(
        PROFILE_URL,
        {"first_name": "Jana", "last_name": "Nováková", "email": "jina@example.cz"},
    )

    assert response.status_code == 302
    user.refresh_from_db()
    assert (user.first_name, user.last_name) == ("Jana", "Nováková")
    assert user.email == "jana@example.cz"
    assert "Profil byl uložen." in logged_in_client.get(PROFILE_URL).content.decode()


# --- Export ------------------------------------------------------------------------------


def test_export_downloads_json_without_password(logged_in_client, user):
    response = logged_in_client.get(EXPORT_URL)

    assert response.status_code == 200
    assert response["Content-Type"] == "application/json; charset=utf-8"
    assert response["Content-Disposition"].startswith('attachment; filename="barf-nutri-export-')
    assert "no-store" in response["Cache-Control"]
    raw = response.content.decode()
    assert user.password not in raw
    assert "password" not in raw
    data = json.loads(raw)
    assert data["format"] == "barf-nutri-personal-data"
    account = data["data"]["account"]
    assert account["email"] == "jana@example.cz"
    assert account["roles"] == [{"code": "owner", "label": "Majitel zvířat"}]


def test_export_contains_login_history(client, user):
    client.post(reverse("accounts:login"), {"email": user.email, "password": PASSWORD})

    data = json.loads(client.get(EXPORT_URL).content)

    history = data["data"]["account"]["login_history"]
    assert len(history) == 1
    assert history[0]["ip_address"] == "127.0.0.1"


def test_export_contains_only_own_data(client, make_user):
    make_user("other@example.cz", first_name="Cizí")
    me = make_user("me@example.cz")
    client.force_login(me)

    raw = client.get(EXPORT_URL).content.decode()

    assert "other@example.cz" not in raw and "Cizí" not in raw


def test_export_rejects_post(logged_in_client):
    assert logged_in_client.post(EXPORT_URL).status_code == 405


def test_accounts_exporter_is_registered():
    assert "account" in registered_exporters()
    assert "animals" in registered_exporters()
    assert "catalog" in registered_exporters()


def test_registry_includes_other_apps(monkeypatch, user):
    monkeypatch.setattr(export_module, "_exporters", dict(export_module._exporters))
    register_exporter("zz_sample", lambda u: [{"name": "Rex", "owner": u.email}])

    data = build_export(user)

    assert list(data["data"]) == ["account", "animals", "catalog", "zz_sample"]
    assert data["data"]["zz_sample"] == [{"name": "Rex", "owner": user.email}]


def test_registry_rejects_conflicting_names(monkeypatch):
    monkeypatch.setattr(export_module, "_exporters", dict(export_module._exporters))

    def exporter(user):
        return {}

    register_exporter("sample", exporter)
    register_exporter("sample", exporter)  # same callable: no-op
    with pytest.raises(ValueError):
        register_exporter("sample", lambda user: {})
    with pytest.raises(ValueError):
        register_exporter("", exporter)


# --- Deletion ----------------------------------------------------------------------------


def test_delete_page(logged_in_client):
    response = logged_in_client.get(DELETE_URL)
    assert response.status_code == 200
    assert "Smazání je nevratné." in response.content.decode()


def test_delete_with_wrong_password_keeps_account(logged_in_client, user):
    response = logged_in_client.post(DELETE_URL, {"password": OTHER_PASSWORD})

    assert response.status_code == 200
    assert "Heslo není správné." in response.content.decode()
    assert User.objects.filter(pk=user.pk).exists()
    assert "_auth_user_id" in logged_in_client.session


def test_delete_with_right_password_removes_account_and_logs_out(client, user):
    client.post(reverse("accounts:login"), {"email": user.email, "password": PASSWORD})
    client.post(DELETE_URL, {"password": OTHER_PASSWORD})
    assert AccessLog.objects.filter(username=user.email).exists()
    assert AccessAttempt.objects.filter(username=user.email).exists()

    response = client.post(DELETE_URL, {"password": PASSWORD})

    assert response.status_code == 302
    assert response["Location"] == reverse("accounts:deleted")
    assert not User.objects.filter(pk=user.pk).exists()
    assert "_auth_user_id" not in client.session
    assert not AccessLog.objects.filter(username=user.email).exists()
    assert not AccessAttempt.objects.filter(username=user.email).exists()
    assert client.get(PROFILE_URL).status_code == 302


def test_deleted_page(client):
    response = client.get(reverse("accounts:deleted"))
    assert response.status_code == 200
    assert "Účet byl smazán" in response.content.decode()


def test_delete_password_guesses_are_rate_limited(logged_in_client, user):
    for _ in range(settings.AXES_FAILURE_LIMIT - 1):
        logged_in_client.post(DELETE_URL, {"password": OTHER_PASSWORD})

    assert logged_in_client.post(DELETE_URL, {"password": OTHER_PASSWORD}).status_code == 429
    assert logged_in_client.post(DELETE_URL, {"password": PASSWORD}).status_code == 429
    assert User.objects.filter(pk=user.pk).exists()
