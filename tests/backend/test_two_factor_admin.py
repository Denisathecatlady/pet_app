"""Two-factor authentication around the administration: the admin site gate, GDPR export and
deletion, and recovery from the loss of a device (docs/14 §14.6)."""

import io
import json

import pytest
from django.contrib.admin.models import CHANGE, LogEntry
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.urls import reverse
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import services, two_factor
from accounts.export import build_export, registered_exporters
from accounts.models import User
from accounts.roles import Role
from backoffice.admin_site import BarfAdminSite
from backoffice.models import AdminAccessAction, AdminAccessLog
from tests.backend.helpers import enroll, log_in_verified, totp_token

pytestmark = pytest.mark.django_db

CHANGELIST = reverse("admin:accounts_user_changelist")


# --- The admin site -------------------------------------------------------------------------------


def test_the_default_site_is_the_barf_site():
    from django.contrib import admin

    assert isinstance(admin.site, BarfAdminSite)
    assert admin.site.site_header == "BARF Nutri – správa"
    assert admin.site.site_title == "BARF Nutri – správa"


def test_the_app_label_of_the_admin_did_not_change():
    from django.apps import apps

    assert apps.get_app_config("admin").name == "django.contrib.admin"
    assert reverse("admin:index") == "/admin/"


def test_the_index_shows_the_czech_header(client, superuser):
    log_in_verified(client, superuser)

    content = client.get(reverse("admin:index")).content.decode()

    assert "BARF Nutri – správa" in content and "Správa aplikace" in content


@pytest.mark.parametrize(
    ("kind", "device", "verified", "allowed"),
    [
        ("staff", False, False, False),
        ("staff", True, False, False),
        ("staff", True, True, True),
        ("superuser", False, False, False),
        ("superuser", True, False, False),
        ("superuser", True, True, True),
    ],
)
def test_the_admin_site_permission_needs_a_verified_session(
    rf, make_staff, superuser, kind, device, verified, allowed
):
    account = make_staff() if kind == "staff" else superuser
    if device:
        enroll(account)
    request = rf.get("/")
    request.user = account
    account.is_verified = lambda: verified

    assert BarfAdminSite().has_permission(request) is allowed


def test_the_admin_site_refuses_a_user_without_the_otp_middleware(rf, superuser):
    request = rf.get("/")
    request.user = superuser  # a plain user object has no is_verified()
    enroll(superuser)

    assert BarfAdminSite().has_permission(request) is False


@override_settings(REQUIRE_2FA_FOR_STAFF=False)
def test_without_the_requirement_staff_without_a_device_may_use_the_admin(rf, superuser):
    request = rf.get("/")
    request.user = superuser
    superuser.is_verified = lambda: False

    assert BarfAdminSite().has_permission(request) is True


def test_an_unverified_staff_session_is_sent_to_verification_not_to_the_admin(client, superuser):
    enroll(superuser)
    client.force_login(superuser)

    response = client.get(reverse("admin:index"))

    assert response.status_code == 302
    assert response["Location"].startswith(reverse("accounts:two_factor_verify"))


def test_there_is_no_separate_admin_login_page(client, user):
    response = client.get(reverse("admin:login") + "?next=/admin/accounts/user/")
    assert response.status_code == 302
    assert response["Location"] == "/ucet/prihlaseni/?next=/admin/accounts/user/"

    client.force_login(user)
    assert client.get(reverse("admin:login"))["Location"] == reverse("core:dashboard")


def test_the_admin_login_does_not_pass_on_an_unsafe_next(client):
    response = client.get(reverse("admin:login") + "?next=https://evil.example/")
    assert response["Location"] == "/ucet/prihlaseni/"


def test_the_admin_login_form_cannot_be_posted_to(client, user):
    from tests.backend.helpers import PASSWORD

    response = client.post(reverse("admin:login"), {"username": user.email, "password": PASSWORD})

    assert response.status_code == 302 and "_auth_user_id" not in client.session


