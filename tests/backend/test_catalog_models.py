"""ScientificSource: validation, database constraints, ordering, history and deletion of the
verifier's account (docs/07 §7.4, docs/13)."""

from datetime import date, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.services import delete_account
from catalog.models import (
    MARKERS,
    EvidenceLevel,
    LifeStage,
    ScientificSource,
    SourceType,
    SpeciesScope,
    VerificationLevel,
    strongest_level,
)

pytestmark = pytest.mark.django_db

TODAY_YEAR = timezone.localdate().year


def full_clean_errors(**fields) -> dict[str, list[str]]:
    """Validate an unsaved source built from valid defaults plus ``fields``."""
    values = {
        "citation_key": "Probe2020",
        "title": "Zkušební zdroj",
        "source_type": SourceType.ORIGINAL_STUDY,
        "evidence_level": EvidenceLevel.L3,
        "species_scope": SpeciesScope.DOG,
        "verification_level": VerificationLevel.NONE,
        **fields,
    }
    try:
        ScientificSource(**values).full_clean()
    except ValidationError as error:
        return error.message_dict
    return {}


def test_valid_source_passes_validation(make_source, user):
    source = make_source(
        doi="10.1000/abc.123",
        url="https://example.org/paper",
        life_stages=[LifeStage.ADULT, LifeStage.GROWTH],
        verification_level=VerificationLevel.A,
        verification_markers=["B", "A"],
        last_verified_at=date(2026, 10, 18),
        verified_by=user,
    )
    assert source.pk and str(source) == source.citation_key
    assert source.doi_url == "https://doi.org/10.1000/abc.123"
    assert source.get_absolute_url() == f"/zdroje/{source.citation_key}/"
    assert source.life_stage_labels == ["dospělí", "růst"]
    assert source.marker_meanings[0][0] == "B"


def test_unverified_source_without_authors_and_year_is_valid():
    """The registry has sources without authors (“autory doplnit”) and without a year."""
    assert full_clean_errors(authors_or_org="", year=None) == {}


# --- Year -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("year", "valid"),
    [
        (1899, False),
        (1900, True),
        (2006, True),
        (TODAY_YEAR, True),
        (TODAY_YEAR + 1, True),
        (TODAY_YEAR + 2, False),
        (None, True),
    ],
)
def test_year_must_be_1900_to_next_year(year, valid):
    errors = full_clean_errors(year=year)
    assert ("year" not in errors) is valid
    if not valid:
        assert "1900" in errors["year"][0] and str(TODAY_YEAR + 1) in errors["year"][0]


def test_database_rejects_year_outside_envelope(make_source):
    source = make_source()
    for year in (1899, 2101):
        with pytest.raises(IntegrityError), transaction.atomic():
            ScientificSource.objects.filter(pk=source.pk).update(year=year)


# --- Citation key ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["", "FEDIAF 2025", "Köhler2012", "a/b", "-x", "_x"])
def test_citation_key_must_be_a_slug_starting_with_letter_or_digit(key):
    assert full_clean_errors(citation_key=key)


@pytest.mark.parametrize(
    "key", ["FEDIAF2025", "PNA-RER", "USDA-FDC", "a_b", "2025x", "Laflamme1997d"]
)
def test_registry_style_keys_are_valid(key, empty_library):
    assert full_clean_errors(citation_key=key) == {}


def test_citation_key_is_unique_ignoring_letter_case(make_source, empty_library):
    make_source(citation_key="FEDIAF2025")
    errors = full_clean_errors(citation_key="fediaf2025")
    assert errors, "the case-insensitive duplicate must be rejected"
    assert "citation_key" in errors or "__all__" in errors
    with pytest.raises(IntegrityError), transaction.atomic():
        ScientificSource.objects.create(
            citation_key="Fediaf2025",
            title="x",
            source_type=SourceType.GUIDELINE,
            evidence_level=EvidenceLevel.L1,
            species_scope=SpeciesScope.BOTH,
            verification_level=VerificationLevel.NONE,
        )


def test_exact_duplicate_key_has_czech_message(make_source):
    make_source(citation_key="Dup1")
    assert full_clean_errors(citation_key="Dup1")["citation_key"] == [
        "Zdroj s tímto citačním klíčem už existuje."
    ]


# --- DOI and URL ----------------------------------------------------------------------------


@pytest.mark.parametrize("doi", ["10.1371/journal.pone.0223099", "10.17226/10668", ""])
def test_valid_doi(doi):
    assert "doi" not in full_clean_errors(doi=doi)


