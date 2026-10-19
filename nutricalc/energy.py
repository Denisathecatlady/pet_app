"""Energetická potřeba zvířete (docs/05).

Rovnice a jejich publikované koeficienty jsou konstanty s odkazem na zdroj
(``docs/zdroje.md``) a stav ověření. Koeficient udržovací potřeby ``k``
(např. 95 nebo 110 u psa) je **data**: předává ho volající jako
:class:`EnergyFactor` se zdrojem a verzí dat (docs/05 §5.0). Jádro žádný
násobitel (kastrace, aktivita) samo nepřidává.

Výstup je vždy odhad (docs/05 §5.0): :func:`estimate_energy` vrací bodový
odhad, rozsah, stav a upozornění, nikdy jen jedno číslo.
"""

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from nutricalc import ENGINE_VERSION
from nutricalc.decimal_ctx import calc_context, to_decimal, to_optional_decimal
from nutricalc.errors import InvalidInputError, SpeciesMismatchError, ValidationError
from nutricalc.flags import Flag, sorted_flags
from nutricalc.vocab import (
    METABOLIC_EXPONENT,
    EnergyStatus,
    PhysiologicalState,
    Species,
    WarningLevel,
    as_member,
    require_text,
)

# --- koeficienty rovnic (docs/05) ------------------------------------------------

# RER = 70 · BW^0,75 [kcal ME/den], psi i kočky:
# [NRC2006] přes [PNA-RER] (docs/05 §5.2), stav ✅ S.
RER_COEFFICIENT: Final = Decimal("70")
RER_EXPONENT: Final = Decimal("0.75")

# Štěňata: ME = 130 · BW^0,75 · 3,2 · (e^(−0,87·p) − 0,1):
# [NRC2006] (docs/05 §5.4), stav ✅ S (ověřit v NRC kap. 15). Mimo MVP.
PUPPY_ME_COEFFICIENT: Final = Decimal("130")
PUPPY_EXPONENT: Final = Decimal("0.75")
PUPPY_GROWTH_FACTOR: Final = Decimal("3.2")
PUPPY_DECAY_RATE: Final = Decimal("0.87")
PUPPY_OFFSET: Final = Decimal("0.1")

# Koťata: ME = 100 · BW^0,67 · 6,7 · (e^(−0,189·p) − 0,66):
# [NRC2006] (docs/05 §5.4, přes Wikivet), stav ✅ S (ověřit v NRC). Mimo MVP.
KITTEN_ME_COEFFICIENT: Final = Decimal("100")
KITTEN_EXPONENT: Final = Decimal("0.67")
KITTEN_GROWTH_FACTOR: Final = Decimal("6.7")
KITTEN_DECAY_RATE: Final = Decimal("0.189")
KITTEN_OFFSET: Final = Decimal("0.66")

# --- technické meze a bezpečnostní politika MVP ------------------------------------

# TECHNICKÉ MEZE VĚROHODNOSTI hmotnosti v kg (včetně mezí). Zachytí překlep
# nebo záměnu jednotky (g místo kg); NEJDE o nutriční data ani o klinické
# meze. Hodnoty potvrdí veterinární nutriční specialista 🛠 🩺.
BODY_WEIGHT_SANITY_RANGE_KG: Final = MappingProxyType(
    {
        Species.DOG: (Decimal("0.5"), Decimal("120")),
        Species.CAT: (Decimal("0.5"), Decimal("15")),
    }
)

# Devítibodová škála BCS: [Laflamme1997d], [Laflamme1997c] (docs/05 §5.3), ✅ B.
BCS_MIN: Final = 1
BCS_MAX: Final = 9

# Bezpečnostní brána MVP pro BCS (docs/09 §9.2, docs/05 §5.3) 🛠 🩺:
# 4–5 bez omezení, 3 a 6–9 vyžaduje posouzení (čísla se spočítají),
# 1–2 automatický výpočet nelze doporučit (bez čísel).
BCS_WITHOUT_RESTRICTION: Final = frozenset({4, 5})
BCS_BLOCKED: Final = frozenset({1, 2})

# Stavy, pro které MVP energii nepočítá (docs/05 §5.4–§5.5, docs/10 §10.3).
UNSUPPORTED_STATES: Final = frozenset(
    {PhysiologicalState.GROWTH, PhysiologicalState.GESTATION, PhysiologicalState.LACTATION}
)


