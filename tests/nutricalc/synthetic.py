"""SYNTETICKÉ testovací fixtury pro ``nutricalc``.

Suroviny ``SYN_*`` a standard ``TESTSTD`` jsou smyšlené. Nejde o reálné
suroviny, reálné složení ani o požadavky FEDIAF, NRC či AAFCO. Jediná reálná
čísla v testech jsou kontrolní příklady z docs/05 §5.8 (koeficienty
k = 95, 110, 75, 100 a hmotnosti), příklady z docs/06 §6.3 a §6.10
(SYN_A, SYN_B) a publikované koeficienty rovnic.
"""

from collections.abc import Iterable, Mapping
from decimal import Decimal

from nutricalc import ENGINE_VERSION
from nutricalc.composition import IngredientProfile, NutrientValue, RecipeItem
from nutricalc.energy import EnergyFactor, EnergyInput
from nutricalc.requirements import Requirement, StandardProfile
from nutricalc.snapshot import AnalysisInput, AnimalSnapshot
from nutricalc.vocab import (
    RATIO_TYPES,
    Basis,
    LifeStage,
    MeMethod,
    PhysiologicalState,
    QualityGrade,
    RequirementType,
    Species,
    Unit,
    ValueKind,
)

QUALITY = QualityGrade.B
TOLERANCE_KCAL = Decimal("1e-6")


def measured(value: str, **extra: str) -> NutrientValue:
    """Naměřená syntetická hodnota (volitelně value_min/value_max jako text)."""
    bounds = {name: Decimal(text) for name, text in extra.items()}
    return NutrientValue(Decimal(value), ValueKind.MEASURED, quality=QUALITY, **bounds)


def zero() -> NutrientValue:
    """Hodnota ZERO_BY_DEFINITION."""
    return NutrientValue(Decimal(0), ValueKind.ZERO_BY_DEFINITION, quality=QUALITY)


def below_lod(lod: str | None = None) -> NutrientValue:
    """Hodnota BELOW_LOD s volitelnou mezí detekce."""
    return NutrientValue(
        None, ValueKind.BELOW_LOD, lod=None if lod is None else Decimal(lod), quality=QUALITY
    )


def missing() -> NutrientValue:
    """Výslovně chybějící hodnota."""
    return NutrientValue(None, ValueKind.MISSING, quality=QualityGrade.D)


def profile(
    code: str,
    values: Mapping[str, NutrientValue],
    category: str = "TEST",
    safety_flags: Iterable[str] = (),
) -> IngredientProfile:
    """Syntetický profil suroviny ``code`` (verze ``test-1``)."""
    return IngredientProfile(
        code, f"{code}@test-1", category, frozenset(safety_flags), dict(values)
    )


def item(source: IngredientProfile, grams: str) -> RecipeItem:
    """Položka receptu se zadanými gramy (text → Decimal)."""
    return RecipeItem(source, Decimal(grams))


# docs/06 §6.3 a §6.10: SYN_A = B 20 g, T 10 g, BNLV 0, V 0 na 100 g; P 0,200 g; Ca chybí.
def syn_a(ca: NutrientValue | None = None) -> IngredientProfile:
    values = {
        "PROTEIN": measured("20"),
        "FAT": measured("10"),
        "NFE": zero(),
        "CRUDE_FIBRE": zero(),
        "P": measured("0.200"),
    }
    if ca is not None:
        values["CA"] = ca
    return profile("SYN_A", values)


# docs/06 §6.10: SYN_B (minerální) = B 0, T 0, P 5,0 g, Ca 10,0 g na 100 g.
def syn_b() -> IngredientProfile:
    return profile(
        "SYN_B",
        {
            "PROTEIN": zero(),
            "FAT": zero(),
            "NFE": zero(),
            "CRUDE_FIBRE": zero(),
            "P": measured("5.0"),
            "CA": measured("10.0"),
        },
    )


def dog_factor(k: str = "110", **bounds: str) -> EnergyFactor:
    """Koeficient pro psa; k z docs/05 §5.8, meze k_low/k_high jako text."""
    return EnergyFactor(
        species=Species.DOG,
        situation_code="TEST_DOG",
        k=Decimal(k),
        exponent=Decimal("0.75"),
        source_key="TEST_FIXTURE",
        data_version="test-1",
        **{name: Decimal(text) for name, text in bounds.items()},
    )


def cat_factor(k: str = "100", **bounds: str) -> EnergyFactor:
    """Koeficient pro kočku; k z docs/05 §5.8."""
    return EnergyFactor(
        species=Species.CAT,
        situation_code="TEST_CAT",
        k=Decimal(k),
        exponent=Decimal("0.67"),
        source_key="TEST_FIXTURE",
        data_version="test-1",
        **{name: Decimal(text) for name, text in bounds.items()},
    )


def energy_input(**overrides: object) -> EnergyInput:
    """Vstup odhadu energie: dospělý pes 20 kg, BCS 5, k = 110 (docs/05 §5.8)."""
    fields: dict[str, object] = {
        "species": Species.DOG,
        "body_weight_kg": Decimal(20),
        "physiological_state": PhysiologicalState.MAINTENANCE,
        "bcs": 5,
        "neutered": False,
        "factor": dog_factor(),
    }
    fields.update(overrides)
    return EnergyInput(**fields)  # type: ignore[arg-type]


def close(actual: Decimal | None, expected: str, tolerance: Decimal = TOLERANCE_KCAL) -> bool:
    """Shoda s očekávanou hodnotou v toleranci (výchozí 1e-6, docs/05 §5.8)."""
    return actual is not None and abs(actual - Decimal(expected)) <= tolerance


