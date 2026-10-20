"""Settings: environment helpers, shared security settings and production settings."""

import os
import runpy
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from config import env
from config.settings import base

BACKEND_DIR = Path(base.BASE_DIR)

PROD_ENV = {
    "DJANGO_SECRET_KEY": "q9!Zr7@kLm2#Vx8$Tn4%Hb6^Wc1&Jd5*Pf3(Gs0)Ye-Ua_Io+Ek=Rl",
    "DJANGO_ALLOWED_HOSTS": "barf.example.cz, www.barf.example.cz",
    "POSTGRES_DB": "barf_prod",
    "POSTGRES_USER": "barf_app",
    "POSTGRES_PASSWORD": "not-a-real-password",
    "POSTGRES_HOST": "db.internal",
}
OPTIONAL_VARS = (
    "POSTGRES_PORT",
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
    "DJANGO_SECURE_HSTS_PRELOAD",
    "DJANGO_SECURE_PROXY_SSL_HEADER",
    "DJANGO_TRUSTED_PROXY_COUNT",
    "DJANGO_STATIC_ROOT",
    "DJANGO_EMAIL_HOST",
    "DJANGO_EMAIL_PORT",
    "DJANGO_EMAIL_HOST_USER",
    "DJANGO_EMAIL_HOST_PASSWORD",
    "DJANGO_EMAIL_USE_TLS",
    "DJANGO_EMAIL_USE_SSL",
    "DJANGO_DEFAULT_FROM_EMAIL",
    "DJANGO_LOG_LEVEL",
)


def load_prod(monkeypatch, **overrides):
    """Execute config/settings/prod.py with PROD_ENV + overrides (None removes a variable)."""
    for name in (*PROD_ENV, *OPTIONAL_VARS):
        monkeypatch.delenv(name, raising=False)
    for name, value in {**PROD_ENV, **overrides}.items():
        if value is not None:
            monkeypatch.setenv(name, value)
    return runpy.run_module("config.settings.prod")


# --- Environment helpers -----------------------------------------------------------------


def test_env_helpers(monkeypatch):
    monkeypatch.setenv("X_BOOL", "Yes")
    monkeypatch.setenv("X_INT", "42")
    monkeypatch.setenv("X_LIST", " a, ,b ,")
    monkeypatch.setenv("X_EMPTY", "  ")
    assert env.env_bool("X_BOOL", False) is True
    assert env.env_bool("X_MISSING", True) is True
    assert env.env_int("X_INT", 0) == 42
    assert env.env_list("X_LIST") == ["a", "b"]
    assert env.env_list("X_MISSING") == []
    assert env.env_str("X_EMPTY", "default") == "default"


@pytest.mark.parametrize(("helper", "value"), [(env.env_bool, "maybe"), (env.env_int, "-1")])
def test_env_helpers_reject_invalid_values(monkeypatch, helper, value):
    monkeypatch.setenv("X_BAD", value)
    with pytest.raises(ImproperlyConfigured):
        helper("X_BAD", 0)


def test_require_env(monkeypatch):
    monkeypatch.delenv("X_REQUIRED", raising=False)
    with pytest.raises(ImproperlyConfigured, match="X_REQUIRED"):
        env.require_env("X_REQUIRED")


def test_database_from_env_with_defaults(monkeypatch):
    for _, variable in env.DATABASE_VARIABLES:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("POSTGRES_HOST", "db")
    config = env.database_from_env(
        {
            "POSTGRES_DB": "d",
            "POSTGRES_USER": "u",
            "POSTGRES_PASSWORD": "p",
            "POSTGRES_HOST": "h",
            "POSTGRES_PORT": "1",
        }
    )
    assert config["ENGINE"] == "django.db.backends.postgresql"
    assert (config["NAME"], config["HOST"], config["PORT"]) == ("d", "db", "1")


# --- Shared (base) settings --------------------------------------------------------------


def test_base_uses_argon2_and_strong_password_rules():
    assert base.PASSWORD_HASHERS[0] == "django.contrib.auth.hashers.Argon2PasswordHasher"
    min_length = next(
        validator["OPTIONS"]["min_length"]
        for validator in base.AUTH_PASSWORD_VALIDATORS
        if validator["NAME"].endswith("MinimumLengthValidator")
    )
    assert min_length == 12


def test_fast_hasher_only_in_test_settings():
    assert settings.PASSWORD_HASHERS == ["django.contrib.auth.hashers.MD5PasswordHasher"]
    assert not any("MD5" in hasher for hasher in base.PASSWORD_HASHERS)


def test_base_axes_configuration():
    assert base.AUTHENTICATION_BACKENDS[0] == "axes.backends.AxesStandaloneBackend"
    assert base.MIDDLEWARE[-1] == "axes.middleware.AxesMiddleware"
    assert "simple_history.middleware.HistoryRequestMiddleware" in base.MIDDLEWARE
    assert base.MIDDLEWARE[0] == "django.middleware.security.SecurityMiddleware"
    assert base.AXES_FAILURE_LIMIT == base.LOGIN_FAILURE_LIMIT == 5
    assert base.AXES_COOLOFF_TIME == base.LOGIN_COOLOFF == timedelta(hours=1)
    assert base.AXES_LOCKOUT_PARAMETERS == [["username", "ip_address"]]
    assert base.AXES_USERNAME_FORM_FIELD == "email"


def test_base_session_and_browser_security():
    assert base.AUTH_USER_MODEL == "accounts.User"
    assert base.SESSION_COOKIE_HTTPONLY is True
    assert base.SESSION_COOKIE_SAMESITE == "Lax"
    assert base.X_FRAME_OPTIONS == "DENY"
    assert base.LANGUAGE_CODE == "cs"
    assert base.TIME_ZONE == "Europe/Prague"
    assert base.USE_TZ is True
    assert base.DEFAULT_AUTO_FIELD == "django.db.models.BigAutoField"
    assert not hasattr(base, "SECRET_KEY")


