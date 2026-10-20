"""Account e-mails (timing, limits), unactivated registrations, records outside foreign
keys (login records, admin log) and the export of failed logins."""

import json
import threading
from datetime import timedelta

import pytest
from axes.models import AccessAttempt, AccessLog
from django.contrib.admin.models import CHANGE, LogEntry
from django.core.mail import EmailMessage
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from accounts import services
from accounts.models import User
from core.privacy import DELETED_OBJECT_REPR
from tests.backend.helpers import OTHER_PASSWORD, PASSWORD

pytestmark = pytest.mark.django_db

RESET_URL = reverse("accounts:password_reset")
EXPORT_URL = reverse("accounts:export")


# --- Background delivery: no enumeration by response time --------------------------------


@pytest.fixture
def slow_smtp(monkeypatch):
    """SMTP that blocks until ``release`` is set; records the subjects it sent."""
    release = threading.Event()
    sent: list[str] = []

    def send(self, fail_silently=False):
        assert release.wait(10), "the request waited for SMTP"
        sent.append(self.subject)
        return 1

    monkeypatch.setattr(EmailMessage, "send", send)
    return release, sent


def join_email_threads():
    for thread in threading.enumerate():
        if thread.name == "account-email":
            thread.join(10)


@override_settings(ACCOUNT_EMAIL_IN_BACKGROUND=True)
def test_password_reset_answers_before_smtp_finishes(client, user, slow_smtp):
    release, sent = slow_smtp

    response = client.post(RESET_URL, {"email": user.email})

    assert response.status_code == 302  # returned while SMTP is still blocked
    assert sent == []
    release.set()
    join_email_threads()
    assert sent == ["[BARF Nutri] Obnova hesla"]


@override_settings(ACCOUNT_EMAIL_IN_BACKGROUND=True)
def test_resend_activation_answers_before_smtp_finishes(client, make_user, slow_smtp):
    release, sent = slow_smtp
    make_user("pending@example.cz", is_active=False, activation_pending=True)

    response = client.post(reverse("accounts:resend_activation"), {"email": "pending@example.cz"})

    assert response.status_code == 302
    assert sent == []
    release.set()
    join_email_threads()
    assert len(sent) == 1 and "Aktivace účtu" in sent[0]


def test_inline_delivery_is_the_default_outside_production(settings):
    assert settings.ACCOUNT_EMAIL_IN_BACKGROUND is False


def test_delivery_errors_are_logged_not_raised(monkeypatch, caplog):
    def broken(self, fail_silently=False):
        raise ConnectionError("SMTP down")

    monkeypatch.setattr(EmailMessage, "send", broken)
    services.deliver(EmailMessage("Předmět", "Text", None, ["a@example.cz"]))
    assert "Sending account e-mail" in caplog.text


# --- E-mail limits --------------------------------------------------------------------------


def test_daily_limit_of_account_emails(user, settings):
    limit = settings.ACCOUNT_EMAIL_DAILY_LIMIT
    allowed = [services.claim_email_slot(f"kind-{index}", user) for index in range(limit + 2)]
    assert allowed == [True] * limit + [False, False]


def test_daily_limit_counts_each_user_separately(user, make_user, settings):
    for index in range(settings.ACCOUNT_EMAIL_DAILY_LIMIT):
        services.claim_email_slot(f"kind-{index}", user)
    assert services.claim_email_slot("kind-0", make_user("other@example.cz"))


# --- Unactivated registrations --------------------------------------------------------------


def test_purge_deletes_only_old_unactivated_registrations(make_user, settings, capsys):
    old = timezone.now() - settings.PENDING_ACCOUNT_RETENTION - timedelta(hours=1)
    make_user("stale@example.cz", is_active=False, activation_pending=True, date_joined=old)
    make_user("fresh@example.cz", is_active=False, activation_pending=True)
    make_user("deactivated@example.cz", is_active=False, date_joined=old)  # by an admin
    make_user("active@example.cz", date_joined=old)
    AccessAttempt.objects.create(
        username="stale@example.cz", ip_address="10.0.0.1", user_agent="x", failures_since_start=1
    )

    call_command("purge_pending_accounts")

    assert "Smazáno neaktivovaných registrací: 1" in capsys.readouterr().out
    assert sorted(User.objects.values_list("email", flat=True)) == [
        "active@example.cz",
        "deactivated@example.cz",
        "fresh@example.cz",
    ]
    assert not AccessAttempt.objects.filter(username="stale@example.cz").exists()