# --- SYNTETICKÝ standard TESTSTD ------------------------------------------------------------
#
# Všechny hodnoty požadavků níže jsou SMYŠLENÉ testovací fixtury (záměrně „nekulatá“
# čísla). Nejde o požadavky FEDIAF, NRC ani AAFCO. Referenční energie sloupců
# (110/95 pro psa, 100/75 pro kočku) jsou kontrolní koeficienty z docs/05 §5.8.

TESTSTD = "TESTSTD"
TESTSTD_VERSION = "teststd-1"
INGREDIENTS_VERSION = "syn-1"
RULES_VERSION = "rules-test-1"
ENERGY_VERSION = "test-1"
SYN_THRESHOLD = Decimal("0.1")
"""Syntetický práh spolehlivosti (podíl), ne odborně stanovená hodnota."""

REFERENCE_K = {
    Species.DOG: (Decimal(110), Decimal(95)),
    Species.CAT: (Decimal(100), Decimal(75)),
}
EXPONENT = {Species.DOG: Decimal("0.75"), Species.CAT: Decimal("0.67")}


def req(
    code: str,
    kind: RequirementType | str,
    value: str,
    unit: Unit | str | None = None,
    condition_note: str = "",
) -> Requirement:
    """Syntetický požadavek na 1000 kcal ME (jednotka g, u poměru ratio)."""
    member = RequirementType(kind)
    if unit is None:
        unit = Unit.RATIO if member in RATIO_TYPES else Unit.G
    return Requirement(
        nutrient_code=code,
        requirement_type=member,
        value=Decimal(value),
        unit=Unit(unit),
        basis=Basis.PER_1000KCAL_ME,
        condition_note=condition_note,
        source_key="TEST_FIXTURE",
    )


def std_requirements(column: str = "high") -> list[Requirement]:
    """Výchozí SYNTETICKÉ požadavky TESTSTD pro vyšší (``high``) nebo nižší (``low``) sloupec."""
    minima = (
        {"PROTEIN": "55.555", "CA": "3.333", "P": "4.321"}
        if column == "high"
        else {"PROTEIN": "64.321", "CA": "3.859", "P": "5.003"}
    )
    return [
        *(req(code, RequirementType.MIN_RECOMMENDED, value) for code, value in minima.items()),
        req("P", RequirementType.NUTRITIONAL_MAX, "7.777"),
        req("CA_P", RequirementType.RATIO_MIN, "1.234"),
        req("CA_P", RequirementType.RATIO_MAX, "1.615"),
    ]


DEFAULT_MANDATORY = frozenset({"PROTEIN", "CA", "P"})


def std_profile(
    column: str = "high",
    species: Species = Species.DOG,
    requirements: Iterable[Requirement] | None = None,
    mandatory: Iterable[str] = DEFAULT_MANDATORY,
    **overrides: object,
) -> StandardProfile:
    """Syntetický sloupec TESTSTD (vydání 1) pro druh a sloupec ``high``/``low``."""
    high_k, low_k = REFERENCE_K[species]
    fields: dict[str, object] = {
        "standard_code": TESTSTD,
        "edition": "1",
        "species": species,
        "life_stage": (
            LifeStage.ADULT_MAINTENANCE if column == "high" else LifeStage.ADULT_MAINTENANCE_LOW
        ),
        "reference_k": high_k if column == "high" else low_k,
        "exponent": EXPONENT[species],
        "requirements": tuple(std_requirements(column) if requirements is None else requirements),
        "mandatory_nutrients": frozenset(mandatory),
        "data_version": TESTSTD_VERSION,
    }
    fields.update(overrides)
    return StandardProfile(**fields)  # type: ignore[arg-type]


def std_pair(
    species: Species = Species.DOG,
    high: Iterable[Requirement] | None = None,
    low: Iterable[Requirement] | None = None,
    mandatory: Iterable[str] = DEFAULT_MANDATORY,
) -> tuple[StandardProfile, StandardProfile]:
    """Dvojice syntetických sloupců TESTSTD (vyšší, nižší)."""
    return (
        std_profile("high", species, high, mandatory),
        std_profile("low", species, low, mandatory),
    )


def animal(**overrides: object) -> AnimalSnapshot:
    """Zvíře pro rozbor: dospělý pes 20 kg, BCS 5, nekastrovaný (docs/05 §5.8)."""
    fields: dict[str, object] = {
        "species": Species.DOG,
        "body_weight_kg": Decimal(20),
        "physiological_state": PhysiologicalState.MAINTENANCE,
        "life_stage": LifeStage.ADULT_MAINTENANCE,
        "bcs": 5,
        "neutered": False,
    }
    fields.update(overrides)
    return AnimalSnapshot(**fields)  # type: ignore[arg-type]


def golden_items(ca: NutrientValue | None = None) -> tuple[RecipeItem, ...]:
    """Recept z docs/06 §6.10: SYN_A 300 g a SYN_B 50 g."""
    return (item(syn_a(ca), "300"), item(syn_b(), "50"))


def analysis_input(**overrides: object) -> AnalysisInput:
    """Vstup rozboru: příklad docs/06 §6.10 se syntetickým standardem TESTSTD."""
    high, low = std_pair()
    fields: dict[str, object] = {
        "animal": animal(),
        "items": golden_items(),
        "energy_factor": dog_factor(),
        "high_profile": high,
        "low_profile": low,
        "me_method": MeMethod.NRC2006_DOG_CF,
        "warning_rules": (),
        "confidence_threshold": SYN_THRESHOLD,
        "data_versions": (
            ("INGREDIENTS", INGREDIENTS_VERSION),
            ("STANDARDS", TESTSTD_VERSION),
            ("ENERGY", ENERGY_VERSION),
        ),
        "engine_version": ENGINE_VERSION,
    }
    fields.update(overrides)
    return AnalysisInput(**fields)  # type: ignore[arg-type]
