"""Animals, body measurements, health conditions and sharing with a vet (docs/07 §7.4).

The nutrition parts of docs/07 §7.4 (preferred standard profile, recipes) are not
modelled yet: the calculator is out of scope of this iteration.

Every model keeps its change history (django-simple-history, docs/07 §7.6). History of
user data is deleted together with the object (``cascade_delete_history``): deleting an
animal or an account removes the data for good (GDPR art. 17, docs/07 §7.7).
"""

import re
import uuid
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final

from django.conf import settings
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import format as format_date
from simple_history.models import HistoricalRecords

from accounts.roles import Role


class Species(models.TextChoices):
    DOG = "DOG", "pes"
    CAT = "CAT", "kočka"


class Sex(models.TextChoices):
    MALE = "MALE", "samec"
    FEMALE = "FEMALE", "samice"


class SizeCategory(models.TextChoices):
    TOY = "TOY", "toy (velmi malé plemeno)"
    SMALL = "SMALL", "malé plemeno"
    MEDIUM = "MEDIUM", "střední plemeno"
    LARGE = "LARGE", "velké plemeno"
    GIANT = "GIANT", "obří plemeno"


class TargetWeightStatus(models.TextChoices):
    """docs/05 §5.3: the target weight is an orientational value until a vet confirms it."""

    UNVERIFIED = "UNVERIFIED", "orientační"
    VET_CONFIRMED = "VET_CONFIRMED", "potvrzeno veterinářem"


class ActivityLevel(models.TextChoices):
    """Activity categories of docs/05 §5.3, described in words only (no energy numbers)."""

    LOW = "LOW", "Nízká – zvíře většinu dne odpočívá, pohybu má málo"
    MODERATE = "MODERATE", "Střední – běžný denní pohyb a hra"
    MODERATE_HIGH_IMPACT = (
        "MODERATE_HIGH_IMPACT",
        "Střední s vysokou zátěží – pravidelný intenzivní pohyb (např. běh, sport)",
    )
    HIGH = "HIGH", "Vysoká – pracovní nebo sportovní zvíře s každodenní vysokou zátěží"


class PhysiologicalState(models.TextChoices):
    MAINTENANCE = "MAINTENANCE", "dospělé zvíře (udržovací stav)"
    GROWTH = "GROWTH", "růst (štěně, kotě)"
    GESTATION = "GESTATION", "březost"
    LACTATION = "LACTATION", "laktace (kojení mláďat)"


FEMALE_ONLY_STATES: Final = frozenset({PhysiologicalState.GESTATION, PhysiologicalState.LACTATION})


class MuscleCondition(models.TextChoices):
    """WSAVA muscle condition score categories (docs/09 §9.2, ``[WSAVA2011]``)."""

    NORMAL = "NORMAL", "normální svalová hmota"
    MILD_LOSS = "MILD_LOSS", "mírná ztráta svalové hmoty"
    MODERATE_LOSS = "MODERATE_LOSS", "střední ztráta svalové hmoty"
    SEVERE_LOSS = "SEVERE_LOSS", "výrazná ztráta svalové hmoty"


class Assessor(models.TextChoices):
    OWNER = "OWNER", "majitel"
    VET = "VET", "veterinární lékař"


class ConditionMode(models.TextChoices):
    """Gate level of a health condition (docs/09 §9.2, docs/08 §8.6)."""

    EXPERT_REQUIRED = "EXPERT_REQUIRED", "vyžaduje odborné posouzení"
    BLOCKED = "BLOCKED", "automatický výpočet nelze doporučit"


# TECHNICAL SANITY BOUNDS, NOT NUTRITION OR REFERENCE DATA. They only catch typing errors
# (grams instead of kilograms, an extra digit). The values are a working proposal of the
# developer and must be confirmed by the veterinary nutrition specialist (docs/09 §9.2).
WEIGHT_BOUNDS_KG: Final = MappingProxyType(
    {
        Species.DOG: (Decimal("0.5"), Decimal("120")),
        Species.CAT: (Decimal("0.5"), Decimal("15")),
    }
)
# Envelope of all species, used where the species is not on the same row (measurements).
WEIGHT_MIN_KG: Final = min(low for low, _ in WEIGHT_BOUNDS_KG.values())
WEIGHT_MAX_KG: Final = max(high for _, high in WEIGHT_BOUNDS_KG.values())