def test_the_admin_password_change_is_the_account_page(client, superuser):
    log_in_verified(client, superuser)

    assert client.get(reverse("admin:password_change"))["Location"] == reverse(
        "accounts:password_change"
    )


def test_the_device_models_are_not_in_the_admin():
    from django.contrib import admin

    for model in (TOTPDevice, StaticDevice, StaticToken):
        assert not admin.site.is_registered(model)


def test_the_secrets_of_the_devices_are_not_reachable_in_the_admin(client, superuser, user):
    log_in_verified(client, superuser)
    device = enroll(user)

    for path in (
        "otp_totp/totpdevice/",
        f"otp_totp/totpdevice/{device.pk}/change/",
        "otp_static/staticdevice/",
        "otp_static/statictoken/",
    ):
        response = client.get(f"/admin/{path}")
        assert response.status_code in (302, 404), path
        assert device.key not in response.content.decode()


# --- GDPR export ----------------------------------------------------------------------------------


def test_the_registry_has_a_two_factor_section():
    assert "two_factor" in registered_exporters()


def test_export_of_a_user_without_two_factor(user):
    section = build_export(user)["data"]["two_factor"]

    assert section == {"enrolled": False, "confirmed_at": None, "unused_recovery_codes": 0}


def test_export_of_an_enrolled_user_has_the_state_and_no_secret(user):
    device = enroll(user)
    codes = two_factor.generate_recovery_codes(user)
    two_factor.begin_enrollment(user)  # a pending device is not "enrolled" and not exported

    export = build_export(user)
    section = export["data"]["two_factor"]

    assert section["enrolled"] is True and section["unused_recovery_codes"] == 10
    assert section["confirmed_at"] == device.created_at.astimezone().isoformat()
    assert set(section) == {"enrolled", "confirmed_at", "unused_recovery_codes"}
    raw = json.dumps(export)
    assert device.key not in raw
    assert not any(code.replace("-", "") in raw or code in raw for code in codes)
    from base64 import b32encode

    assert b32encode(device.bin_key).decode() not in raw


def test_the_download_contains_the_section(client, user):
    client.force_login(user)

    data = json.loads(client.get(reverse("accounts:export")).content)

    assert data["data"]["two_factor"]["enrolled"] is False


def test_the_count_of_unused_codes_follows_their_use(user):
    enroll(user)
    codes = two_factor.generate_recovery_codes(user)
    two_factor.verify(user, codes[0])

    assert build_export(user)["data"]["two_factor"]["unused_recovery_codes"] == 9


# --- Deleting the account -------------------------------------------------------------------------


def test_deleting_the_account_removes_every_device_and_code(user, make_user):
    other = make_user("other@example.cz")
    enroll(other)
    two_factor.generate_recovery_codes(other)
    enroll(user)
    two_factor.generate_recovery_codes(user)
    two_factor.begin_enrollment(user)

    services.delete_account(user)

    assert not TOTPDevice.objects.filter(user_id=user.pk).exists()
    assert not StaticDevice.objects.filter(user_id=user.pk).exists()
    assert StaticToken.objects.count() == 10  # only the other account's codes remain
    assert TOTPDevice.objects.filter(user=other).exists()


def test_a_superuser_deleting_the_account_in_the_admin_removes_them_too(client, superuser, user):
    enroll(user)
    two_factor.generate_recovery_codes(user)
    log_in_verified(client, superuser)

    response = client.post(reverse("admin:accounts_user_delete", args=[user.pk]), {"post": "yes"})

    assert response.status_code == 302
    assert not TOTPDevice.objects.filter(user_id=user.pk).exists()
    assert not StaticToken.objects.exists()


# --- Loss of the device: the admin action ---------------------------------------------------------


def reset(client, *users):
    return client.post(
        CHANGELIST,
        {"action": "reset_two_factor", "_selected_action": [u.pk for u in users]},
        follow=True,
    )


