"""Settings of the administration: the hidden address, the second factor requirement and the
staff session limits (docs/14 §14.4 to §14.6)."""

import importlib
import runpy
import sys

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.urls import clear_url_caches, reverse

from config import env
from tests.backend.helpers import log_in_verified
from tests.backend.test_settings import load_prod

# --- ADMIN_URL: parsing -----------------------------------------------------------------------


def run_settings(monkeypatch, name):
    """Execute a settings module afresh (not the one Django already loaded) and return its names."""
    monkeypatch.delitem(sys.modules, f"config.settings.{name}", raising=False)
    return runpy.run_module(f"config.settings.{name}")


def parse(monkeypatch, value, *, production):
    if value is None:
        monkeypatch.delenv("DJANGO_ADMIN_URL", raising=False)
    else:
        monkeypatch.setenv("DJANGO_ADMIN_URL", value)
    return env.admin_url_from_env(production=production)


def test_development_defaults_to_admin(monkeypatch):
    assert parse(monkeypatch, None, production=False) == "admin/"
    assert parse(monkeypatch, "  ", production=False) == "admin/"


@pytest.mark.parametrize("value", ["sprava-q7x2k9m4/", "a/b/", "x_1.2~3/", "Sprava9/", "admin/"])
def test_development_accepts_well_formed_values(monkeypatch, value):
    assert parse(monkeypatch, value, production=False) == value


@pytest.mark.parametrize("value", ["sprava-q7x2k9m4/", "a1/b2/", "nic-nevi-9/"])
def test_production_accepts_a_hidden_path(monkeypatch, value):
    assert parse(monkeypatch, value, production=True) == value


@pytest.mark.parametrize(
    "value",
    [
        "sprava",  # no trailing slash
        "/sprava/",  # leading slash
        "sprava//",  # empty segment
        "sprava/ x/",
        "sprava?x=1/",
        "spr ava/",
        "správa/",
        "../x/",
        "https://evil.example/",
        "/",
        "ucet/",  # paths of the application itself
        "zvirata/tajne/",
        "STATIC/",
        "zdroje/",
        "prehled/",
    ],
)
def test_malformed_or_clashing_values_are_refused(monkeypatch, value):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_ADMIN_URL"):
        parse(monkeypatch, value, production=False)


@pytest.mark.parametrize("value", [None, "admin/", "Admin/", "ADMIN/"])
def test_production_refuses_a_missing_or_well_known_value(monkeypatch, value):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_ADMIN_URL"):
        parse(monkeypatch, value, production=True)


# --- ADMIN_URL: the settings modules and the URL configuration --------------------------------


def test_production_settings_use_the_variable(monkeypatch):
    assert load_prod(monkeypatch)["ADMIN_URL"] == "sprava-q7x2k9m4/"
    assert load_prod(monkeypatch, DJANGO_ADMIN_URL="jine-tajne-3/")["ADMIN_URL"] == "jine-tajne-3/"


@pytest.mark.parametrize("value", [None, "admin/", "sprava-bez-lomitka", "/sprava/"])
def test_production_refuses_to_start_with_a_bad_admin_url(monkeypatch, value):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_ADMIN_URL"):
        load_prod(monkeypatch, DJANGO_ADMIN_URL=value)


def test_the_test_settings_always_use_admin(monkeypatch):
    monkeypatch.setenv("DJANGO_ADMIN_URL", "something-else/")

    assert run_settings(monkeypatch, "test")["ADMIN_URL"] == "admin/"


def test_development_reads_the_variable(monkeypatch):
    monkeypatch.setenv("DJANGO_ADMIN_URL", "dev-sprava/")
    assert run_settings(monkeypatch, "dev")["ADMIN_URL"] == "dev-sprava/"
    monkeypatch.delenv("DJANGO_ADMIN_URL")
    assert run_settings(monkeypatch, "dev")["ADMIN_URL"] == "admin/"


@pytest.fixture
def hidden_admin(settings):
    """Mount the administration at a hidden path (the URL configuration reads the setting)."""
    from config import urls

    settings.ADMIN_URL = "sprava-q7x2k9m4/"
    importlib.reload(urls)
    clear_url_caches()
    yield settings.ADMIN_URL
    settings.ADMIN_URL = "admin/"
    importlib.reload(urls)
    clear_url_caches()


@pytest.mark.django_db
def test_the_urls_follow_the_setting(hidden_admin, client, superuser):
    assert reverse("admin:index") == "/sprava-q7x2k9m4/"
    assert reverse("admin:accounts_user_changelist") == "/sprava-q7x2k9m4/accounts/user/"
    log_in_verified(client, superuser)

    assert client.get("/sprava-q7x2k9m4/").status_code == 200
    assert client.get("/sprava-q7x2k9m4/accounts/user/").status_code == 200
    assert client.get("/admin/").status_code == 404
    assert client.get("/admin/accounts/user/").status_code == 404
    assert client.get("/admin/login/").status_code == 404


@pytest.mark.django_db
def test_the_admin_link_of_the_site_follows_the_setting(hidden_admin, client, superuser):
    log_in_verified(client, superuser)

    content = client.get(reverse("core:dashboard")).content.decode()

    assert 'href="/sprava-q7x2k9m4/"' in content and 'href="/admin/"' not in content