BCS_MIN: Final = 1
BCS_MAX: Final = 9

ALLERGY_MAX_LENGTH: Final = 60
ALLERGY_MAX_COUNT: Final = 30

# A vet confirms the target weight of this animal as it is described (docs/05 §5.3). When
# any of these fields changes, the confirmation no longer applies and is cancelled.
CONFIRMATION_BASIS_FIELDS: Final = ("target_weight_kg", "species", "physiological_state")


def format_kg(value: Decimal) -> str:
    """Return ``value`` in Czech notation without trailing zeros.

    Example: ``Decimal("12.50")`` → ``"12,5"``.
    """
    text = format(value.normalize(), "f")
    return text.replace(".", ",")


def weight_error(species: str, value: Decimal | None) -> str | None:
    """Return a Czech error message if ``value`` (kg) is outside the bounds for ``species``.

    Inputs: species code and a weight or ``None``. ``None`` and an unknown species
    (reported by the species field itself) return ``None``.
    """
    if value is None or species not in WEIGHT_BOUNDS_KG:
        return None
    low, high = WEIGHT_BOUNDS_KG[Species(species)]
    if low <= value <= high:
        return None
    noun = "psa" if species == Species.DOG else "kočky"
    return (
        f"Hmotnost {noun} zadejte v kilogramech v rozmezí {format_kg(low)}–{format_kg(high)} kg. "
        "Jde o technickou kontrolu překlepů."
    )


def normalize_allergies(value: Any) -> list[str]:
    """Normalise allergies to a list of unique, lower-case items.

    Inputs: comma (or semicolon / newline) separated text, or an iterable of strings.
    Output: items stripped, inner whitespace collapsed, lower-cased, empty items
    dropped, duplicates removed (first occurrence wins).

    Raises:
        ValidationError: an item is not a string, is longer than
            ``ALLERGY_MAX_LENGTH`` or there are more than ``ALLERGY_MAX_COUNT`` items.
    """
    if value is None:
        return []
    if isinstance(value, str):
        items: Iterable[Any] = re.split(r"[,;\n]", value)
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        raise ValidationError("Alergie musí být seznam textů.", code="invalid")
    result: list[str] = []
    for item in items:
        if not isinstance(item, str):
            raise ValidationError("Alergie musí být seznam textů.", code="invalid")
        text = " ".join(item.split()).lower()
        if not text or text in result:
            continue
        if len(text) > ALLERGY_MAX_LENGTH:
            raise ValidationError(
                f"Položka „{text[:20]}…“ je delší než {ALLERGY_MAX_LENGTH} znaků.", code="too_long"
            )
        result.append(text)
    if len(result) > ALLERGY_MAX_COUNT:
        raise ValidationError(f"Zadejte nejvýše {ALLERGY_MAX_COUNT} položek.", code="too_many")
    return result


def _czech_date(value: date) -> str:
    return format_date(value, "j. n. Y")


def _before_birth(animal: "Animal", value: date | None) -> bool:
    """Return whether ``value`` precedes the animal's birth date.

    Only an exact birth date counts; an estimated one (``birth_date_estimated``) may be
    off, so nothing is rejected against it.
    """
    birth = animal.birth_date
    return bool(value and birth and not animal.birth_date_estimated and value < birth)


def _choices(field: str, choices: type[models.TextChoices], *, blank: bool = False) -> Q:
    condition = Q(**{f"{field}__in": choices.values})
    return condition | Q(**{field: ""}) if blank else condition


def _weight_within_bounds(field: str) -> Q:
    """``field`` is empty or within the bounds of the row's species."""
    condition = Q(**{f"{field}__isnull": True})
    for species, (low, high) in WEIGHT_BOUNDS_KG.items():
        condition |= Q(species=species, **{f"{field}__gte": low, f"{field}__lte": high})
    return condition


def _weight_field(verbose_name: str, **kwargs: Any) -> models.DecimalField:
    # Kilograms with gram resolution.
    return models.DecimalField(verbose_name, max_digits=6, decimal_places=3, **kwargs)