def test_a_superuser_resets_two_factor_and_it_is_logged(client, superuser, make_staff):
    colleague = make_staff(Role.DATA_CURATOR)
    enroll(colleague)
    two_factor.generate_recovery_codes(colleague)
    log_in_verified(client, superuser)

    response = reset(client, colleague)

    assert "Dvoufázové ověření bylo zrušeno: 1." in response.content.decode()
    assert two_factor.confirmed_device(colleague) is None
    assert not StaticDevice.objects.filter(user=colleague).exists()
    entry = LogEntry.objects.get(object_id=str(colleague.pk), action_flag=CHANGE)
    assert entry.user == superuser and "Zrušeno dvoufázové ověření" in entry.change_message
    assert AdminAccessLog.objects.filter(
        staff_user=superuser, action=AdminAccessAction.CHANGE, object_pk=str(colleague.pk)
    ).exists()


def test_the_reset_user_must_enrol_again_at_the_next_request(client, superuser, make_staff):
    colleague = make_staff(Role.DATA_CURATOR)
    log_in_verified(client, colleague)
    assert client.get(reverse("admin:index")).status_code == 200
    other = type(client)()
    log_in_verified(other, superuser)

    reset(other, colleague)

    response = client.get(reverse("admin:index"))  # the old verified session is worthless now
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("accounts:two_factor_setup"))


def test_the_reset_action_is_for_superusers_only(client, make_staff):
    support = make_staff()
    victim = User.objects.create_user("victim@example.cz", "x")
    enroll(victim)
    log_in_verified(client, support)

    listing = client.get(CHANGELIST).content.decode()
    client.post(
        CHANGELIST, {"action": "reset_two_factor", "_selected_action": [victim.pk]}, follow=True
    )

    assert 'value="reset_two_factor"' not in listing
    assert two_factor.confirmed_device(victim) is not None


def test_the_command_resets_an_account(make_staff):
    colleague = make_staff(Role.DATA_CURATOR, email="Colleague@Example.cz")
    enroll(colleague)
    two_factor.generate_recovery_codes(colleague)
    out = io.StringIO()

    call_command("reset_2fa", "COLLEAGUE@example.cz", stdout=out)

    assert "bylo zrušeno" in out.getvalue() and colleague.email in out.getvalue()
    assert two_factor.confirmed_device(colleague) is None
    assert not StaticDevice.objects.filter(user=colleague).exists()
    row = AdminAccessLog.objects.get(object_pk=str(colleague.pk))
    assert (row.staff_email, row.action, row.path) == (
        "manage.py reset_2fa",
        AdminAccessAction.CHANGE,
        "manage.py reset_2fa",
    )
    assert row.staff_user is None and row.ip_address is None


def test_the_command_logs_a_warning(make_staff, caplog):
    colleague = make_staff(Role.DATA_CURATOR)
    enroll(colleague)

    with caplog.at_level("WARNING", logger="accounts.management.commands.reset_2fa"):
        call_command("reset_2fa", colleague.email, stdout=io.StringIO())

    assert f"Two-factor reset for user {colleague.pk}" in caplog.text


def test_the_command_rejects_an_unknown_account():
    with pytest.raises(CommandError, match="neexistuje"):
        call_command("reset_2fa", "nobody@example.cz", stdout=io.StringIO())


def test_the_command_works_for_an_account_without_a_device(user):
    out = io.StringIO()

    call_command("reset_2fa", user.email, stdout=out)

    assert "smazaných zařízení: 0" in out.getvalue()


def test_a_reset_account_can_enrol_and_sign_in_again(client, make_staff):
    colleague = make_staff(Role.DATA_CURATOR)
    enroll(colleague)
    call_command("reset_2fa", colleague.email, stdout=io.StringIO())
    client.force_login(colleague)

    client.get(reverse("accounts:two_factor_setup"))
    pending = TOTPDevice.objects.get(user=colleague, confirmed=False)
    response = client.post(reverse("accounts:two_factor_setup"), {"token": totp_token(pending)})

    assert response.status_code == 200 and client.get(reverse("admin:index")).status_code == 200