@pytest.mark.parametrize(
    "doi", ["https://doi.org/10.1000/x", "doi:10.1000/x", "10.1/x", "11.1000/x", "10.1000/a b"]
)
def test_invalid_doi(doi):
    assert "doi" in full_clean_errors(doi=doi)


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "ftp://example.org/x", "data:text/html,x", "example.org", "http://"],
)
def test_url_must_be_http_or_https(url):
    assert "url" in full_clean_errors(url=url)


@pytest.mark.parametrize("url", ["", "http://example.org/a?b=c", "https://example.org/a_b-c/"])
def test_valid_url(url):
    assert "url" not in full_clean_errors(url=url)


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://example.org/x", "https:// x"])
def test_database_rejects_unsafe_url(make_source, url):
    source = make_source()
    with pytest.raises(IntegrityError), transaction.atomic():
        ScientificSource.objects.filter(pk=source.pk).update(url=url)


def test_database_rejects_malformed_doi(make_source):
    source = make_source()
    with pytest.raises(IntegrityError), transaction.atomic():
        ScientificSource.objects.filter(pk=source.pk).update(doi="not-a-doi")


# --- Choices --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field", ["source_type", "evidence_level", "species_scope", "verification_level"]
)
def test_choice_fields_reject_unknown_values_in_validation_and_database(make_source, field):
    assert field in full_clean_errors(**{field: "X9"})
    source = make_source()
    with pytest.raises(IntegrityError), transaction.atomic():
        ScientificSource.objects.filter(pk=source.pk).update(**{field: "X9"})


def test_choice_sets_match_the_specification():
    assert set(SourceType.values) == {
        "GUIDELINE",
        "MONOGRAPH",
        "META_ANALYSIS",
        "REVIEW",
        "ORIGINAL_STUDY",
        "CASE_REPORT",
        "FOOD_DATABASE",
        "LAB_ANALYSIS",
        "MANUFACTURER_DECLARATION",
        "SECONDARY",
    }
    assert EvidenceLevel.values == ["L1", "L2", "L3", "L4", "L5", "L6"]
    assert set(SpeciesScope.values) == {"DOG", "CAT", "BOTH", "NOT_APPLICABLE"}
    assert VerificationLevel.values == ["B", "A", "P", "S", "NONE"]


def test_blank_title_is_rejected(make_source):
    assert full_clean_errors(title="   ") == {"__all__": ["Zadejte název zdroje."]}
    source = make_source()
    with pytest.raises(IntegrityError), transaction.atomic():
        ScientificSource.objects.filter(pk=source.pk).update(title="  ")


@pytest.mark.parametrize(
    ("source_type", "evidence_level", "valid"),
    [
        (SourceType.FOOD_DATABASE, EvidenceLevel.L5, True),
        (SourceType.FOOD_DATABASE, EvidenceLevel.L3, False),
        (SourceType.SECONDARY, EvidenceLevel.L6, True),
        (SourceType.SECONDARY, EvidenceLevel.L1, False),
        (SourceType.GUIDELINE, EvidenceLevel.L1, True),
    ],
)
def test_weak_types_cannot_claim_a_higher_evidence_level(source_type, evidence_level, valid):
    errors = full_clean_errors(source_type=source_type, evidence_level=evidence_level)
    assert (errors == {}) is valid


# --- JSON lists -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stages", ["ADULT", {"ADULT": 1}, ["ADULT", "ADULT"], ["PUPPY"], [1], ["ADULT", None]]
)
def test_life_stages_must_be_a_list_of_known_unique_codes(stages):
    assert "life_stages" in full_clean_errors(life_stages=stages)


def test_life_stages_accepts_all_known_codes():
    assert full_clean_errors(life_stages=list(LifeStage.values)) == {}


@pytest.mark.parametrize("markers", ["B", ["B", "B"], ["X"], ["NONE"], [None], {"B": 1}])
def test_markers_must_be_a_list_of_unique_marks(markers):
    assert "verification_markers" in full_clean_errors(verification_markers=markers)


# --- Verification ---------------------------------------------------------------------------


def test_strongest_level_follows_the_documented_order():
    assert strongest_level([]) == "NONE"
    assert strongest_level(["B"]) == "B"
    assert strongest_level(["B", "S"]) == "S"
    assert strongest_level(["S", "B"]) == "S"
    assert strongest_level(["B", "A"]) == "A"
    assert strongest_level(["S", "A"]) == "A"
    assert strongest_level(["A", "P", "B"]) == "P"
    assert strongest_level(iter(["S"])) == "S"
    with pytest.raises(ValueError, match="Unknown verification mark"):
        strongest_level(["NONE"])
    assert [marker.value for marker in MARKERS] == ["B", "A", "P", "S"]


