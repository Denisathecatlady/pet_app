"""Admin of the library, the GDPR export of the catalog section and deleting the account of
somebody who verified sources (docs/07 §7.6, §7.7, docs/12 §12.6)."""

import json
import re
from datetime import date

import pytest
from django.contrib import admin
from django.contrib.admin.models import LogEntry
from django.urls import reverse
from simple_history.admin import SimpleHistoryAdmin

from accounts.export import build_export
from accounts.models import User
from catalog.models import ScientificSource
from tests.backend.helpers import PASSWORD

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user() -> User:
    return User.objects.create_superuser("admin@example.cz", PASSWORD)


@pytest.fixture
def admin_client(client, admin_user):
    client.force_login(admin_user)
    return client


def verified(make_source, user, **fields) -> ScientificSource:
    return make_source(
        verification_level="B",
        verification_markers=["B"],
        last_verified_at=date(2026, 10, 18),
        verified_by=user,
        **fields,
    )


# --- Admin --------------------------------------------------------------------------------------


def test_model_uses_history_admin_with_filters_and_search():
    model_admin = admin.site._registry[ScientificSource]
    assert isinstance(model_admin, SimpleHistoryAdmin)
    assert set(model_admin.list_filter) == {
        "evidence_level",
        "source_type",
        "species_scope",
        "verification_level",
    }
    assert {"citation_key", "title", "authors_or_org"} <= set(model_admin.search_fields)


def test_admin_pages_load(admin_client, make_source):
    source = make_source()
    for url in (
        reverse("admin:catalog_scientificsource_changelist"),
        reverse("admin:catalog_scientificsource_add"),
        reverse("admin:catalog_scientificsource_change", args=[source.pk]),
        reverse("admin:catalog_scientificsource_history", args=[source.pk]),
    ):
        assert admin_client.get(url).status_code == 200, url


def test_admin_requires_staff(client, logged_in_client):
    url = reverse("admin:catalog_scientificsource_changelist")
    assert client.get(url).status_code == 302
    assert logged_in_client.get(url).status_code == 302  # not a staff member


def test_changelist_filters_and_searches(admin_client, empty_library, make_source):
    make_source(citation_key="Aaa1", title="Alfa", evidence_level="L3")
    make_source(
        citation_key="Bbb1",
        title="Beta",
        evidence_level="L1",
        source_type="GUIDELINE",
        species_scope="BOTH",
    )
    url = reverse("admin:catalog_scientificsource_changelist")

    everything = admin_client.get(url).content.decode()
    only_l1 = admin_client.get(url, {"evidence_level__exact": "L1"}).content.decode()
    found = admin_client.get(url, {"q": "alfa"}).content.decode()

    assert "Aaa1" in everything and "Bbb1" in everything
    assert "Bbb1" in only_l1 and "Aaa1" not in only_l1
    assert "Aaa1" in found and "Bbb1" not in found


def admin_data(**changes) -> dict:
    data = {
        "citation_key": "Adm2026",
        "title": "Přidáno v administraci",
        "authors_or_org": "Autor",
        "year": "2026",
        "publication_details": "",
        "edition_version": "",
        "doi": "",
        "url": "",
        "source_type": "ORIGINAL_STUDY",
        "type_note": "",
        "evidence_level": "L3",
        "species_scope": "DOG",
        "units_and_conditions": "",
        "verification_level": "NONE",
        "verification_note": "",
        "last_verified_at": "",
        "limitations": "",
        "key_findings": "",
        "_save": "Uložit",
    }
    return {**data, **changes}


def test_admin_adds_a_source_from_check_boxes(admin_client, admin_user):
    response = admin_client.post(
        reverse("admin:catalog_scientificsource_add"),
        admin_data(
            life_stages=["GROWTH", "ADULT"],  # any order is stored in the canonical one
            verification_level="A",
            verification_markers=["A", "B"],
            last_verified_at="18.10.2026",
            url="example.org/clanek",  # a form address without scheme means https
            verified_by=admin_user.pk,
        ),
    )

    assert response.status_code == 302, response.content.decode()[:3000]
    source = ScientificSource.objects.get(citation_key="Adm2026")
    assert source.life_stages == ["ADULT", "GROWTH"]
    assert source.verification_markers == ["B", "A"]
    assert source.verification_level == "A" and source.last_verified_at == date(2026, 10, 18)
    assert source.url == "https://example.org/clanek"
    assert source.verified_by == admin_user
    record = source.history.get()
    assert record.history_user == admin_user and record.history_type == "+"