# --- Production settings -----------------------------------------------------------------


@pytest.mark.parametrize(
    "missing",
    [
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
    ],
)
def test_prod_refuses_to_load_without_required_env(monkeypatch, missing):
    with pytest.raises(ImproperlyConfigured, match=missing):
        load_prod(monkeypatch, **{missing: None})


@pytest.mark.parametrize(
    "secret",
    ["short-key", "django-insecure-" + "x" * 60, "a" * 60],
)
def test_prod_refuses_weak_secret_key(monkeypatch, secret):
    with pytest.raises(ImproperlyConfigured, match="DJANGO_SECRET_KEY"):
        load_prod(monkeypatch, DJANGO_SECRET_KEY=secret)


def test_prod_security_settings(monkeypatch):
    prod = load_prod(monkeypatch)

    assert prod["DEBUG"] is False
    assert prod["ALLOWED_HOSTS"] == ["barf.example.cz", "www.barf.example.cz"]
    assert prod["SECURE_SSL_REDIRECT"] is True
    assert prod["SESSION_COOKIE_SECURE"] is True
    assert prod["CSRF_COOKIE_SECURE"] is True
    assert prod["SESSION_COOKIE_HTTPONLY"] is True
    assert prod["SECURE_HSTS_SECONDS"] == 31_536_000
    assert prod["SECURE_HSTS_INCLUDE_SUBDOMAINS"] is True
    assert prod["SECURE_HSTS_PRELOAD"] is False
    assert prod["SECURE_CONTENT_TYPE_NOSNIFF"] is True
    assert prod["SECURE_REFERRER_POLICY"] == "same-origin"
    assert prod["X_FRAME_OPTIONS"] == "DENY"
    assert "SECURE_PROXY_SSL_HEADER" not in prod
    assert prod["PASSWORD_HASHERS"][0] == "django.contrib.auth.hashers.Argon2PasswordHasher"
    assert prod["EMAIL_BACKEND"] == "django.core.mail.backends.smtp.EmailBackend"
    assert prod["LOGGING"]["handlers"]["stdout"]["stream"] == "ext://sys.stdout"
    database = prod["DATABASES"]["default"]
    assert (database["NAME"], database["USER"], database["HOST"], database["PORT"]) == (
        "barf_prod",
        "barf_app",
        "db.internal",
        "5432",
    )


def test_prod_optional_settings_from_env(monkeypatch):
    prod = load_prod(
        monkeypatch,
        DJANGO_SECURE_HSTS_PRELOAD="true",
        DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS="false",
        DJANGO_SECURE_PROXY_SSL_HEADER="HTTP_X_FORWARDED_PROTO,https",
        DJANGO_TRUSTED_PROXY_COUNT="1",
        DJANGO_CSRF_TRUSTED_ORIGINS="https://barf.example.cz",
        DJANGO_EMAIL_HOST="smtp.example.cz",
        DJANGO_EMAIL_PORT="465",
        DJANGO_EMAIL_USE_TLS="false",
        DJANGO_EMAIL_USE_SSL="true",
        DJANGO_DEFAULT_FROM_EMAIL="BARF Nutri <info@example.cz>",
    )

    assert prod["SECURE_HSTS_PRELOAD"] is True
    assert prod["SECURE_HSTS_INCLUDE_SUBDOMAINS"] is False
    assert prod["SECURE_PROXY_SSL_HEADER"] == ("HTTP_X_FORWARDED_PROTO", "https")
    assert prod["TRUSTED_PROXY_COUNT"] == 1
    assert prod["CSRF_TRUSTED_ORIGINS"] == ["https://barf.example.cz"]
    assert (prod["EMAIL_HOST"], prod["EMAIL_PORT"], prod["EMAIL_USE_SSL"]) == (
        "smtp.example.cz",
        465,
        True,
    )
    assert prod["DEFAULT_FROM_EMAIL"] == prod["SERVER_EMAIL"] == "BARF Nutri <info@example.cz>"


@pytest.mark.parametrize(
    "overrides",
    [
        {"DJANGO_SECURE_PROXY_SSL_HEADER": "X_FORWARDED_PROTO,https"},
        {"DJANGO_SECURE_PROXY_SSL_HEADER": "HTTP_X_FORWARDED_PROTO"},
        {"DJANGO_EMAIL_USE_TLS": "true", "DJANGO_EMAIL_USE_SSL": "true"},
    ],
)
def test_prod_rejects_inconsistent_optional_settings(monkeypatch, overrides):
    with pytest.raises(ImproperlyConfigured):
        load_prod(monkeypatch, **overrides)


def run_manage(*args, extra_env=None):
    environment = {
        **os.environ,
        **PROD_ENV,
        "DJANGO_SECURE_HSTS_PRELOAD": "true",
        **(extra_env or {}),
    }
    environment.pop("DJANGO_SETTINGS_MODULE", None)
    return subprocess.run(
        [sys.executable, "manage.py", *args],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_prod_check_deploy_reports_no_issues():
    result = run_manage("check", "--deploy", "--settings=config.settings.prod")

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "System check identified no issues" in output, output


def test_prod_settings_fail_fast_in_a_fresh_process():
    result = run_manage(
        "check", "--settings=config.settings.prod", extra_env={"DJANGO_SECRET_KEY": ""}
    )

    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert "DJANGO_SECRET_KEY" in result.stderr


@pytest.mark.django_db
def test_tests_run_on_postgresql():
    from django.db import connection

    assert connection.vendor == "postgresql"
    assert connection.settings_dict["NAME"].startswith("test_")