def _positive(value: Decimal | int | str, name: str) -> Decimal:
    number = to_decimal(value, name=name)
    if not number > 0:
        raise InvalidInputError(f"{name} musí být větší než 0 (zadáno {number}).")
    return number


# --- rovnice -----------------------------------------------------------------------


def rer_kcal(body_weight_kg: Decimal | int | str) -> Decimal:
    """Klidová energetická potřeba ``RER = 70 · BW^0,75`` v kcal ME/den.

    Zdroj: [NRC2006] přes [PNA-RER] (docs/05 §5.2), stav ✅ S; platí pro psy
    i kočky. Jen informativně, pro výpočet dávky se nepoužívá.

    Vstup: hmotnost v kg (> 0). Výstup: kcal ME/den v plné přesnosti.
    Chyby: ``TypeError`` pro ``float``;
    :class:`~nutricalc.errors.InvalidInputError` pro hmotnost ≤ 0.
    """
    weight = _positive(body_weight_kg, "Hmotnost (kg)")
    with calc_context():
        return RER_COEFFICIENT * weight**RER_EXPONENT


def mer_kcal(
    body_weight_kg: Decimal | int | str, k: Decimal | int | str, exponent: Decimal | int | str
) -> Decimal:
    """Udržovací energetická potřeba ``MER = k · BW^n`` v kcal ME/den (docs/05 §5.3).

    Vstup: hmotnost v kg (> 0), koeficient ``k`` v kcal ME/kg BW^n (> 0, data
    se zdrojem, viz :class:`EnergyFactor`) a exponent ``n`` (> 0).
    Výstup: kcal ME/den v plné přesnosti.
    Chyby: ``TypeError`` pro ``float``;
    :class:`~nutricalc.errors.InvalidInputError` pro hodnotu ≤ 0.
    """
    weight = _positive(body_weight_kg, "Hmotnost (kg)")
    factor = _positive(k, "Koeficient k")
    power = _positive(exponent, "Exponent metabolické hmotnosti")
    with calc_context():
        return factor * weight**power


def _growth_share(
    body_weight_kg: Decimal | int | str, mature_bw_kg: Decimal | int | str
) -> tuple[Decimal, Decimal]:
    weight = _positive(body_weight_kg, "Hmotnost (kg)")
    mature = _positive(mature_bw_kg, "Očekávaná hmotnost v dospělosti (kg)")
    with calc_context():
        share = weight / mature
    if share > 1:
        raise InvalidInputError(
            f"Hmotnost {weight} kg je vyšší než očekávaná hmotnost v dospělosti {mature} kg "
            "(podíl p > 1). Ověřte oba údaje."
        )
    return weight, share


def nrc_puppy_me_kcal(
    body_weight_kg: Decimal | int | str, mature_bw_kg: Decimal | int | str
) -> Decimal:
    """Energetická potřeba štěněte ``130 · BW^0,75 · 3,2 · (e^(−0,87·p) − 0,1)``.

    Zdroj: [NRC2006] (docs/05 §5.4), stav ✅ S. **Mimo MVP**: funkci
    :func:`estimate_energy` nepoužívá (růst je v MVP blokovaný).

    Vstup: hmotnost a očekávaná hmotnost v dospělosti v kg (obě > 0);
    ``p = BW / BW_m`` musí být nejvýše 1.
    Výstup: kcal ME/den v plné přesnosti.
    Chyby: :class:`~nutricalc.errors.InvalidInputError` pro hmotnost ≤ 0,
    dospělou hmotnost ≤ 0 nebo ``p > 1``.
    """
    weight, share = _growth_share(body_weight_kg, mature_bw_kg)
    with calc_context():
        decay = (-PUPPY_DECAY_RATE * share).exp()
        return (
            PUPPY_ME_COEFFICIENT
            * weight**PUPPY_EXPONENT
            * PUPPY_GROWTH_FACTOR
            * (decay - PUPPY_OFFSET)
        )