class Animal(models.Model):
    uuid = models.UUIDField(
        "veřejný identifikátor", default=uuid.uuid4, unique=True, editable=False
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="animals",
        verbose_name="majitel",
    )
    name = models.CharField("jméno", max_length=100)
    species = models.CharField("druh", max_length=3, choices=Species.choices)
    sex = models.CharField("pohlaví", max_length=6, choices=Sex.choices)
    neutered = models.BooleanField("kastrace", default=False)
    birth_date = models.DateField("datum narození", null=True, blank=True)
    birth_date_estimated = models.BooleanField("datum narození je odhad", default=False)
    breed = models.CharField("plemeno", max_length=100, blank=True)
    size_category = models.CharField(
        "velikostní kategorie", max_length=6, choices=SizeCategory.choices, blank=True
    )
    expected_adult_weight_kg = _weight_field(
        "očekávaná hmotnost v dospělosti (kg)", null=True, blank=True
    )
    target_weight_kg = _weight_field("cílová hmotnost (kg)", null=True, blank=True)
    target_weight_status = models.CharField(
        "stav cílové hmotnosti",
        max_length=13,
        choices=TargetWeightStatus.choices,
        default=TargetWeightStatus.UNVERIFIED,
    )
    target_weight_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="cílovou hmotnost potvrdil",
    )
    target_weight_confirmed_at = models.DateTimeField(
        "cílová hmotnost potvrzena", null=True, blank=True
    )
    activity_level = models.CharField("aktivita", max_length=20, choices=ActivityLevel.choices)
    physiological_state = models.CharField(
        "fyziologický stav",
        max_length=11,
        choices=PhysiologicalState.choices,
        default=PhysiologicalState.MAINTENANCE,
    )
    current_feeding = models.TextField("současné krmení", blank=True)
    allergies = models.JSONField("alergie a nesnášenlivosti", default=list, blank=True)
    notes = models.TextField("poznámky", blank=True)
    created_at = models.DateTimeField("vytvořeno", auto_now_add=True)
    updated_at = models.DateTimeField("změněno", auto_now=True)

    history = HistoricalRecords(cascade_delete_history=True)

    class Meta:
        verbose_name = "zvíře"
        verbose_name_plural = "zvířata"
        ordering = ["name", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(name__regex=r"\S"),
                name="animals_animal_name_not_blank",
                violation_error_message="Zadejte jméno zvířete.",
            ),
            models.CheckConstraint(
                condition=_choices("species", Species),
                name="animals_animal_species_valid",
                violation_error_message="Neplatný druh zvířete.",
            ),
            models.CheckConstraint(
                condition=_choices("sex", Sex),
                name="animals_animal_sex_valid",
                violation_error_message="Neplatné pohlaví.",
            ),
            models.CheckConstraint(
                condition=_choices("activity_level", ActivityLevel),
                name="animals_animal_activity_level_valid",
                violation_error_message="Neplatná úroveň aktivity.",
            ),
            models.CheckConstraint(
                condition=Q(size_category="")
                | Q(species=Species.DOG, size_category__in=SizeCategory.values),
                name="animals_animal_size_category_dogs_only",
                violation_error_message="Velikostní kategorie se zadává jen u psů.",
            ),
            models.CheckConstraint(
                condition=Q(
                    physiological_state__in=[
                        PhysiologicalState.MAINTENANCE,
                        PhysiologicalState.GROWTH,
                    ]
                )
                | Q(physiological_state__in=sorted(FEMALE_ONLY_STATES), sex=Sex.FEMALE),
                name="animals_animal_physiological_state_valid",
                violation_error_message="Březost a laktaci lze zadat jen u samice.",
            ),
            models.CheckConstraint(
                condition=Q(birth_date__isnull=False) | Q(birth_date_estimated=False),
                name="animals_animal_estimate_needs_birth_date",
                violation_error_message="Odhad lze označit jen u zadaného data narození.",
            ),
            models.CheckConstraint(
                condition=_weight_within_bounds("expected_adult_weight_kg"),
                name="animals_animal_expected_adult_weight_bounds",
                violation_error_message="Očekávaná hmotnost v dospělosti je mimo povolené rozmezí.",
            ),
            models.CheckConstraint(
                condition=_weight_within_bounds("target_weight_kg"),
                name="animals_animal_target_weight_bounds",
                violation_error_message="Cílová hmotnost je mimo povolené rozmezí.",
            ),
            models.CheckConstraint(
                condition=Q(
                    target_weight_status=TargetWeightStatus.UNVERIFIED,
                    target_weight_confirmed_by__isnull=True,
                    target_weight_confirmed_at__isnull=True,
                )
                | Q(
                    target_weight_status=TargetWeightStatus.VET_CONFIRMED,
                    target_weight_kg__isnull=False,
                    target_weight_confirmed_by__isnull=False,
                    target_weight_confirmed_at__isnull=False,
                ),
                name="animals_animal_target_weight_confirmation",
                violation_error_message=(
                    "Potvrzená cílová hmotnost musí mít hodnotu, veterináře a čas potvrzení; "
                    "orientační je nemá."
                ),
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("animals:detail", kwargs={"animal_uuid": self.uuid})

    @property
    def target_weight_confirmed(self) -> bool:
        return self.target_weight_status == TargetWeightStatus.VET_CONFIRMED

    def reset_target_weight_confirmation(self) -> None:
        """Mark the target weight as orientational again (not saved)."""
        self.target_weight_status = TargetWeightStatus.UNVERIFIED
        self.target_weight_confirmed_by = None
        self.target_weight_confirmed_at = None

    def clean(self) -> None:
        """Validate cross-field rules with field-level Czech messages.

        Also cancels a vet's target-weight confirmation when a field it is based on
        (``CONFIRMATION_BASIS_FIELDS``) changed against the stored row, whoever edits
        the animal (owner's form, admin). See :meth:`_check_target_weight_confirmation`.

        Raises:
            ValidationError: birth date in the future or later than a stored
                measurement or condition start, size category for a cat, gestation
                or lactation for a male, weights outside ``WEIGHT_BOUNDS_KG``,
                malformed allergies, a species change that existing measurements do
                not fit, or a new confirmation by an account without the vet role.
        """
        errors: dict[str, str] = {}
        if self.birth_date and self.birth_date > timezone.localdate():
            errors["birth_date"] = "Datum narození nemůže být v budoucnosti."
        elif (
            self.pk
            and self.birth_date
            and not self.birth_date_estimated
            and (
                self.measurements.filter(measured_on__lt=self.birth_date).exists()
                or self.conditions.filter(since__lt=self.birth_date).exists()
            )
        ):
            errors["birth_date"] = (
                "Datum narození je pozdější než některé uložené měření nebo začátek "
                "zdravotního stavu. Opravte datum, nebo ho označte jako odhad."
            )
        if self.birth_date_estimated and not self.birth_date:
            errors["birth_date_estimated"] = "Odhad lze označit jen u zadaného data narození."
        if self.species == Species.CAT and self.size_category:
            errors["size_category"] = "Velikostní kategorie se zadává jen u psů."
        if self.physiological_state in FEMALE_ONLY_STATES and self.sex != Sex.FEMALE:
            errors["physiological_state"] = "Březost a laktaci lze zadat jen u samice."
        for field in ("expected_adult_weight_kg", "target_weight_kg"):
            message = weight_error(self.species, getattr(self, field))
            if message:
                errors[field] = message
        try:
            self.allergies = normalize_allergies(self.allergies)
        except ValidationError as error:
            errors["allergies"] = error.messages[0]
        if self.pk and self.species in WEIGHT_BOUNDS_KG:
            low, high = WEIGHT_BOUNDS_KG[Species(self.species)]
            outside = self.measurements.exclude(weight_kg__gte=low, weight_kg__lte=high)
            if outside.exists():
                errors["species"] = (
                    "Druh nelze změnit: některá uložená měření mají hmotnost mimo rozmezí "
                    "pro zvolený druh. Nejdříve je opravte nebo smažte."
                )
        message = self._check_target_weight_confirmation()
        if message:
            errors[NON_FIELD_ERRORS] = message
        if errors:
            raise ValidationError(errors)

    def _check_target_weight_confirmation(self) -> str | None:
        """Keep the confirmation invariant of docs/05 §5.3 for every edit path.

        A confirmation already stored is cancelled (not saved here) when a field of
        ``CONFIRMATION_BASIS_FIELDS`` differs from the stored row: the vet confirmed the
        old values. A confirmation set in this edit must name an account with the vet
        role. Output: an error message, or ``None``.
        """
        if not self.target_weight_confirmed:
            return None
        stored = None
        if self.pk:
            stored = (
                Animal.objects.filter(pk=self.pk)
                .values(
                    *CONFIRMATION_BASIS_FIELDS,
                    "target_weight_status",
                    "target_weight_confirmed_by",
                    "target_weight_confirmed_at",
                )
                .first()
            )
        if stored is not None and (
            stored["target_weight_status"],
            stored["target_weight_confirmed_by"],
            stored["target_weight_confirmed_at"],
        ) == (
            self.target_weight_status,
            self.target_weight_confirmed_by_id,
            self.target_weight_confirmed_at,
        ):
            if any(stored[name] != getattr(self, name) for name in CONFIRMATION_BASIS_FIELDS):
                self.reset_target_weight_confirmation()
            return None
        confirmed_by = self.target_weight_confirmed_by
        if confirmed_by is not None and not confirmed_by.has_role(Role.VET):
            return "Cílovou hmotnost může potvrdit jen účet s rolí veterinárního lékaře."
        return None


class BodyMeasurement(models.Model):
    uuid = models.UUIDField(
        "veřejný identifikátor", default=uuid.uuid4, unique=True, editable=False
    )
    animal = models.ForeignKey(
        Animal, on_delete=models.CASCADE, related_name="measurements", verbose_name="zvíře"
    )
    measured_on = models.DateField("datum měření")
    weight_kg = _weight_field("hmotnost (kg)")
    bcs = models.PositiveSmallIntegerField("BCS (1–9)", null=True, blank=True)
    mcs = models.CharField(
        "svalová kondice (MCS)", max_length=13, choices=MuscleCondition.choices, blank=True
    )
    assessed_by = models.CharField("posoudil", max_length=5, choices=Assessor.choices)
    note = models.TextField("poznámka", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="zapsal",
    )
    created_at = models.DateTimeField("zapsáno", auto_now_add=True)

    history = HistoricalRecords(cascade_delete_history=True)

    class Meta:
        verbose_name = "měření hmotnosti a kondice"
        verbose_name_plural = "měření hmotnosti a kondice"
        ordering = ["-measured_on", "-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(weight_kg__gte=WEIGHT_MIN_KG, weight_kg__lte=WEIGHT_MAX_KG),
                name="animals_measurement_weight_bounds",
                violation_error_message="Hmotnost je mimo povolené rozmezí.",
            ),
            models.CheckConstraint(
                condition=Q(bcs__isnull=True) | Q(bcs__gte=BCS_MIN, bcs__lte=BCS_MAX),
                name="animals_measurement_bcs_range",
                violation_error_message="BCS musí být celé číslo 1–9.",
            ),
            models.CheckConstraint(
                condition=_choices("mcs", MuscleCondition, blank=True),
                name="animals_measurement_mcs_valid",
                violation_error_message="Neplatná hodnota svalové kondice.",
            ),
            models.CheckConstraint(
                condition=_choices("assessed_by", Assessor),
                name="animals_measurement_assessed_by_valid",
                violation_error_message="Neplatná hodnota „posoudil“.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.animal} {self.measured_on:%Y-%m-%d}: {format_kg(self.weight_kg)} kg"

    def clean(self) -> None:
        """Validate the date and the species-specific weight bounds.

        Raises:
            ValidationError: measurement date in the future or before the animal's
                exact birth date, weight outside the bounds of the animal's species,
                BCS outside 1–9.
        """
        errors: dict[str, str] = {}
        if self.measured_on and self.measured_on > timezone.localdate():
            errors["measured_on"] = "Datum měření nemůže být v budoucnosti."
        elif self.animal_id is not None and _before_birth(self.animal, self.measured_on):
            errors["measured_on"] = (
                "Datum měření nemůže být dřívější než datum narození zvířete "
                f"({_czech_date(self.animal.birth_date)})."
            )
        if self.animal_id is not None and self.weight_kg is not None:
            message = weight_error(self.animal.species, self.weight_kg)
            if message:
                errors["weight_kg"] = message
        if self.bcs is not None and not BCS_MIN <= self.bcs <= BCS_MAX:
            errors["bcs"] = "BCS musí být celé číslo 1–9."
        if errors:
            raise ValidationError(errors)


class HealthCondition(models.Model):
    """Catalog of health conditions maintained by the veterinary nutrition specialist.

    Seeded by migration ``0002_seed_health_conditions`` from docs/09 §9.2.
    """

    code = models.SlugField("kód", max_length=50, unique=True)
    name_cs = models.CharField("název", max_length=200)
    description_cs = models.TextField("popis", blank=True)
    mode = models.CharField("úroveň", max_length=15, choices=ConditionMode.choices)
    source_note = models.TextField("zdroj a správa", blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "zdravotní stav (číselník)"
        verbose_name_plural = "zdravotní stavy (číselník)"
        ordering = ["name_cs"]
        constraints = [
            models.CheckConstraint(
                condition=_choices("mode", ConditionMode),
                name="animals_healthcondition_mode_valid",
                violation_error_message="Neplatná úroveň zdravotního stavu.",
            ),
        ]

    def __str__(self) -> str:
        return self.name_cs


class AnimalHealthCondition(models.Model):
    animal = models.ForeignKey(
        Animal, on_delete=models.CASCADE, related_name="conditions", verbose_name="zvíře"
    )
    condition = models.ForeignKey(
        HealthCondition, on_delete=models.PROTECT, related_name="+", verbose_name="zdravotní stav"
    )
    diagnosed_by_vet = models.BooleanField("diagnostikoval veterinární lékař", default=False)
    since = models.DateField("od kdy", null=True, blank=True)
    # Free text from the vet. The application displays it and never interprets it.
    vet_diet_restrictions = models.TextField("omezení stravy podle veterináře", blank=True)
    note = models.TextField("poznámka", blank=True)

    history = HistoricalRecords(cascade_delete_history=True)

    class Meta:
        verbose_name = "zdravotní stav zvířete"
        verbose_name_plural = "zdravotní stavy zvířat"
        ordering = ["condition__name_cs"]
        constraints = [
            models.UniqueConstraint(
                fields=["animal", "condition"],
                name="animals_animalhealthcondition_unique",
                violation_error_message="Tento zdravotní stav už je u zvířete zadaný.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.animal}: {self.condition}"

    def clean(self) -> None:
        """Raises ``ValidationError`` when ``since`` is in the future or before the birth date."""
        if self.since and self.since > timezone.localdate():
            raise ValidationError({"since": "Datum nemůže být v budoucnosti."})
        if self.animal_id is not None and _before_birth(self.animal, self.since):
            raise ValidationError(
                {
                    "since": "Datum nemůže být dřívější než datum narození zvířete "
                    f"({_czech_date(self.animal.birth_date)})."
                }
            )


class AnimalShareQuerySet(models.QuerySet["AnimalShare"]):
    def active(self) -> "AnimalShareQuerySet":
        return self.filter(revoked_at__isnull=True)


class AnimalShare(models.Model):
    """Owner's consent that a vet may see the animal (docs/07 §7.7). Revocable."""

    uuid = models.UUIDField(
        "veřejný identifikátor", default=uuid.uuid4, unique=True, editable=False
    )
    animal = models.ForeignKey(
        Animal, on_delete=models.CASCADE, related_name="shares", verbose_name="zvíře"
    )
    vet = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_animal_shares",
        verbose_name="veterinární lékař",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name="sdílel",
    )
    created_at = models.DateTimeField("sdíleno", auto_now_add=True)
    revoked_at = models.DateTimeField("zrušeno", null=True, blank=True)

    objects = AnimalShareQuerySet.as_manager()
    history = HistoricalRecords(cascade_delete_history=True)

    class Meta:
        verbose_name = "sdílení s veterinářem"
        verbose_name_plural = "sdílení s veterináři"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["animal", "vet"],
                condition=Q(revoked_at__isnull=True),
                name="animals_animalshare_one_active_per_vet",
                violation_error_message="Se zvoleným veterinářem už zvíře sdílíte.",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.animal} → {self.vet}"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def clean(self) -> None:
        """Validate the recipient (also for shares created in the admin).

        Raises:
            ValidationError: the recipient is the animal's owner or is not in the
                ``vet`` group.
        """
        if self.vet_id is None:
            return
        if self.animal_id is not None and self.vet_id == self.animal.owner_id:
            raise ValidationError({"vet": "Zvíře nelze sdílet s jeho majitelem."})
        if not self.vet.has_role(Role.VET):
            raise ValidationError(
                {"vet": "Sdílet lze jen s účtem, který má roli veterinárního lékaře."}
            )
