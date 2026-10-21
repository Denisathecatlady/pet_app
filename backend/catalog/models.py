"""Library of scientific sources: the model ``ScientificSource`` (docs/07 §7.4, docs/13).

The registry docs/zdroje.md is the single source of truth. ``catalog/data/sources.json``
mirrors it and ``manage.py load_sources`` loads it into this table. The model describes
*sources and how far each one was verified*; it holds no nutrient, energy or dosing values.

Every change is kept in the history (django-simple-history, docs/07 §7.6). The history
is not deleted together with a source: it is the audit trail of reference data.

Deviations from the sketch in docs/07 §7.4 are listed in docs/13 §13.3 (nullable year, the
fields ``publication_details``, ``type_note``, ``verification_markers``, ``verification_note``
and ``key_findings``, ``verified_by`` set to NULL when the account is deleted).
"""

from collections.abc import Iterable
from datetime import date
from typing import Any, Final

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, URLValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

YEAR_MIN: Final = 1900
# Coarse envelope for the database; the exact upper bound (this year + 1) moves with time,
# so it is checked by ``validate_year`` only.
YEAR_DB_MAX: Final = 2100

DOI_PATTERN: Final = r"^10\.\d{4,9}/\S+$"
HTTP_URL_PATTERN: Final = r"^https?://\S+$"
CITATION_KEY_PATTERN: Final = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"


class SourceType(models.TextChoices):
    GUIDELINE = "GUIDELINE", "doporučení, standard nebo regulační profil"
    MONOGRAPH = "MONOGRAPH", "vědecká monografie"
    META_ANALYSIS = "META_ANALYSIS", "metaanalýza"
    REVIEW = "REVIEW", "přehledový článek"
    ORIGINAL_STUDY = "ORIGINAL_STUDY", "původní studie"
    CASE_REPORT = "CASE_REPORT", "kazuistika nebo série případů"
    FOOD_DATABASE = "FOOD_DATABASE", "databáze složení potravin"
    LAB_ANALYSIS = "LAB_ANALYSIS", "laboratorní rozbor"
    MANUFACTURER_DECLARATION = "MANUFACTURER_DECLARATION", "prohlášení výrobce"
    SECONDARY = "SECONDARY", "sekundární nebo populární zdroj"


class EvidenceLevel(models.TextChoices):
    """Levels of expertise of a source. The labels are the text of docs/zdroje.md
    ("Úrovně odbornosti zdroje") without the final full stop; a test keeps them in sync."""

    L1 = "L1", "Konsenzuální doporučení vědecké nebo odborné instituce (NRC, FEDIAF, AAFCO, WSAVA)"
    L2 = "L2", "Systematický přehled nebo metaanalýza v recenzovaném časopise"
    L3 = "L3", "Původní recenzovaná studie (experimentální, observační)"
    L4 = "L4", "Kazuistika nebo série případů"
    L5 = "L5", "Databáze složení potravin (kvalita se liší podle záznamu, hodnotí se zvlášť)"
    L6 = "L6", "Sekundární nebo populární zdroj. Smí sloužit jen k dohledání primárního zdroje"


class SpeciesScope(models.TextChoices):
    DOG = "DOG", "psi"
    CAT = "CAT", "kočky"
    BOTH = "BOTH", "psi i kočky"
    NOT_APPLICABLE = "NOT_APPLICABLE", "druh se neuplatňuje"


class LifeStage(models.TextChoices):
    """Life stages as named in docs/zdroje.md ("Dospělí, růst, reprodukce", "Všechny fáze")."""

    ADULT = "ADULT", "dospělí"
    GROWTH = "GROWTH", "růst"
    REPRODUCTION = "REPRODUCTION", "reprodukce"
    ALL_STAGES = "ALL_STAGES", "všechny fáze"


