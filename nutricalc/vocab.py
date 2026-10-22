"""Řízené slovníky výpočetního jádra.

Hodnoty sdílené s balíčkem ``refdata`` (druh, životní fáze, typ požadavku,
báze a jednotky) mají stejné řetězce jako ``refdata.vocab``; jádro ale
``refdata`` neimportuje (shodu hlídá test). Jádro pracuje jen
s kanonickými jednotkami: mezinárodní jednotky (IU) se převádějí už při
importu dat podle ověřeného převodu (docs/06 §6.2).
"""

from collections.abc import Iterable
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from nutricalc.errors import InvalidInputError, ValidationError


class Species(StrEnum):
    """Druh zvířete."""

    DOG = "DOG"
    CAT = "CAT"


class LifeStage(StrEnum):
    """Životní fáze profilu standardu (docs/03 §3.1; stejné hodnoty jako ``refdata``)."""

    ADULT_MAINTENANCE = "ADULT_MAINTENANCE"
    ADULT_MAINTENANCE_LOW = "ADULT_MAINTENANCE_LOW"
    EARLY_GROWTH_REPRO = "EARLY_GROWTH_REPRO"
    LATE_GROWTH = "LATE_GROWTH"
    GROWTH_REPRO = "GROWTH_REPRO"


class PhysiologicalState(StrEnum):
    """Fyziologický stav zvířete pro odhad energie (docs/05 §5.3–§5.5)."""

    MAINTENANCE = "MAINTENANCE"
    GROWTH = "GROWTH"
    GESTATION = "GESTATION"
    LACTATION = "LACTATION"


class RequirementType(StrEnum):
    """Typ požadavku (docs/02 §2.2a; stejné hodnoty jako ``refdata``)."""

    MIN_RECOMMENDED = "MIN_RECOMMENDED"
    MR = "MR"
    AI = "AI"
    RA = "RA"
    NUTRITIONAL_MAX = "NUTRITIONAL_MAX"
    LEGAL_MAX_EU = "LEGAL_MAX_EU"
    SUL = "SUL"
    RATIO_MIN = "RATIO_MIN"
    RATIO_MAX = "RATIO_MAX"


class Basis(StrEnum):
    """Báze vyjádření veličiny (docs/06 §6.2).

    Báze z ``refdata.vocab.Basis`` jsou podmnožinou se stejnými řetězci.
    """

    PER_100G_AS_FED = "PER_100G_AS_FED"
    PER_100G_DM = "PER_100G_DM"
    PER_DAY = "PER_DAY"
    PER_1000KCAL_ME = "PER_1000KCAL_ME"
    PER_MJ_ME = "PER_MJ_ME"
    PER_KG_BW075 = "PER_KG_BW075"
    PER_KG_BW067 = "PER_KG_BW067"


class Unit(StrEnum):
    """Kanonická jednotka veličiny (µg se zapisuje jako ``ug``).

    Oproti ``refdata.vocab.Unit`` chybí IU (převádí se při importu) a
    přibývá kJ (explicitní převod energie).
    """

    G = "g"
    MG = "mg"
    UG = "ug"
    KCAL = "kcal"
    KJ = "kJ"
    RATIO = "ratio"


class ValueKind(StrEnum):
    """Stav hodnoty živiny suroviny (docs/06 §6.5.1)."""

    MEASURED = "MEASURED"
    CALCULATED = "CALCULATED"
    BORROWED = "BORROWED"
    IMPUTED = "IMPUTED"
    BELOW_LOD = "BELOW_LOD"
    TRACE = "TRACE"
    ZERO_BY_DEFINITION = "ZERO_BY_DEFINITION"
    MISSING = "MISSING"


class QualityGrade(StrEnum):
    """Kvalita údaje A–D, A je nejlepší (docs/04, docs/06 §6.6.5)."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Completeness(StrEnum):
    """Úplnost součtu nebo výpočtu (docs/06 §6.5.2)."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class WarningLevel(StrEnum):
    """Úroveň upozornění, od nejmírnější (docs/08, docs/09 §9.2)."""

    INFO = "INFO"
    NUTRITION_WARNING = "NUTRITION_WARNING"
    EXPERT_REQUIRED = "EXPERT_REQUIRED"
    BLOCKED = "BLOCKED"


class EnergyStatus(StrEnum):
    """Stav odhadu energetické potřeby (:func:`nutricalc.energy.estimate_energy`)."""

    OK = "OK"
    EXPERT_REQUIRED = "EXPERT_REQUIRED"
    BLOCKED = "BLOCKED"


class GateStatus(StrEnum):
    """Stav bezpečnostní brány rozboru (docs/09 §9.2, :mod:`nutricalc.gate`)."""

    OK = "OK"
    EXPERT_REQUIRED = "EXPERT_REQUIRED"
    BLOCKED = "BLOCKED"


class MeMethod(StrEnum):
    """Metoda výpočtu metabolizovatelné energie krmiva (docs/06 §6.3)."""

    NRC2006_DOG_CF = "NRC2006_DOG_CF"
    NRC2006_DOG_TDF = "NRC2006_DOG_TDF"
    MOD_ATWATER = "MOD_ATWATER"
    NRC2006_CAT = "NRC2006_CAT"


class DataScope(StrEnum):
    """Oblast verze referenčních dat (``DataVersion.scope``, docs/07 §7.4)."""

    INGREDIENTS = "INGREDIENTS"
    STANDARDS = "STANDARDS"
    ENERGY = "ENERGY"
    RULES = "RULES"