# --- Records outside foreign keys: admin log and login records ------------------------------


@pytest.fixture
def admin_user(make_user):
    return make_user("admin@example.cz", is_staff=True, is_superuser=True, roles=())


def test_account_deletion_anonymises_the_admin_log(make_user, admin_user, make_animal):
    leaving = make_user("leaving.person@example.cz")
    animal = make_animal(leaving, name="Bobík")
    LogEntry.objects.log_actions(admin_user.pk, [leaving], CHANGE, change_message="[]")
    LogEntry.objects.log_actions(admin_user.pk, [animal], CHANGE, change_message="[]")

    services.delete_account(leaving)

    reprs = list(LogEntry.objects.values_list("object_repr", flat=True))
    assert reprs == [DELETED_OBJECT_REPR, DELETED_OBJECT_REPR]  # the audit trail stays
    assert LogEntry.objects.filter(user=admin_user).count() == 2


def test_admin_deletion_runs_the_same_cleanup(client, make_user, admin_user):
    """Deleting a user in the admin bypasses services.delete_account; signals still clean up."""
    leaving = make_user("leaving.person@example.cz")
    login = reverse("accounts:login")
    client.post(login, {"email": leaving.email, "password": OTHER_PASSWORD}, REMOTE_ADDR="10.0.0.7")
    client.post(login, {"email": leaving.email, "password": PASSWORD})
    assert AccessLog.objects.filter(username=leaving.email).exists()
    assert AccessAttempt.objects.filter(username=leaving.email).exists()

    client.force_login(admin_user)
    url = reverse("admin:accounts_user_delete", args=[leaving.pk])
    assert client.post(url, {"post": "yes"}).status_code == 302

    assert not User.objects.filter(pk=leaving.pk).exists()
    assert not AccessLog.objects.filter(username=leaving.email).exists()
    assert not AccessAttempt.objects.filter(username=leaving.email).exists()
    assert not LogEntry.objects.filter(object_repr__contains="leaving.person").exists()
    # The admin's record of the deletion stays, without the e-mail.
    assert LogEntry.objects.filter(object_repr=DELETED_OBJECT_REPR).exists()


# --- Export of failed logins ----------------------------------------------------------------


def test_export_contains_failed_logins_without_request_data(client, user):
    client.post(
        reverse("accounts:login"),
        {"email": user.email, "password": OTHER_PASSWORD},
        REMOTE_ADDR="10.1.2.3",
        HTTP_USER_AGENT="Testovací prohlížeč",
    )
    client.force_login(user)

    raw = client.get(EXPORT_URL).content.decode()

    account = json.loads(raw)["data"]["account"]
    failed = [entry for entry in account["failed_logins"] if entry["ip_address"] == "10.1.2.3"]
    assert len(failed) == 1
    assert failed[0]["failures"] == 1
    assert failed[0]["user_agent"] == "Testovací prohlížeč"
    assert account["failed_login_log"] == []  # AXES_ENABLE_ACCESS_FAILURE_LOG is off
    assert "post_data" not in raw and "get_data" not in raw
    assert OTHER_PASSWORD not in raw


@override_settings(AXES_ENABLE_ACCESS_FAILURE_LOG=True)
def test_export_contains_the_failure_log_when_enabled(user):
    from axes.models import AccessFailureLog

    from accounts.export import export_account

    AccessFailureLog.objects.create(
        username=user.email, ip_address="10.0.0.9", user_agent="UA", locked_out=False
    )
    log = export_account(user)["failed_login_log"]
    assert [(e["ip_address"], e["user_agent"], e["locked_out"]) for e in log] == [
        ("10.0.0.9", "UA", False)
    ]