class VerificationLevel(models.TextChoices):
    """How far a source was verified. The labels are the meanings of docs/zdroje.md
    ("Jak číst sloupec Ověření v této fázi") without the final full stop."""

    B = "B", "Bibliografické údaje (autoři, rok, časopis, ročník, strany) ověřeny"
    A = "A", "Ověřen obsah abstraktu nebo souhrnu (hlavní zjištění)"
    P = "P", "Ověřena konkrétní hodnota nebo tabulka přímo v primárním zdroji"
    S = "S", "Hodnota ověřena jen přes sekundární zdroj, který primární zdroj cituje"
    NONE = "NONE", "Neověřeno. Uvedeno z odborné znalosti. Před použitím je nutné to ověřit"


# The marks B, A, P and S in the order of the legend. NONE is the absence of every mark.
MARKERS: Final = (VerificationLevel.B, VerificationLevel.A, VerificationLevel.P, VerificationLevel.S)

# What the single ``verification_level`` of a source with several marks is: the strongest
# one in this order, i.e. how far into the *content* the verification reached. A mark of a
# secondary source (S) says more about the content than bibliography alone (B); an abstract
# (A) more than a secondary source; the primary source (P) most. Working order of the
# developer (docs/13 §13.4), 🩺 to be confirmed by the specialist.
VERIFICATION_STRENGTH: Final = {
    VerificationLevel.NONE: 0,
    VerificationLevel.B: 1,
    VerificationLevel.S: 2,
    VerificationLevel.A: 3,
    VerificationLevel.P: 4,
}


def strongest_level(markers: Iterable[str]) -> str:
    """Return the verification level that summarises ``markers``.

    Inputs: marks ``B``, ``A``, ``P`` or ``S`` (any order). Output: the strongest one by
    ``VERIFICATION_STRENGTH``, or ``NONE`` for no marks.

    Raises:
        ValueError: a value that is not one of the four marks.
    """
    strongest = VerificationLevel.NONE
    for marker in markers:
        if marker not in MARKERS:
            raise ValueError(f"Unknown verification mark: {marker!r}")
        if VERIFICATION_STRENGTH[VerificationLevel(marker)] > VERIFICATION_STRENGTH[strongest]:
            strongest = VerificationLevel(marker)
    return strongest.value


def validate_year(value: int | None) -> None:
    """Allow ``None`` or a year from 1900 to next year (a source may be published ahead)."""
    if value is None:
        return
    latest = timezone.localdate().year + 1
    if not YEAR_MIN <= value <= latest:
        raise ValidationError(f"Rok musí být v rozmezí {YEAR_MIN}–{latest}.", code="invalid_year")


def validate_not_in_future(value: date | None) -> None:
    if value is not None and value > timezone.localdate():
        raise ValidationError("Datum ověření nemůže být v budoucnosti.", code="future_date")


def _validate_code_list(value: Any, allowed: Iterable[str], what: str) -> None:
    allowed = tuple(allowed)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationError(f"{what}: očekává se seznam kódů.", code="invalid_list")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise ValidationError(
            f"{what}: neznámé hodnoty {', '.join(unknown)}. Povolené: {', '.join(allowed)}.",
            code="invalid_choice",
        )
    if len(set(value)) != len(value):
        raise ValidationError(f"{what}: hodnoty se nesmí opakovat.", code="duplicate")


def validate_life_stages(value: Any) -> None:
    _validate_code_list(value, LifeStage.values, "Životní fáze")


def validate_markers(value: Any) -> None:
    _validate_code_list(value, [str(marker.value) for marker in MARKERS], "Značky ověření")


def _in(field: str, choices: type[models.TextChoices]) -> Q:
    return Q(**{f"{field}__in": choices.values})