def nrc_kitten_me_kcal(
    body_weight_kg: Decimal | int | str, mature_bw_kg: Decimal | int | str
) -> Decimal:
    """Energetická potřeba kotěte ``100 · BW^0,67 · 6,7 · (e^(−0,189·p) − 0,66)``.

    Zdroj: [NRC2006] (docs/05 §5.4), stav ✅ S. **Mimo MVP**: funkci
    :func:`estimate_energy` nepoužívá.

    Vstup, výstup a chyby: jako :func:`nrc_puppy_me_kcal`.
    """
    weight, share = _growth_share(body_weight_kg, mature_bw_kg)
    with calc_context():
        decay = (-KITTEN_DECAY_RATE * share).exp()
        return (
            KITTEN_ME_COEFFICIENT
            * weight**KITTEN_EXPONENT
            * KITTEN_GROWTH_FACTOR
            * (decay - KITTEN_OFFSET)
        )


# --- vstupy a výstup odhadu ----------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class EnergyFactor:
    """Schválený koeficient udržovací potřeby (data, docs/05 §5.3, docs/07 §7.4).

    Pole (jen jako pojmenované argumenty):
        ``species`` – druh, pro který koeficient platí.
        ``situation_code`` – klíč situace (např. kategorie aktivity).
        ``k`` – bodový koeficient v kcal ME/kg BW^n (> 0).
        ``exponent`` – exponent ``n`` (> 0; soulad s druhem kontroluje
        :func:`estimate_energy`).
        ``k_low``, ``k_high`` – volitelné meze rozsahu (``k_low ≤ k ≤ k_high``).
        ``source_key`` – klíč zdroje z ``docs/zdroje.md``.
        ``data_version`` – verze dat (``DataVersion``), ze které koeficient pochází.

    Chyby: ``TypeError`` pro ``float`` nebo jiný typ;
    :class:`~nutricalc.errors.ValidationError` pro koeficient ≤ 0, meze mimo
    pořadí nebo prázdný text.
    """

    species: Species
    situation_code: str
    k: Decimal
    exponent: Decimal
    k_low: Decimal | None = None
    k_high: Decimal | None = None
    source_key: str
    data_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "species", as_member(Species, self.species, "druh koeficientu"))
        require_text(self.situation_code, "EnergyFactor.situation_code")
        require_text(self.source_key, "EnergyFactor.source_key")
        require_text(self.data_version, "EnergyFactor.data_version")
        for name in ("k", "exponent"):
            number = to_decimal(getattr(self, name), name=f"EnergyFactor.{name}")
            if not number > 0:
                raise ValidationError(
                    f"EnergyFactor.{name} musí být větší než 0 (zadáno {number})."
                )
            object.__setattr__(self, name, number)
        for name in ("k_low", "k_high"):
            bound = to_optional_decimal(getattr(self, name), name=f"EnergyFactor.{name}")
            if bound is not None and not bound > 0:
                raise ValidationError(f"EnergyFactor.{name} musí být větší než 0 (zadáno {bound}).")
            object.__setattr__(self, name, bound)
        if self.k_low is not None and self.k_low > self.k:
            raise ValidationError(f"EnergyFactor: k_low {self.k_low} je větší než k {self.k}.")
        if self.k_high is not None and self.k_high < self.k:
            raise ValidationError(f"EnergyFactor: k_high {self.k_high} je menší než k {self.k}.")


@dataclass(frozen=True, kw_only=True)
class EnergyInput:
    """Vstup odhadu energetické potřeby (neměnný snapshot).

    Pole (jen jako pojmenované argumenty):
        ``species`` – druh zvířete.
        ``body_weight_kg`` – **aktuální** hmotnost v kg (``Decimal``, ``int``
        nebo text; nezáporná).
        ``physiological_state`` – fyziologický stav.
        ``bcs`` – BCS na devítibodové škále (``int``) nebo ``None``, pokud není
        známé. Rozsah 1–9 kontroluje :func:`estimate_energy`.
        ``neutered`` – kastrace (``bool``).
        ``factor`` – zvolený koeficient :class:`EnergyFactor` (volbu kategorie,
        např. nižší koeficient u kastrovaných, dělá volající podle schválených
        pravidel).

    Chyby: ``TypeError`` pro nesprávné typy (``float``, ``bool`` místo čísla,
    číslo místo ``bool`` u ``neutered``);
    :class:`~nutricalc.errors.InvalidInputError` pro záporné nebo neplatné číslo.
    """

    species: Species
    body_weight_kg: Decimal
    physiological_state: PhysiologicalState
    bcs: int | None
    neutered: bool
    factor: EnergyFactor

    def __post_init__(self) -> None:
        object.__setattr__(self, "species", as_member(Species, self.species, "druh"))
        object.__setattr__(
            self, "body_weight_kg", to_decimal(self.body_weight_kg, name="Hmotnost (kg)")
        )
        object.__setattr__(
            self,
            "physiological_state",
            as_member(PhysiologicalState, self.physiological_state, "fyziologický stav"),
        )
        if self.bcs is not None and (isinstance(self.bcs, bool) or not isinstance(self.bcs, int)):
            raise TypeError(f"BCS musí být celé číslo 1–9 nebo None, ne {type(self.bcs).__name__}.")
        if not isinstance(self.neutered, bool):
            raise TypeError(f"Údaj o kastraci musí být bool, ne {type(self.neutered).__name__}.")
        if not isinstance(self.factor, EnergyFactor):
            raise TypeError(f"factor musí být EnergyFactor, ne {type(self.factor).__name__}.")