def test_level_must_be_the_strongest_mark():
    errors = full_clean_errors(
        verification_level="P",
        verification_markers=["B", "A"],
        last_verified_at=date(2026, 10, 18),
    )
    assert "A" in errors["verification_level"][0]
    errors = full_clean_errors(verification_level="B", verification_markers=[])
    assert "verification_level" in errors  # marks missing: only NONE fits
    ok = full_clean_errors(
        verification_level="A", verification_markers=["B", "A"], last_verified_at=date(2026, 10, 18)
    )
    assert ok == {}


def test_unverified_source_has_no_date_and_no_verifier(user):
    assert full_clean_errors(last_verified_at=date(2026, 10, 18))  # NONE with a date
    assert full_clean_errors(verified_by=user)  # NONE with a verifier


def test_verified_source_needs_a_date():
    errors = full_clean_errors(verification_level="B", verification_markers=["B"])
    assert errors
    assert (
        full_clean_errors(
            verification_level="B", verification_markers=["B"], last_verified_at=date(2026, 1, 1)
        )
        == {}
    )


def test_verification_date_cannot_be_in_the_future():
    tomorrow = timezone.localdate() + timedelta(days=1)
    errors = full_clean_errors(
        verification_level="B", verification_markers=["B"], last_verified_at=tomorrow
    )
    assert "last_verified_at" in errors


def test_database_enforces_the_verification_rules(make_source, user):
    source = make_source()
    with pytest.raises(IntegrityError), transaction.atomic():  # NONE with a date
        ScientificSource.objects.filter(pk=source.pk).update(last_verified_at=date(2026, 1, 1))
    with pytest.raises(IntegrityError), transaction.atomic():  # verified without a date
        ScientificSource.objects.filter(pk=source.pk).update(verification_level="B")
    with pytest.raises(IntegrityError), transaction.atomic():  # NONE with a verifier
        ScientificSource.objects.filter(pk=source.pk).update(verified_by=user)


# --- Ordering, history ----------------------------------------------------------------------


def test_default_ordering_is_evidence_level_then_newest_year_then_key(make_source, empty_library):
    make_source(citation_key="B", evidence_level="L3", year=2000)
    make_source(citation_key="A", evidence_level="L3", year=2000)
    make_source(citation_key="C", evidence_level="L3", year=2010)
    make_source(citation_key="D", evidence_level="L3", year=None)
    make_source(citation_key="E", evidence_level="L1", year=1990, source_type="GUIDELINE")
    keys = list(ScientificSource.objects.values_list("citation_key", flat=True))
    assert keys == ["E", "C", "A", "B", "D"]


def test_changes_are_recorded_in_history_and_survive_deletion(make_source):
    source = make_source(title="První")
    source.title = "Druhý"
    source.save()
    history = list(source.history.order_by("history_id").values_list("title", "history_type"))
    assert history == [("První", "+"), ("Druhý", "~")]
    key = source.citation_key
    source.delete()
    assert (
        ScientificSource.history.filter(citation_key=key).count() == 3
    )  # created, changed, deleted


# --- Deleting the verifier's account --------------------------------------------------------


def verified_source(make_source, user):
    return make_source(
        verification_level="B",
        verification_markers=["B"],
        last_verified_at=date(2026, 10, 18),
        verified_by=user,
    )


def test_deleting_the_verifier_keeps_the_source(make_source, user):
    source = verified_source(make_source, user)
    source.title = "Po úpravě"
    source.save()  # a second history row that also names the verifier

    delete_account(user)

    source.refresh_from_db()
    assert source.verified_by is None
    assert source.verification_level == "B" and source.last_verified_at == date(2026, 10, 18)
    assert source.history.exclude(verified_by=None).count() == 0  # no leftover of the account


def test_deleting_the_verifier_in_a_second_source_with_history_user(make_source, user):
    """``history_user`` is a real foreign key: it is set to NULL, the history stays."""
    source = make_source()
    record = source.history.get()
    record.history_user = user
    record.save()

    delete_account(user)

    record.refresh_from_db()
    assert record.history_user is None
    assert ScientificSource.objects.filter(pk=source.pk).exists()