def test_admin_rejects_a_level_that_is_not_the_strongest_mark(admin_client):
    response = admin_client.post(
        reverse("admin:catalog_scientificsource_add"),
        admin_data(
            verification_level="P", verification_markers=["B"], last_verified_at="18.10.2026"
        ),
    )
    assert response.status_code == 200
    assert "Stav ověření musí odpovídat nejsilnější ze značek (B)" in response.content.decode()
    assert not ScientificSource.objects.filter(citation_key="Adm2026").exists()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"year": "1800"}, "Rok musí být v rozmezí 1900"),
        ({"doi": "https://doi.org/10.1/x"}, "DOI zadejte ve tvaru"),
        ({"url": "javascript:alert(1)"}, "Zadejte platnou adresu URL"),
        ({"citation_key": "má mezeru"}, "Vložte platný identifikátor"),
        ({"source_type": "FOOD_DATABASE"}, "Databáze složení potravin má úroveň důkazů L5."),
        ({"last_verified_at": "18.10.2026"}, "Neověřený zdroj nemá datum ani osobu ověření"),
    ],
)
def test_admin_shows_czech_validation_errors(admin_client, changes, message):
    response = admin_client.post(
        reverse("admin:catalog_scientificsource_add"), admin_data(**changes)
    )
    assert response.status_code == 200
    assert message in response.content.decode()
    assert not ScientificSource.objects.filter(citation_key="Adm2026").exists()


def test_admin_change_form_shows_the_stored_check_boxes(admin_client, make_source):
    source = make_source(
        life_stages=["GROWTH"],
        verification_level="S",
        verification_markers=["B", "S"],
        last_verified_at=date(2026, 10, 18),
    )
    content = admin_client.get(
        reverse("admin:catalog_scientificsource_change", args=[source.pk])
    ).content.decode()
    checked = set(
        re.findall(
            r'<input type="checkbox" name="(?:life_stages|verification_markers)" '
            r'value="(\w+)" id="\w+" checked>',
            content,
        )
    )
    assert checked == {"GROWTH", "B", "S"}


def test_admin_change_is_recorded_in_history(admin_client, admin_user, make_source):
    source = make_source(title="Před")
    data = admin_data(citation_key=source.citation_key, title="Po", year="2020")

    response = admin_client.post(
        reverse("admin:catalog_scientificsource_change", args=[source.pk]), data
    )

    assert response.status_code == 302
    source.refresh_from_db()
    assert source.title == "Po"
    changed = source.history.filter(history_type="~").get()
    assert changed.history_user == admin_user and changed.title == "Po"
    assert LogEntry.objects.filter(object_id=str(source.pk)).exists()


# --- GDPR export ---------------------------------------------------------------------------------


def test_export_lists_verified_sources_and_own_changes(make_source, user, make_user):
    other = make_user("other@example.cz")
    mine = verified(make_source, user, citation_key="Mine1")
    verified(make_source, other, citation_key="Theirs1")
    make_source(citation_key="Nobody1")
    mine._history_user = user
    mine.title = "Změněno uživatelem"
    mine.save()

    section = build_export(user)["data"]["catalog"]

    assert section["verified_sources"] == [
        {"citation_key": "Mine1", "last_verified_at": "2026-10-18"}
    ]
    (change,) = section["changes"]
    assert change["citation_key"] == "Mine1" and change["type"] == "changed"
    assert change["changed_at"].startswith("20")
    assert "Theirs1" not in json.dumps(section) and "other@example.cz" not in json.dumps(section)


def test_export_is_empty_for_everybody_else(user):
    assert build_export(user)["data"]["catalog"] == {"verified_sources": [], "changes": []}


def test_export_download_contains_the_section(logged_in_client, make_source, user):
    verified(make_source, user, citation_key="Mine1")
    raw = logged_in_client.get(reverse("accounts:export")).content.decode()
    assert json.loads(raw)["data"]["catalog"]["verified_sources"][0]["citation_key"] == "Mine1"


# --- Deleting the account of a verifier ------------------------------------------------------------


def test_deleting_an_account_through_the_page_keeps_the_sources(client, user, make_source):
    source = verified(make_source, user, citation_key="Mine1")
    client.post(reverse("accounts:login"), {"email": user.email, "password": PASSWORD})

    response = client.post(reverse("accounts:delete"), {"password": PASSWORD})

    assert response.status_code == 302 and response["Location"] == reverse("accounts:deleted")
    assert not User.objects.filter(pk=user.pk).exists()
    source.refresh_from_db()
    assert source.verified_by is None
    assert source.verification_level == "B" and source.last_verified_at == date(2026, 10, 18)
    assert client.get(source.get_absolute_url()).status_code == 200  # still public


def test_deleting_the_account_in_the_admin_works_too(admin_client, user, make_source):
    source = verified(make_source, user, citation_key="Mine1")
    url = reverse("admin:accounts_user_delete", args=[user.pk])

    response = admin_client.post(url, {"post": "yes"})

    assert response.status_code == 302
    source.refresh_from_db()
    assert source.verified_by is None
    assert not source.history.exclude(verified_by=None).exists()


def test_deleting_another_account_leaves_the_verifier_alone(make_user, make_source, user):
    source = verified(make_source, user, citation_key="Mine1")
    make_user("other@example.cz").delete()
    source.refresh_from_db()
    assert source.verified_by == user