@pytest.mark.django_db
def test_an_anonymous_visitor_learns_nothing_at_the_old_address(hidden_admin, client):
    assert client.get("/admin/").status_code == 404
    assert client.get("/admin/login/").status_code == 404


def test_by_default_the_administration_is_at_admin():
    assert settings.ADMIN_URL == "admin/"
    assert reverse("admin:index") == "/admin/"


# --- The second factor requirement -------------------------------------------------------------


def test_the_requirement_defaults_to_true():
    from config.settings import base

    assert base.REQUIRE_2FA_FOR_STAFF is True and settings.REQUIRE_2FA_FOR_STAFF is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "False"])
def test_production_refuses_to_start_without_the_requirement(monkeypatch, value):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_REQUIRE_2FA_FOR_STAFF"):
        load_prod(monkeypatch, DJANGO_REQUIRE_2FA_FOR_STAFF=value)


@pytest.mark.parametrize("value", [None, "true", "1", "yes"])
def test_production_has_the_requirement(monkeypatch, value):
    assert (
        load_prod(monkeypatch, DJANGO_REQUIRE_2FA_FOR_STAFF=value)["REQUIRE_2FA_FOR_STAFF"] is True
    )


def test_production_refuses_a_value_that_is_not_a_boolean(monkeypatch):
    with pytest.raises(ImproperlyConfigured):
        load_prod(monkeypatch, DJANGO_REQUIRE_2FA_FOR_STAFF="maybe")


def test_development_may_switch_it_off_through_the_environment(monkeypatch):
    monkeypatch.delenv("DJANGO_REQUIRE_2FA_FOR_STAFF", raising=False)
    assert run_settings(monkeypatch, "dev")["REQUIRE_2FA_FOR_STAFF"] is True
    monkeypatch.setenv("DJANGO_REQUIRE_2FA_FOR_STAFF", "false")
    assert run_settings(monkeypatch, "dev")["REQUIRE_2FA_FOR_STAFF"] is False


def test_the_test_settings_ignore_the_environment(monkeypatch):
    monkeypatch.setenv("DJANGO_REQUIRE_2FA_FOR_STAFF", "false")
    assert run_settings(monkeypatch, "test")["REQUIRE_2FA_FOR_STAFF"] is True


# --- Staff session limits and the other documented values ----------------------------------------


def test_production_has_the_default_session_limits(monkeypatch):
    prod = load_prod(monkeypatch)

    assert prod["STAFF_SESSION_IDLE_SECONDS"] == 1800
    assert prod["STAFF_SESSION_MAX_SECONDS"] == 43200


def test_production_reads_the_session_limits(monkeypatch):
    prod = load_prod(
        monkeypatch,
        DJANGO_STAFF_SESSION_IDLE_SECONDS="600",
        DJANGO_STAFF_SESSION_MAX_SECONDS="7200",
    )

    assert (prod["STAFF_SESSION_IDLE_SECONDS"], prod["STAFF_SESSION_MAX_SECONDS"]) == (600, 7200)


@pytest.mark.parametrize(
    "overrides",
    [
        {"DJANGO_STAFF_SESSION_IDLE_SECONDS": "0"},
        {"DJANGO_STAFF_SESSION_MAX_SECONDS": "0"},
        {"DJANGO_STAFF_SESSION_IDLE_SECONDS": "-5"},
        {"DJANGO_STAFF_SESSION_MAX_SECONDS": "soon"},
    ],
)
def test_production_refuses_nonsense_session_limits(monkeypatch, overrides):
    with pytest.raises(ImproperlyConfigured):
        load_prod(monkeypatch, **overrides)


def test_the_idle_limit_is_shorter_than_the_absolute_limit():
    assert 0 < settings.STAFF_SESSION_IDLE_SECONDS < settings.STAFF_SESSION_MAX_SECONDS


def test_otp_settings_are_the_documented_ones():
    assert settings.OTP_TOTP_ISSUER == "BARF Nutri"
    assert settings.OTP_TOTP_THROTTLE_FACTOR == settings.OTP_STATIC_THROTTLE_FACTOR == 2


def test_the_middleware_order_gives_the_gate_what_it_needs():
    middleware = settings.MIDDLEWARE

    def index(name):
        return middleware.index(name)

    assert (
        index("django.contrib.auth.middleware.AuthenticationMiddleware")
        < index("django_otp.middleware.OTPMiddleware")
        < index("accounts.middleware.StaffSessionPolicyMiddleware")
        < index("accounts.middleware.TwoFactorEnforcementMiddleware")
    )
    assert index("django.contrib.messages.middleware.MessageMiddleware") < index(
        "accounts.middleware.StaffSessionPolicyMiddleware"
    )
    assert index("django.contrib.sessions.middleware.SessionMiddleware") < index(
        "django.contrib.auth.middleware.AuthenticationMiddleware"
    )
    assert middleware[-1] == "axes.middleware.AxesMiddleware"


def test_the_admin_app_is_the_barf_configuration():
    assert "backoffice.admin_apps.BarfAdminConfig" in settings.INSTALLED_APPS
    assert "django.contrib.admin" not in settings.INSTALLED_APPS