class ScientificSource(models.Model):
    """One entry of the registry docs/zdroje.md: what the source is and how far it was verified."""

    citation_key = models.SlugField(
        "citační klíč",
        max_length=60,
        unique=True,
        error_messages={"unique": "Zdroj s tímto citačním klíčem už existuje."},
        help_text="Klíč z registru zdrojů, např. FEDIAF2025. Písmena bez diakritiky, číslice, "
        "pomlčka a podtržítko; velikost písmen se při porovnání nerozlišuje.",
    )
    title = models.TextField("název")
    authors_or_org = models.TextField(
        "autoři nebo organizace",
        blank=True,
        help_text="Prázdné, když je registr neuvádí (u některých zdrojů je „autory doplnit“).",
    )
    year = models.PositiveSmallIntegerField(
        "rok",
        null=True,
        blank=True,
        validators=[validate_year],
        help_text="Prázdné, když registr rok neuvádí. Povolené rozmezí je 1900 až příští rok.",
    )
    publication_details = models.TextField(
        "podrobnosti o vydání",
        blank=True,
        help_text="Časopis, ročník, strany, vydavatel a místo, identifikátory PubMed a PMC, "
        "zrcadlo souboru: vše, co registr uvádí o vydání mimo názvu, autorů, roku a odkazů.",
    )
    doi = models.CharField(
        "DOI",
        max_length=200,
        blank=True,
        validators=[RegexValidator(DOI_PATTERN, "DOI zadejte ve tvaru 10.xxxx/…, bez adresy.")],
    )
    url = models.URLField(
        "odkaz",
        max_length=500,
        blank=True,
        validators=[URLValidator(schemes=["http", "https"])],
    )
    source_type = models.CharField("typ zdroje", max_length=24, choices=SourceType.choices)
    type_note = models.CharField(
        "upřesnění typu",
        max_length=300,
        blank=True,
        help_text="Upřesnění typu zdroje tak, jak ho uvádí registr, např. „Validační studie“.",
    )
    evidence_level = models.CharField("úroveň důkazů", max_length=2, choices=EvidenceLevel.choices)
    species_scope = models.CharField("druh zvířat", max_length=14, choices=SpeciesScope.choices)
    life_stages = models.JSONField(
        "životní fáze",
        default=list,
        blank=True,
        validators=[validate_life_stages],
        help_text="Jen fáze, které registr nebo název zdroje výslovně uvádí. Prázdné = neuvedeno.",
    )
    units_and_conditions = models.TextField(
        "jednotky a podmínky",
        blank=True,
        help_text="Za jakých podmínek a v jakých jednotkách hodnoty zdroje platí.",
    )
    edition_version = models.CharField("vydání nebo verze", max_length=200, blank=True)
    verification_level = models.CharField(
        "stav ověření",
        max_length=4,
        choices=VerificationLevel.choices,
        help_text="Musí odpovídat nejsilnější ze značek B, A, P, S; bez značky je to NONE.",
    )
    verification_markers = models.JSONField(
        "značky ověření",
        default=list,
        blank=True,
        validators=[validate_markers],
        help_text="Všechny značky B, A, P, S, které registr u zdroje uvádí. Stav ověření je "
        "nejsilnější z nich; bez značky je stav „Neověřeno“.",
    )
    verification_note = models.TextField(
        "co přesně bylo ověřeno",
        blank=True,
        help_text="Poznámky k ověření z registru: co bylo ověřeno, čím a co ověřeno nebylo.",
    )
    last_verified_at = models.DateField(
        "datum posledního ověření",
        null=True,
        blank=True,
        validators=[validate_not_in_future],
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="ověřil",
        help_text="Jméno ani e-mail se na veřejných stránkách nezobrazují.",
    )
    limitations = models.TextField("omezení", blank=True)
    key_findings = models.TextField("hlavní zjištění", blank=True)
    created_at = models.DateTimeField("vytvořeno", auto_now_add=True)
    updated_at = models.DateTimeField("změněno", auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "odborný zdroj"
        verbose_name_plural = "odborné zdroje"
        ordering = ["evidence_level", F("year").desc(nulls_last=True), "citation_key"]
        constraints = [
            models.CheckConstraint(
                condition=Q(citation_key__regex=CITATION_KEY_PATTERN),
                name="catalog_source_key_format",
                violation_error_message="Citační klíč musí začínat písmenem nebo číslicí.",
            ),
            models.UniqueConstraint(
                Lower("citation_key"),
                name="catalog_source_key_unique_ci",
                violation_error_message="Zdroj s tímto citačním klíčem už existuje "
                "(velikost písmen se nerozlišuje).",
            ),
            models.CheckConstraint(
                condition=Q(title__regex=r"\S"),
                name="catalog_source_title_not_blank",
                violation_error_message="Zadejte název zdroje.",
            ),
            models.CheckConstraint(
                condition=Q(year__isnull=True) | Q(year__gte=YEAR_MIN, year__lte=YEAR_DB_MAX),
                name="catalog_source_year_range",
                violation_error_message="Rok je mimo povolené rozmezí.",
            ),
            models.CheckConstraint(
                condition=Q(doi="") | Q(doi__regex=DOI_PATTERN),
                name="catalog_source_doi_format",
                violation_error_message="DOI zadejte ve tvaru 10.xxxx/…, bez adresy.",
            ),
            models.CheckConstraint(
                condition=Q(url="") | Q(url__regex=HTTP_URL_PATTERN),
                name="catalog_source_url_http",
                violation_error_message="Odkaz musí začínat http:// nebo https://.",
            ),
            models.CheckConstraint(
                condition=_in("source_type", SourceType),
                name="catalog_source_type_valid",
                violation_error_message="Neplatný typ zdroje.",
            ),
            models.CheckConstraint(
                condition=_in("evidence_level", EvidenceLevel),
                name="catalog_source_evidence_valid",
                violation_error_message="Neplatná úroveň důkazů.",
            ),
            models.CheckConstraint(
                condition=_in("species_scope", SpeciesScope),
                name="catalog_source_species_valid",
                violation_error_message="Neplatný druh zvířat.",
            ),
            models.CheckConstraint(
                condition=_in("verification_level", VerificationLevel),
                name="catalog_source_verification_valid",
                violation_error_message="Neplatný stav ověření.",
            ),
            models.CheckConstraint(
                condition=Q(
                    verification_level=VerificationLevel.NONE,
                    last_verified_at__isnull=True,
                    verified_by__isnull=True,
                )
                | (
                    ~Q(verification_level=VerificationLevel.NONE)
                    & Q(last_verified_at__isnull=False)
                ),
                name="catalog_source_verification_dated",
                violation_error_message="Neověřený zdroj nemá datum ani osobu ověření; "
                "u ověřeného zdroje zadejte datum ověření.",
            ),
            models.CheckConstraint(
                condition=~Q(source_type=SourceType.FOOD_DATABASE)
                | Q(evidence_level=EvidenceLevel.L5),
                name="catalog_source_food_database_l5",
                violation_error_message="Databáze složení potravin má úroveň důkazů L5.",
            ),
            models.CheckConstraint(
                condition=~Q(source_type=SourceType.SECONDARY) | Q(evidence_level=EvidenceLevel.L6),
                name="catalog_source_secondary_l6",
                violation_error_message="Sekundární nebo populární zdroj má úroveň důkazů L6.",
            ),
        ]

    def __str__(self) -> str:
        return self.citation_key

    def get_absolute_url(self) -> str:
        return reverse("catalog:source_detail", kwargs={"citation_key": self.citation_key})

    @property
    def doi_url(self) -> str:
        """Link to the DOI (``https://doi.org/…``), empty without a DOI."""
        return f"https://doi.org/{self.doi}" if self.doi else ""

    def clean(self) -> None:
        """Check that the stored level is the strongest of the marks.

        Raises:
            ValidationError: ``verification_level`` differs from ``strongest_level`` of
                ``verification_markers`` (the markers themselves are validated by their field).
        """
        markers = self.verification_markers
        if not isinstance(markers, list) or any(marker not in MARKERS for marker in markers):
            return  # reported by the field validator
        expected = strongest_level(markers)
        if self.verification_level in VerificationLevel.values and (
            self.verification_level != expected
        ):
            raise ValidationError(
                {
                    "verification_level": (
                        "Stav ověření musí odpovídat nejsilnější ze značek "
                        f"({expected}); bez značky je to „Neověřeno“ (NONE)."
                    )
                }
            )
