"""Public pages, layout, error pages, security headers and status badges."""

import pytest
from django.core.exceptions import PermissionDenied
from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import RequestFactory, override_settings
from django.urls import reverse
from django.views import defaults

from config.settings.base import BASE_DIR
from core.status import WARNING_LEVELS, level_style

pytestmark = pytest.mark.django_db

VET_NOTICE = "Aplikace nenahrazuje veterinární péči."


@pytest.mark.parametrize("url_name", ["core:home", "core:terms", "core:privacy"])
def test_public_pages_have_layout(client, url_name):
    response = client.get(reverse(url_name))

    content = response.content.decode()
    assert response.status_code == 200
    assert '<html lang="cs">' in content
    assert 'class="skip-link" href="#obsah"' in content
    assert 'id="obsah"' in content
    assert VET_NOTICE in content
    assert reverse("accounts:login") in content
    assert reverse("accounts:logout") not in content


def test_landing_page_explains_limits(client):
    content = client.get(reverse("core:home")).content.decode()

    assert "Co aplikace dělá" in content
    assert "Co aplikace není" in content
    assert "Náhrada veterinárního vyšetření" in content
    assert "Generátor léčebných diet" in content
    assert "Nutriční rozbor dávek" in content and "zatím není k dispozici" in content


def test_landing_page_redirects_signed_in_user(logged_in_client):
    response = logged_in_client.get(reverse("core:home"))
    assert response.status_code == 302
    assert response["Location"] == reverse("core:dashboard")


def test_dashboard_requires_login(client):
    response = client.get(reverse("core:dashboard"))
    assert response.status_code == 302
    assert response["Location"].startswith(reverse("accounts:login"))


def test_navigation_for_signed_in_user(logged_in_client):
    content = logged_in_client.get(reverse("core:dashboard")).content.decode()

    assert "Přehled" in content
    assert f'action="{reverse("accounts:logout")}"' in content
    assert 'method="post"' in content
    assert 'aria-current="page"' in content
    assert reverse("accounts:register") not in content
    assert reverse("admin:index") not in content
    assert VET_NOTICE in content


def test_navigation_shows_admin_link_to_staff(client, make_user):
    client.force_login(make_user("staff@example.cz", is_staff=True))
    assert reverse("admin:index") in client.get(reverse("core:dashboard")).content.decode()


@pytest.mark.parametrize("url_name", ["core:terms", "core:privacy"])
def test_legal_pages_are_marked_as_draft(client, url_name):
    content = client.get(reverse(url_name)).content.decode()
    assert "KONCEPT – není platné znění." in content
    assert "právník" in content
    assert "[DOPLNÍ PRÁVNÍK" in content


def test_security_headers(client):
    response = client.get(reverse("core:home"))

    assert response["X-Frame-Options"] == "DENY"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Referrer-Policy"] == "same-origin"
    csp = response["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "script-src 'self'" in csp


def test_csp_also_on_error_pages_but_not_on_debug_pages(client):
    with override_settings(DEBUG=False):
        assert "Content-Security-Policy" in client.get("/neexistuje/")
    with override_settings(DEBUG=True):
        assert "Content-Security-Policy" not in client.get("/neexistuje/")
        assert "Content-Security-Policy" in client.get(reverse("core:home"))


def test_templates_have_no_inline_scripts_or_styles():
    for path in (BASE_DIR / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        assert "<script" not in text, path
        assert "style=" not in text and "<style" not in text, path


# --- Error pages -------------------------------------------------------------------------


def test_404_page_is_czech(client):
    with override_settings(DEBUG=False):
        response = client.get("/neexistuje/")
    assert response.status_code == 404
    content = response.content.decode()
    assert "Stránka nenalezena" in content
    assert VET_NOTICE in content


def test_403_page_is_czech(rf_user_request):
    response = defaults.permission_denied(rf_user_request, PermissionDenied())
    assert response.status_code == 403
    assert "Přístup odepřen" in response.content.decode()


def test_500_page_renders_without_context():
    content = render_to_string("500.html")
    assert "Chyba serveru" in content
    assert '<html lang="cs">' in content


def test_csrf_failure_page_is_czech(client, user):
    csrf_client = client.__class__(enforce_csrf_checks=True)
    response = csrf_client.post(reverse("accounts:login"), {"email": user.email})
    assert response.status_code == 403
    assert "Formulář nelze odeslat" in response.content.decode()


@pytest.fixture
def rf_user_request():
    from django.contrib.auth.models import AnonymousUser

    request = RequestFactory().get("/zakazano/")
    request.user = AnonymousUser()
    return request


# --- Status badges (docs/08 §8.6) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("level", "icon", "label", "css"),
    [
        ("INFO", "ⓘ", "Informativní doporučení", "status--info"),
        ("NUTRITION_WARNING", "⚠", "Nutriční varování", "status--nutrition-warning"),
        ("EXPERT_REQUIRED", "🩺", "Vyžaduje odborné posouzení", "status--expert-required"),
        ("BLOCKED", "⛔", "Automatický výpočet nelze doporučit", "status--blocked"),
    ],
)
def test_status_badge_has_icon_text_and_colour_class(level, icon, label, css):
    html = Template("{% load status %}{% status_badge level %}").render(Context({"level": level}))

    assert icon in html and 'aria-hidden="true"' in html
    assert label in html
    assert css in html


def test_status_badge_appends_text():
    html = Template('{% load status %}{% status_badge "blocked" "CKD" %}').render(Context())
    assert "Automatický výpočet nelze doporučit" in html and ": CKD" in html


def test_unknown_level_is_an_error():
    with pytest.raises(ValueError):
        level_style("OK")


def test_stylesheet_defines_levels_schemes_and_focus():
    css = (BASE_DIR / "static" / "css" / "app.css").read_text(encoding="utf-8")

    assert "prefers-color-scheme: dark" in css
    assert ":focus-visible" in css
    assert ".skip-link" in css
    for style in WARNING_LEVELS.values():
        assert f".status--{style.css}" in css
        assert f".notice--{style.css}" in css