@dataclass(frozen=True, kw_only=True)
class EnergyEstimate:
    """Výsledek odhadu energetické potřeby.

    ``status``: ``OK``, ``EXPERT_REQUIRED`` (čísla jsou spočítaná, ale výsledek
    musí posoudit odborník) nebo ``BLOCKED`` (automatický výpočet nelze
    doporučit; žádná čísla).
    ``kcal_point``, ``kcal_low``, ``kcal_high``: odhad MER v kcal ME/den
    v plné přesnosti (zaokrouhluje se jen při zobrazení); ``None`` při BLOCKED.
    ``rer_kcal``: RER v kcal ME/den (informativně); ``None`` při BLOCKED.
    ``factor``: použitý koeficient (zdroj a verze dat).
    ``flags``: upozornění seřazená podle :func:`~nutricalc.flags.sorted_flags`.
    ``engine_version``: verze jádra.
    """

    status: EnergyStatus
    kcal_point: Decimal | None
    kcal_low: Decimal | None
    kcal_high: Decimal | None
    rer_kcal: Decimal | None
    factor: EnergyFactor
    flags: tuple[Flag, ...]
    engine_version: str


def _check_input(inp: EnergyInput) -> None:
    low, high = BODY_WEIGHT_SANITY_RANGE_KG[inp.species]
    weight = inp.body_weight_kg
    if not weight > 0:
        raise InvalidInputError(f"Hmotnost musí být větší než 0 kg (zadáno {weight}).")
    if not low <= weight <= high:
        raise InvalidInputError(
            f"Hmotnost {weight} kg je mimo technický rozsah věrohodnosti pro druh "
            f"{inp.species} ({low}–{high} kg). Ověřte, zda je hmotnost zadaná v kg."
        )
    if inp.bcs is not None and not BCS_MIN <= inp.bcs <= BCS_MAX:
        raise InvalidInputError(f"BCS {inp.bcs} je mimo devítibodovou škálu {BCS_MIN}–{BCS_MAX}.")
    factor = inp.factor
    if factor.species != inp.species:
        raise SpeciesMismatchError(
            f"Koeficient {factor.situation_code} platí pro druh {factor.species}, zvíře je "
            f"{inp.species}. Zvolte koeficient pro správný druh."
        )
    expected = METABOLIC_EXPONENT[inp.species]
    if factor.exponent != expected:
        raise SpeciesMismatchError(
            f"Koeficient {factor.situation_code} má exponent {factor.exponent}, druh "
            f"{inp.species} vyžaduje {expected}."
        )


