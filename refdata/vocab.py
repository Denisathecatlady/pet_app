"""Řízené slovníky a převodní konstanty pro přepis tabulek standardů.

Hodnoty slovníků odpovídají návrhu schématu (docs/07 §7.4) a šabloně
``data/reference/standard_import_template.csv``. Konstanty nesou v komentáři
zdroj; nejde o nutriční požadavky, ale o převodní a referenční údaje,
které jsou v dokumentaci Fáze 1 ověřené.
"""

from decimal import Decimal, localcontext
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from refdata.decimal_utils import DECIMAL_CONTEXT


class Species(StrEnum):
    """Druh zvířete."""

    DOG = "DOG"
    CAT = "CAT"


class LifeStage(StrEnum):
    """Životní fáze profilu standardu (docs/03 §3.1)."""

    ADULT_MAINTENANCE = "ADULT_MAINTENANCE"
    ADULT_MAINTENANCE_LOW = "ADULT_MAINTENANCE_LOW"
    EARLY_GROWTH_REPRO = "EARLY_GROWTH_REPRO"
    LATE_GROWTH = "LATE_GROWTH"
    GROWTH_REPRO = "GROWTH_REPRO"


class RequirementType(StrEnum):
    """Typ požadavku (docs/02 §2.2a, docs/07 §7.4)."""

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
    """Báze vyjádření požadavku.

    FEDIAF uvádí hodnoty na 100 g sušiny, na 1 000 kcal ME a na MJ ME
    (docs/02 §2.1); báze na kg metabolické hmotnosti viz docs/06 §6.2.
    """

    PER_100G_DM = "PER_100G_DM"
    PER_1000KCAL_ME = "PER_1000KCAL_ME"
    PER_MJ_ME = "PER_MJ_ME"
    PER_KG_BW075 = "PER_KG_BW075"
    PER_KG_BW067 = "PER_KG_BW067"


class Unit(StrEnum):
    """Jednotka hodnoty v přepisu (µg se zapisuje jako ``ug``)."""

    G = "g"
    MG = "mg"
    UG = "ug"
    KCAL = "kcal"
    IU = "IU"
    RATIO = "ratio"


# Exponent metabolické hmotnosti: pes BW^0,75, kočka BW^0,67
# ([FEDIAF2025], docs/03 §3.1 a §3.3, docs/zdroje.md).
METABOLIC_EXPONENT: Final = MappingProxyType(
    {Species.DOG: Decimal("0.75"), Species.CAT: Decimal("0.67")}
)

LIFE_STAGES: Final = MappingProxyType(
    {
        Species.DOG: frozenset(
            {
                LifeStage.ADULT_MAINTENANCE,
                LifeStage.ADULT_MAINTENANCE_LOW,
                LifeStage.EARLY_GROWTH_REPRO,
                LifeStage.LATE_GROWTH,
            }
        ),
        Species.CAT: frozenset(
            {
                LifeStage.ADULT_MAINTENANCE,
                LifeStage.ADULT_MAINTENANCE_LOW,
                LifeStage.GROWTH_REPRO,
            }
        ),
    }
)
"""Platné životní fáze pro každý druh (docs/03 §3.1)."""

ADULT_STAGES: Final = frozenset({LifeStage.ADULT_MAINTENANCE, LifeStage.ADULT_MAINTENANCE_LOW})
"""Fáze, které musí mít vyplněnou referenční energii ``reference_energy_k``."""

MINIMUM_TYPES: Final = frozenset(
    {
        RequirementType.MIN_RECOMMENDED,
        RequirementType.MR,
        RequirementType.AI,
        RequirementType.RA,
    }
)
MAXIMUM_TYPES: Final = frozenset(
    {
        RequirementType.NUTRITIONAL_MAX,
        RequirementType.LEGAL_MAX_EU,
        RequirementType.SUL,
    }
)
RATIO_TYPES: Final = frozenset({RequirementType.RATIO_MIN, RequirementType.RATIO_MAX})

BASIS_ONLY_FOR_SPECIES: Final = MappingProxyType(
    {Basis.PER_KG_BW075: Species.DOG, Basis.PER_KG_BW067: Species.CAT}
)
"""Báze vázané na exponent metabolické hmotnosti jednoho druhu."""

BASIS_LABELS: Final = MappingProxyType(
    {
        Basis.PER_100G_DM: "na 100 g sušiny",
        Basis.PER_1000KCAL_ME: "na 1000 kcal ME",
        Basis.PER_MJ_ME: "na MJ ME",
        Basis.PER_KG_BW075: "na kg BW^0.75",
        Basis.PER_KG_BW067: "na kg BW^0.67",
    }
)
"""České popisy bází pro zprávy nálezů."""

CANONICAL_UNITS: Final = frozenset(Unit) - {Unit.IU}
"""Jednotky, které smí být kanonickou jednotkou živiny v katalogu (docs/06 §6.2)."""

ENERGY_NUTRIENT: Final = "ENERGY_ME"
"""Jediná živina, u které je povolena jednotka kcal."""

RATIO_CATEGORY: Final = "RATIO"
"""Kategorie katalogu pro poměrové živiny (např. ``CA_P``)."""

# FEDIAF předpokládá energetickou hustotu 4 000 kcal ME/kg sušiny
# (docs/03 §3.3 a §3.5, stav ✅ S: [FEDIAF2025] přes sekundární zdroj).
KCAL_PER_KG_DM: Final = Decimal("4000")

# 1 kcal = 4,184 kJ (termochemická kalorie; docs/03 §3.5, docs/11 §11.2).
KJ_PER_KCAL: Final = Decimal("4.184")


def _dm_to_1000kcal_factor() -> Decimal:
    # 100 g sušiny nese KCAL_PER_KG_DM / 10 kcal, tedy hodnota na 1000 kcal
    # = hodnota na 100 g DM × 1000 / 400 = × 2,5 (docs/03 §3.3 a §3.5).
    with localcontext(DECIMAL_CONTEXT):
        return Decimal(1000) / (KCAL_PER_KG_DM / Decimal(10))


DM_TO_1000KCAL_FACTOR: Final = _dm_to_1000kcal_factor()

# 1000 kcal = 4184 kJ = 4,184 MJ, tedy hodnota na 1000 kcal
# = hodnota na MJ × 4,184 (docs/03 §3.5).
MJ_TO_1000KCAL_FACTOR: Final = KJ_PER_KCAL

# Referenční energie (k_low, k_high) v kcal ME/kg BW^n. Pro požadavky typu
# minimum se očekává hodnota(k_low) = hodnota(k_high) × k_high / k_low,
# pokud tabulka vznikla přepočtem (docs/02 §2.2b, docs/03 §3.3 a §3.5).
SCALED_PAIRS: Final = MappingProxyType(
    {
        Species.DOG: (Decimal("95"), Decimal("110")),
        Species.CAT: (Decimal("75"), Decimal("100")),
    }
)

# Mezinárodní jednotky se připouštějí jen u vitaminů A, D a E; převod se
# převezme z přílohy standardu jako ověřený záznam (docs/06 §6.2).
IU_ALLOWED_NUTRIENTS: Final = frozenset({"VIT_A", "VIT_D", "VIT_E"})

# Slovo v poznámce (note), kterým přepisovatel potvrzuje, že nekonzistentní
# hodnoty jsou v originále vytištěny přesně takto. Platí jen jako samostatné
# slovo, ne jako část delšího (docs/postup-prepisu-standardu.md §8).
CONFIRM_TOKEN: Final = "CONFIRMED_AS_PRINTED"