# Exponent metabolické hmotnosti: pes BW^0,75, kočka BW^0,67
# ([FEDIAF2025], docs/05 §5.1, docs/03 §3.3), stav ✅ S.
METABOLIC_EXPONENT: Final = MappingProxyType(
    {Species.DOG: Decimal("0.75"), Species.CAT: Decimal("0.67")}
)

METABOLIC_BASIS: Final = MappingProxyType(
    {Species.DOG: Basis.PER_KG_BW075, Species.CAT: Basis.PER_KG_BW067}
)
"""Báze „na kg metabolické hmotnosti“ podle druhu (docs/06 §6.2)."""

MINIMUM_TYPES: Final = frozenset(
    {
        RequirementType.MIN_RECOMMENDED,
        RequirementType.MR,
        RequirementType.AI,
        RequirementType.RA,
    }
)
"""Typy požadavku, které se vyhodnocují jako minimum."""

MAXIMUM_TYPES: Final = frozenset(
    {
        RequirementType.NUTRITIONAL_MAX,
        RequirementType.LEGAL_MAX_EU,
        RequirementType.SUL,
    }
)
"""Typy požadavku, které se vyhodnocují jako maximum."""

RATIO_TYPES: Final = frozenset({RequirementType.RATIO_MIN, RequirementType.RATIO_MAX})
"""Typy požadavku pro poměry (např. Ca:P)."""

QUALITY_RANK: Final = MappingProxyType(
    {QualityGrade.A: 0, QualityGrade.B: 1, QualityGrade.C: 2, QualityGrade.D: 3}
)
"""Pořadí kvality: vyšší číslo = horší údaj."""

WARNING_LEVEL_RANK: Final = MappingProxyType(
    {
        WarningLevel.INFO: 0,
        WarningLevel.NUTRITION_WARNING: 1,
        WarningLevel.EXPERT_REQUIRED: 2,
        WarningLevel.BLOCKED: 3,
    }
)
"""Pořadí závažnosti upozornění: vyšší číslo = závažnější."""

BASIS_LABELS: Final = MappingProxyType(
    {
        Basis.PER_100G_AS_FED: "na 100 g původní hmoty",
        Basis.PER_100G_DM: "na 100 g sušiny",
        Basis.PER_DAY: "na den",
        Basis.PER_1000KCAL_ME: "na 1000 kcal ME",
        Basis.PER_MJ_ME: "na MJ ME",
        Basis.PER_KG_BW075: "na kg BW^0.75",
        Basis.PER_KG_BW067: "na kg BW^0.67",
    }
)
"""České popisy bází pro zprávy."""

SPECIES_LABELS: Final = MappingProxyType({Species.DOG: "pes", Species.CAT: "kočka"})
"""České názvy druhů pro zprávy."""

LIFE_STAGE_LABELS: Final = MappingProxyType(
    {
        LifeStage.ADULT_MAINTENANCE: "dospělý, udržovací potřeba",
        LifeStage.ADULT_MAINTENANCE_LOW: "dospělý, nízká potřeba energie",
        LifeStage.EARLY_GROWTH_REPRO: "časný růst a reprodukce",
        LifeStage.LATE_GROWTH: "pozdní růst",
        LifeStage.GROWTH_REPRO: "růst a reprodukce",
    }
)
"""České popisy životních fází profilu standardu pro zprávy (docs/03 §3.1)."""


def as_member[E: StrEnum](enum_type: type[E], value: object, label: str) -> E:
    """Vrátí člen slovníku pro člen nebo jeho textovou hodnotu.

    Vstup: třída slovníku, hodnota (člen nebo text, např. ``"DOG"``) a český
    název údaje pro zprávu.
    Výstup: člen ``enum_type``.
    Chyby: ``TypeError``, pokud hodnota není text;
    :class:`~nutricalc.errors.InvalidInputError` pro neznámou hodnotu.
    """
    if isinstance(value, enum_type):
        return value
    if not isinstance(value, str):
        raise TypeError(
            f"{label}: očekává se text nebo {enum_type.__name__}, ne {type(value).__name__}."
        )
    try:
        return enum_type(value)
    except ValueError:
        allowed = ", ".join(member.value for member in enum_type)
        raise InvalidInputError(
            f"{label}: neznámá hodnota „{value}“. Povolené hodnoty: {allowed}."
        ) from None


def require_text(value: object, label: str) -> str:
    """Ověří, že údaj je neprázdný text (kód, identifikátor, zdroj).

    Vstup: hodnota a český název údaje pro zprávu. Výstup: stejný text.
    Chyby: ``TypeError``, pokud hodnota není text;
    :class:`~nutricalc.errors.ValidationError` pro prázdný text nebo jen mezery.
    """
    if not isinstance(value, str):
        raise TypeError(f"{label} musí být text, ne {type(value).__name__}.")
    if not value.strip():
        raise ValidationError(f"{label} nesmí být prázdné.")
    return value


def worst_quality(grades: Iterable[QualityGrade]) -> QualityGrade | None:
    """Vrátí nejhorší kvalitu údajů.

    Vstup: kvality (může být prázdné). Výstup: nejhorší kvalita, nebo
    ``None`` pro prázdný vstup.
    """
    ordered = sorted(grades, key=QUALITY_RANK.__getitem__)
    return ordered[-1] if ordered else None