def estimate_energy(inp: EnergyInput) -> EnergyEstimate:
    """Odhadne denní energetickou potřebu zvířete (MER = k · BW^n).

    Vstup: :class:`EnergyInput`.

    Pravidla (docs/05 §5.3, docs/09 §9.2):
        - růst, březost a laktace → ``BLOCKED`` s upozorněním
          ``ENERGY_STATE_NOT_SUPPORTED`` (bez čísel; rovnice pro růst se
          v MVP nepoužívají),
        - BCS 1–2 → ``BLOCKED`` (``BCS_SEVERE``, bez čísel),
        - BCS 3 a 6–9 → ``EXPERT_REQUIRED`` (``BCS_OUT_OF_RANGE``), čísla se
          spočítají z aktuální hmotnosti,
        - BCS neznámé → ``INFO`` ``BCS_MISSING``,
        - kastrace → ``INFO`` ``NEUTERED_FACTOR_CHOICE``; žádný násobitel se
          nikdy nepoužije,
        - vždy ``INFO`` ``ENERGY_IS_ESTIMATE``.
        Rozsah: ``kcal_low`` a ``kcal_high`` z ``factor.k_low`` a
        ``factor.k_high``; chybí-li mez, rovná se bodovému odhadu.

    Výstup: :class:`EnergyEstimate`.

    Chyby (výjimky, ne stav výsledku):
        ``TypeError`` pro jiný typ vstupu;
        :class:`~nutricalc.errors.InvalidInputError` pro hmotnost ≤ 0 nebo
        mimo :data:`BODY_WEIGHT_SANITY_RANGE_KG` a pro BCS mimo 1–9;
        :class:`~nutricalc.errors.SpeciesMismatchError`, když koeficient patří
        jinému druhu nebo jeho exponent neodpovídá druhu.
    """
    if not isinstance(inp, EnergyInput):
        raise TypeError(f"estimate_energy očekává EnergyInput, ne {type(inp).__name__}.")
    _check_input(inp)
    flags: list[Flag] = []
    blocked = False
    expert = False
    if inp.physiological_state in UNSUPPORTED_STATES:
        blocked = True
        flags.append(
            Flag(
                WarningLevel.BLOCKED,
                "ENERGY_STATE_NOT_SUPPORTED",
                f"Pro stav {inp.physiological_state} nelze automatický výpočet energie doporučit "
                "(růst, březost a laktace nejsou v této verzi podporovány). Energetickou "
                "potřebu stanoví veterinář.",
            )
        )
    if inp.bcs is None:
        flags.append(
            Flag(
                WarningLevel.INFO,
                "BCS_MISSING",
                "BCS není zadané. Odhad vychází jen z aktuální hmotnosti; doplňte BCS, aby šlo "
                "posoudit, zda je hmotnost vhodná.",
            )
        )
    elif inp.bcs in BCS_BLOCKED:
        blocked = True
        flags.append(
            Flag(
                WarningLevel.BLOCKED,
                "BCS_SEVERE",
                f"BCS {inp.bcs}/9 ukazuje na výraznou podvýživu. Automatický výpočet nelze "
                "doporučit: může jít o onemocnění a hrozí refeeding syndrom. Obraťte se na "
                "veterináře.",
            )
        )
    elif inp.bcs not in BCS_WITHOUT_RESTRICTION:
        expert = True
        flags.append(
            Flag(
                WarningLevel.EXPERT_REQUIRED,
                "BCS_OUT_OF_RANGE",
                f"BCS {inp.bcs}/9 je mimo pásmo 4–5/9. Odhad vychází z aktuální hmotnosti a "
                "neslouží k hubnutí ani přibírání; plán musí posoudit odborník.",
            )
        )
    if inp.neutered:
        flags.append(
            Flag(
                WarningLevel.INFO,
                "NEUTERED_FACTOR_CHOICE",
                "Zvíře je kastrované. Jádro nepoužívá žádný paušální násobitel; zohledněte "
                "kastraci volbou kategorie koeficientu a ověřte odhad podle vývoje hmotnosti.",
            )
        )
    flags.append(
        Flag(
            WarningLevel.INFO,
            "ENERGY_IS_ESTIMATE",
            "Jde o odhad. Upravte množství krmiva podle vývoje hmotnosti a BCS.",
        )
    )
    if blocked:
        return EnergyEstimate(
            status=EnergyStatus.BLOCKED,
            kcal_point=None,
            kcal_low=None,
            kcal_high=None,
            rer_kcal=None,
            factor=inp.factor,
            flags=sorted_flags(flags),
            engine_version=ENGINE_VERSION,
        )
    factor = inp.factor
    weight = inp.body_weight_kg
    point = mer_kcal(weight, factor.k, factor.exponent)
    low = point if factor.k_low is None else mer_kcal(weight, factor.k_low, factor.exponent)
    high = point if factor.k_high is None else mer_kcal(weight, factor.k_high, factor.exponent)
    return EnergyEstimate(
        status=EnergyStatus.EXPERT_REQUIRED if expert else EnergyStatus.OK,
        kcal_point=point,
        kcal_low=low,
        kcal_high=high,
        rer_kcal=rer_kcal(weight),
        factor=factor,
        flags=sorted_flags(flags),
        engine_version=ENGINE_VERSION,
    )
