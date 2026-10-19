"""Porovnání živin s požadavky, poměr Ca:P, spolehlivost a souhrn (docs/06 §6.6).

Porovnává se vždy **nezaokrouhlená** hodnota; zaokrouhluje se jen při
zobrazení (:func:`format_coverage`). Chybějící údaj se nikdy nepovažuje za
nulu: součet ``PARTIAL`` má jen dolní mez a ``UNKNOWN`` se nevyhodnocuje
(docs/06 §6.5). Požadavek typu maximum se nikdy nepoužije jako minimum a
naopak; poměrové požadavky patří jen do :func:`evaluate_ratio`.

Hodnoty požadavků, prahy (např. práh spolehlivosti) a pravidla jsou data,
která předává volající; tento modul žádné nutriční hodnoty neobsahuje.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Final, NamedTuple

from nutricalc.composition import NutrientTotal
from nutricalc.decimal_ctx import CALC_PRECISION, calc_context, to_decimal
from nutricalc.errors import (
    BasisMismatchError,
    InvalidInputError,
    UnitMismatchError,
    ValidationError,
)
from nutricalc.requirements import Requirement, StandardProfile, check_requirement_set
from nutricalc.units import Quantity, per_day_to_per_1000kcal
from nutricalc.vocab import (
    LIFE_STAGE_LABELS,
    MAXIMUM_TYPES,
    SPECIES_LABELS,
    Basis,
    Completeness,
    GateStatus,
    QualityGrade,
    RequirementType,
    Unit,
    as_member,
    require_text,
    worst_quality,
)

CALCIUM: Final = "CA"
PHOSPHORUS: Final = "P"
CA_P: Final = "CA_P"
"""Kódy živin z ``data/reference/nutrients.csv``."""

RATIO_COMPONENTS: Final = MappingProxyType({CA_P: (CALCIUM, PHOSPHORUS)})
"""Poměr → (čitatel, jmenovatel). Hlídá záměnu Ca a P (docs/06 §6.6.3)."""

_ZERO: Final = Decimal(0)
_HUNDRED: Final = Decimal(100)


class NutrientStatus(StrEnum):
    """Stav živiny po porovnání se standardem (docs/06 §6.6.1)."""

    BELOW_MIN = "BELOW_MIN"
    BORDERLINE_MIN = "BORDERLINE_MIN"
    ADEQUATE = "ADEQUATE"
    MIN_MET_PARTIAL = "MIN_MET_PARTIAL"
    ABOVE_MAX = "ABOVE_MAX"
    BORDERLINE_MAX = "BORDERLINE_MAX"
    ABOVE_LEGAL_MAX_INFO = "ABOVE_LEGAL_MAX_INFO"
    ABOVE_SUL = "ABOVE_SUL"
    NOT_EVALUABLE = "NOT_EVALUABLE"
    NO_REFERENCE = "NO_REFERENCE"


STATUS_PRIORITY: Final = (
    NutrientStatus.ABOVE_MAX,
    NutrientStatus.ABOVE_SUL,
    NutrientStatus.BELOW_MIN,
    NutrientStatus.BORDERLINE_MIN,
    NutrientStatus.BORDERLINE_MAX,
    NutrientStatus.NOT_EVALUABLE,
    NutrientStatus.MIN_MET_PARTIAL,
    NutrientStatus.ABOVE_LEGAL_MAX_INFO,
    NutrientStatus.ADEQUATE,
    NutrientStatus.NO_REFERENCE,
)
"""Pořadí stavů od nejzávažnějšího; první přítomný stav je hlavní stav živiny."""

_PRIORITY_INDEX: Final = MappingProxyType(
    {status: index for index, status in enumerate(STATUS_PRIORITY)}
)

STATUS_LABELS: Final = MappingProxyType(
    {
        NutrientStatus.BELOW_MIN: "Pod minimem",
        NutrientStatus.BORDERLINE_MIN: "Na hranici minima (v rozsahu nejistoty)",
        NutrientStatus.ADEQUATE: "V rozmezí standardu",
        NutrientStatus.MIN_MET_PARTIAL: (
            "Minimum splněno i bez chybějících dat. Maximum nelze ověřit"
        ),
        NutrientStatus.ABOVE_MAX: "Překročeno nutriční maximum",
        NutrientStatus.BORDERLINE_MAX: "Na hranici maxima",
        NutrientStatus.ABOVE_LEGAL_MAX_INFO: (
            "Informativně: nad zákonným limitem pro komerční krmiva"
        ),
        NutrientStatus.ABOVE_SUL: "Nad bezpečným horním limitem",
        NutrientStatus.NOT_EVALUABLE: "Nelze vyhodnotit – chybí data",
        NutrientStatus.NO_REFERENCE: "Standard nestanovuje",
    }
)
"""České texty stavů pro UI (docs/06 §6.6.1)."""

DEFICIT_OR_EXCESS_STATUSES: Final = frozenset(
    {NutrientStatus.BELOW_MIN, NutrientStatus.ABOVE_MAX, NutrientStatus.ABOVE_SUL}
)
BORDERLINE_STATUSES: Final = frozenset(
    {NutrientStatus.BORDERLINE_MIN, NutrientStatus.BORDERLINE_MAX}
)


def ordered_statuses(statuses: Iterable[NutrientStatus]) -> tuple[NutrientStatus, ...]:
    """Seřadí stavy podle :data:`STATUS_PRIORITY` (bez duplicit)."""
    return tuple(sorted(set(statuses), key=_PRIORITY_INDEX.__getitem__))


# --- hodnota živiny na 1000 kcal ------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class NutrientInterval:
    """Obsah živiny jako interval s úplností (obvykle na 1000 kcal ME).

    Pole (jen jako pojmenované argumenty):
        ``nutrient_code``, ``unit`` (kanonická jednotka), ``basis``.
        ``lower`` – dolní mez (≥ 0). U ``PARTIAL`` je to jen dolní mez přes
        známé suroviny, u ``UNKNOWN`` nemá význam obsahu (chybějící údaj ≠ 0).
        ``upper`` – horní mez; povinná u ``COMPLETE`` (``lower ≤ upper``),
        jinak ``None``.
        ``point`` – bodová hodnota, nebo ``None``; jen u ``COMPLETE`` a uvnitř
        intervalu.
        ``completeness`` – :class:`~nutricalc.vocab.Completeness`.

    Chyby: ``TypeError`` pro ``float``; :class:`~nutricalc.errors.ValidationError`
    pro rozporné meze nebo úplnost.
    """

    nutrient_code: str
    unit: Unit
    basis: Basis
    lower: Decimal
    upper: Decimal | None
    point: Decimal | None
    completeness: Completeness

    def __post_init__(self) -> None:
        code = require_text(self.nutrient_code, "NutrientInterval.nutrient_code")
        object.__setattr__(self, "unit", as_member(Unit, self.unit, "jednotka"))
        object.__setattr__(self, "basis", as_member(Basis, self.basis, "báze"))
        completeness = as_member(Completeness, self.completeness, "úplnost")
        object.__setattr__(self, "completeness", completeness)
        lower = to_decimal(self.lower, name=f"Dolní mez {code}")
        object.__setattr__(self, "lower", lower)
        if completeness == Completeness.COMPLETE:
            if self.upper is None:
                raise ValidationError(f"Úplný (COMPLETE) obsah {code} musí mít horní mez.")
            upper = to_decimal(self.upper, name=f"Horní mez {code}")
            if upper < lower:
                raise ValidationError(f"Horní mez {code} {upper} je menší než dolní mez {lower}.")
            object.__setattr__(self, "upper", upper)
            if self.point is not None:
                point = to_decimal(self.point, name=f"Bodová hodnota {code}")
                if not lower <= point <= upper:
                    raise ValidationError(
                        f"Bodová hodnota {code} {point} leží mimo interval [{lower}; {upper}]."
                    )
                object.__setattr__(self, "point", point)
        elif self.upper is not None or self.point is not None:
            raise ValidationError(
                f"Obsah {code} ve stavu {completeness} nesmí mít horní mez ani bodovou hodnotu "
                "(chybějící údaj nelze odhadnout)."
            )


def per_1000kcal_interval(
    total: NutrientTotal, me_kcal_per_day: Decimal | int | str
) -> NutrientInterval:
    """Převede denní součet živiny na interval na 1000 kcal ME (docs/06 §6.2).

    ``x_1000 = x_den / (ME_den / 1000)`` pro každou mez i bodovou hodnotu.

    Vstup: :class:`~nutricalc.composition.NutrientTotal` (na den) a ME dávky
    v kcal/den (> 0).
    Výstup: :class:`NutrientInterval` s bází ``PER_1000KCAL_ME``; úplnost se
    nemění.
    Chyby: ``TypeError`` pro jiný typ;
    :class:`~nutricalc.errors.ValidationError` pro ME ≤ 0.
    """
    if not isinstance(total, NutrientTotal):
        raise TypeError(f"per_1000kcal_interval očekává NutrientTotal, ne {type(total).__name__}.")

    def convert(quantity: Quantity | None) -> Decimal | None:
        if quantity is None:
            return None
        return per_day_to_per_1000kcal(quantity, me_kcal_per_day).value

    lower = convert(total.lower_quantity())
    return NutrientInterval(
        nutrient_code=total.nutrient_code,
        unit=total.unit,
        basis=Basis.PER_1000KCAL_ME,
        lower=lower if lower is not None else _ZERO,
        upper=convert(total.upper_quantity()),
        point=convert(total.point_quantity()),
        completeness=total.completeness,
    )


# --- vyhodnocení živiny --------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class NutrientEvaluation:
    """Výsledek porovnání jedné živiny s požadavky (docs/06 §6.6).

    ``status`` – hlavní stav (první podle :data:`STATUS_PRIORITY`).
    ``all_statuses`` – všechny zjištěné stavy v pořadí :data:`STATUS_PRIORITY`.
    ``coverage_low_pct``, ``coverage_high_pct`` – pokrytí minima v % (dolní
    a horní mez obsahu / minimum · 100). Jen pro požadavek typu minimum a jen
    tam, kde je číslo podložené daty: ``COMPLETE`` (obě meze) a
    ``MIN_MET_PARTIAL`` (jen dolní mez); jinak ``None`` (chybějící data nikdy
    nedávají číselné hodnocení, docs/10 §10.5).
    ``pct_of_max_low``, ``pct_of_max_high`` – % nutričního maxima
    (``NUTRITIONAL_MAX``); u ``COMPLETE`` obě meze, u ``PARTIAL`` jen dolní
    mez a jen při jistém překročení; jinak ``None``. Nikdy se nespojuje
    s pokrytím minima (docs/06 §6.6.2).
    ``requirements`` – použité požadavky (po filtru podmínky).
    """

    nutrient_code: str
    status: NutrientStatus
    all_statuses: tuple[NutrientStatus, ...]
    coverage_low_pct: Decimal | None
    coverage_high_pct: Decimal | None
    pct_of_max_low: Decimal | None
    pct_of_max_high: Decimal | None
    requirements: tuple[Requirement, ...]


def _percent(value: Decimal, reference: Decimal) -> Decimal:
    with calc_context():
        return value * _HUNDRED / reference


def _applicable(
    requirements: Iterable[Requirement], nutrient_code: str, condition_note: str, *, ratio: bool
) -> tuple[Requirement, ...]:
    if isinstance(requirements, Requirement) or not isinstance(requirements, Iterable):
        raise TypeError("Požadavky musí být kolekce Requirement.")
    if not isinstance(condition_note, str):
        raise TypeError(f"condition_note musí být text, ne {type(condition_note).__name__}.")
    checked = check_requirement_set(requirements)
    for req in checked:
        if req.nutrient_code != nutrient_code:
            raise ValidationError(
                f"Požadavek pro {req.nutrient_code} nelze použít k vyhodnocení {nutrient_code}."
            )
        if req.is_ratio != ratio:
            target = "evaluate_ratio" if req.is_ratio else "evaluate_nutrient"
            raise ValidationError(
                f"Požadavek {req.nutrient_code} typu {req.requirement_type} patří do {target}."
            )
    return tuple(req for req in checked if req.condition_note == condition_note)


def no_data_evaluation(
    nutrient_code: str, requirements: Iterable[Requirement], condition_note: str = ""
) -> NutrientEvaluation:
    """Vyhodnocení živiny, jejíž obsah na 1000 kcal nelze určit (např. neznámá ME dávky).

    Vstup: kód živiny, její požadavky a podmínka (jako :func:`evaluate_nutrient`).
    Výstup: ``NOT_EVALUABLE`` (nebo ``NO_REFERENCE`` bez požadavku), bez čísel.
    Chyby: jako :func:`evaluate_nutrient`.
    """
    code = require_text(nutrient_code, "Kód živiny")
    applicable = _applicable(requirements, code, condition_note, ratio=False)
    status = NutrientStatus.NOT_EVALUABLE if applicable else NutrientStatus.NO_REFERENCE
    return NutrientEvaluation(
        nutrient_code=code,
        status=status,
        all_statuses=(status,),
        coverage_low_pct=None,
        coverage_high_pct=None,
        pct_of_max_low=None,
        pct_of_max_high=None,
        requirements=applicable,
    )


def evaluate_nutrient(
    per_1000: NutrientInterval, requirements: Iterable[Requirement], condition_note: str = ""
) -> NutrientEvaluation:
    """Porovná obsah živiny na 1000 kcal ME s požadavky standardu (docs/06 §6.6.1).

    Použijí se jen požadavky s ``condition_note == condition_note`` (výchozí
    prázdná podmínka = požadavky bez podmínky). Pravidla (meze ``lo``, ``hi``
    obsahu, nezaokrouhlené; požadavky už přepočtené, viz
    :func:`~nutricalc.requirements.select_requirements`):

    - žádný použitelný požadavek → ``NO_REFERENCE``,
    - ``UNKNOWN`` → ``NOT_EVALUABLE``,
    - ``lo > NUTRITIONAL_MAX`` → ``ABOVE_MAX``; ``lo > SUL`` → ``ABOVE_SUL``;
      ``lo > LEGAL_MAX_EU`` → ``ABOVE_LEGAL_MAX_INFO`` (informativní, týká se
      komerčních krmiv); platí i pro ``PARTIAL``,
    - ``COMPLETE``: ``lo ≤ NUTRITIONAL_MAX < hi`` nebo ``lo ≤ SUL < hi`` →
      ``BORDERLINE_MAX``; ``hi < min`` → ``BELOW_MIN``;
      ``lo < min ≤ hi`` → ``BORDERLINE_MIN``,
    - ``PARTIAL``: ``lo ≥ min`` → ``MIN_MET_PARTIAL``, jinak
      ``NOT_EVALUABLE``; bez minima a bez překročeného maxima →
      ``NOT_EVALUABLE``,
    - ``COMPLETE`` bez jiného stavu → ``ADEQUATE``.

    Minimum je jen požadavek typu ``MIN_RECOMMENDED``, ``MR``, ``AI`` nebo
    ``RA``; maximum jen ``NUTRITIONAL_MAX``, ``SUL`` a ``LEGAL_MAX_EU``.

    Vstup: :class:`NutrientInterval` s bází ``PER_1000KCAL_ME``, požadavky
    téže živiny a podmínka.
    Výstup: :class:`NutrientEvaluation`.
    Chyby: ``TypeError`` pro jiný typ;
    :class:`~nutricalc.errors.BasisMismatchError` pro jinou bázi obsahu;
    :class:`~nutricalc.errors.UnitMismatchError` pro jinou jednotku obsahu
    a požadavku; :class:`~nutricalc.errors.ValidationError` pro požadavek jiné
    živiny, poměrový požadavek nebo neplatný soubor požadavků
    (:func:`~nutricalc.requirements.check_requirement_set`).
    """
    if not isinstance(per_1000, NutrientInterval):
        raise TypeError(
            f"evaluate_nutrient očekává NutrientInterval, ne {type(per_1000).__name__}."
        )
    code = per_1000.nutrient_code
    if per_1000.basis != Basis.PER_1000KCAL_ME:
        raise BasisMismatchError(
            f"Obsah {code} musí být na 1000 kcal ME, aby šel porovnat s požadavkem "
            f"(zadaná báze {per_1000.basis})."
        )
    applicable = _applicable(requirements, code, condition_note, ratio=False)
    for req in applicable:
        if req.unit != per_1000.unit:
            raise UnitMismatchError(
                f"Obsah {code} je v {per_1000.unit}, požadavek {req.requirement_type} v {req.unit}."
            )
    if not applicable:
        return no_data_evaluation(code, (), condition_note)
    if per_1000.completeness == Completeness.UNKNOWN:
        return no_data_evaluation(code, applicable, condition_note)
    complete = per_1000.completeness == Completeness.COMPLETE
    low = per_1000.lower
    high = per_1000.upper
    minimum = next((req for req in applicable if req.is_minimum), None)
    maxima = {req.requirement_type: req for req in applicable if req.is_maximum}
    statuses: set[NutrientStatus] = set()
    for kind, exceeded in (
        (RequirementType.NUTRITIONAL_MAX, NutrientStatus.ABOVE_MAX),
        (RequirementType.SUL, NutrientStatus.ABOVE_SUL),
    ):
        limit = maxima.get(kind)
        if limit is None:
            continue
        if low > limit.value:
            statuses.add(exceeded)
        elif complete and high is not None and high > limit.value:
            statuses.add(NutrientStatus.BORDERLINE_MAX)
    legal = maxima.get(RequirementType.LEGAL_MAX_EU)
    if legal is not None and low > legal.value:
        statuses.add(NutrientStatus.ABOVE_LEGAL_MAX_INFO)
    if minimum is not None:
        if complete and high is not None:
            if high < minimum.value:
                statuses.add(NutrientStatus.BELOW_MIN)
            elif low < minimum.value:
                statuses.add(NutrientStatus.BORDERLINE_MIN)
        elif low >= minimum.value:
            statuses.add(NutrientStatus.MIN_MET_PARTIAL)
        else:
            statuses.add(NutrientStatus.NOT_EVALUABLE)
    elif not complete and not statuses & {NutrientStatus.ABOVE_MAX, NutrientStatus.ABOVE_SUL}:
        statuses.add(NutrientStatus.NOT_EVALUABLE)
    if not statuses:
        statuses.add(NutrientStatus.ADEQUATE)
    ordered = ordered_statuses(statuses)
    coverage_low = coverage_high = None
    if minimum is not None and (complete or low >= minimum.value):
        coverage_low = _percent(low, minimum.value)
        if complete and high is not None:
            coverage_high = _percent(high, minimum.value)
    max_low = max_high = None
    nutritional = maxima.get(RequirementType.NUTRITIONAL_MAX)
    if nutritional is not None:
        if complete and high is not None:
            max_low = _percent(low, nutritional.value)
            max_high = _percent(high, nutritional.value)
        elif low > nutritional.value:
            max_low = _percent(low, nutritional.value)
    return NutrientEvaluation(
        nutrient_code=code,
        status=ordered[0],
        all_statuses=ordered,
        coverage_low_pct=coverage_low,
        coverage_high_pct=coverage_high,
        pct_of_max_low=max_low,
        pct_of_max_high=max_high,
        requirements=applicable,
    )


# --- zobrazení -------------------------------------------------------------------------------

_MAX_DECIMALS: Final = 12


def format_decimal_cs(value: Decimal, decimals: int = 0) -> str:
    """Zformátuje číslo česky: desetinná čárka, tisíce oddělené mezerou.

    Zaokrouhlení ``ROUND_HALF_EVEN`` na ``decimals`` desetinných míst (jen pro
    zobrazení). Příklad: ``1040.315`` s 2 místy → ``"1 040,32"``.

    Vstup: ``Decimal`` (také ``int`` nebo text; znaménko povolené) a počet
    desetinných míst (``int`` 0–12).
    Výstup: text.
    Chyby: ``TypeError`` pro ``float`` nebo jiný typ počtu míst;
    :class:`~nutricalc.errors.InvalidInputError` pro počet míst mimo rozsah nebo
    číslo, které by po zaokrouhlení mělo víc než 28 číslic.
    """
    number = to_decimal(value, signed=True, name="Číslo k zobrazení")
    places = _check_decimals(decimals)
    rounded = _round_for_display(number, places)
    text = f"{rounded:f}"
    sign = ""
    if text.startswith("-"):
        sign, text = "-", text[1:]
        if rounded.is_zero():
            sign = ""
    integer, _, fraction = text.partition(".")
    groups: list[str] = []
    while len(integer) > 3:
        groups.insert(0, integer[-3:])
        integer = integer[:-3]
    groups.insert(0, integer)
    result = " ".join(groups)
    if fraction:
        result = f"{result},{fraction}"
    return sign + result


def _round_for_display(value: Decimal, places: int) -> Decimal:
    if value.adjusted() + 1 + places > CALC_PRECISION:
        raise InvalidInputError(
            f"Číslo {value} má pro zobrazení s {places} desetinnými místy příliš mnoho číslic."
        )
    with calc_context():
        return value.quantize(Decimal(1).scaleb(-places))


def _check_decimals(decimals: object) -> int:
    if isinstance(decimals, bool) or not isinstance(decimals, int):
        raise TypeError(f"Počet desetinných míst musí být int, ne {type(decimals).__name__}.")
    if not 0 <= decimals <= _MAX_DECIMALS:
        raise InvalidInputError(
            f"Počet desetinných míst musí být 0 až {_MAX_DECIMALS} (zadáno {decimals})."
        )
    return decimals


def format_coverage(pct: Decimal, decimals: int = 0) -> str:
    """Zobrazí procento pokrytí česky (docs/06 §6.6.2).

    Pravidlo: když je skutečná hodnota < 100 % a po zaokrouhlení
    (``ROUND_HALF_EVEN``) by vyšla 100 %, zobrazí se ``"< 100 %"``.
    Zaokrouhlení je jen pro zobrazení a nikdy nemění stav živiny (stav se
    určuje z nezaokrouhlené hodnoty v :func:`evaluate_nutrient`).

    Vstup: procento ``Decimal`` (≥ 0) a počet desetinných míst (0–12).
    Výstup: text, např. ``"85 %"``, ``"112,5 %"``, ``"< 100 %"``.
    Chyby: ``TypeError`` pro ``float`` a ``None``;
    :class:`~nutricalc.errors.InvalidInputError` pro záporné číslo, počet míst
    mimo rozsah nebo číslo s víc než 28 číslicemi po zaokrouhlení.
    """
    value = to_decimal(pct, name="Procento pokrytí")
    places = _check_decimals(decimals)
    rounded = _round_for_display(value, places)
    if value < _HUNDRED <= rounded:
        return "< 100 %"
    return f"{format_decimal_cs(rounded, places)} %"


# --- poměr Ca:P ------------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class RatioInterval:
    """Hmotnostní poměr dvou denních součtů jako interval [lo, hi] a bod."""

    lower: Decimal
    upper: Decimal
    point: Decimal | None


@dataclass(frozen=True, kw_only=True)
class RatioEvaluation:
    """Výsledek vyhodnocení poměru (docs/06 §6.6.3).

    ``nutrient_code`` (např. ``CA_P``), ``numerator_code``, ``denominator_code``.
    ``interval`` – poměr, nebo ``None``, když ho nelze spočítat.
    ``status``, ``all_statuses`` – jako u :class:`NutrientEvaluation`
    (``BELOW_MIN``, ``BORDERLINE_MIN``, ``ADEQUATE``, ``BORDERLINE_MAX``,
    ``ABOVE_MAX``, ``NOT_EVALUABLE``, ``NO_REFERENCE``).
    ``requirements`` – použité požadavky ``RATIO_MIN``/``RATIO_MAX``.
    """

    nutrient_code: str
    numerator_code: str
    denominator_code: str
    interval: RatioInterval | None
    status: NutrientStatus
    all_statuses: tuple[NutrientStatus, ...]
    requirements: tuple[Requirement, ...]


def _check_ratio_totals(
    ratio_code: str, numerator: NutrientTotal, denominator: NutrientTotal
) -> tuple[str, str]:
    for name, total in (("čitatel", numerator), ("jmenovatel", denominator)):
        if not isinstance(total, NutrientTotal):
            raise TypeError(f"Poměr {ratio_code}: {name} musí být NutrientTotal.")
    components = RATIO_COMPONENTS.get(ratio_code)
    if components is None:
        known = ", ".join(RATIO_COMPONENTS)
        raise ValidationError(f"Neznámý poměr {ratio_code} (jádro zná: {known}).")
    expected = (numerator.nutrient_code, denominator.nutrient_code)
    if expected != components:
        raise ValidationError(
            f"Poměr {ratio_code} se počítá jako {components[0]} / {components[1]}, zadáno "
            f"{expected[0]} / {expected[1]}."
        )
    if numerator.unit != denominator.unit:
        raise UnitMismatchError(
            f"Poměr {ratio_code}: {components[0]} je v {numerator.unit}, {components[1]} "
            f"v {denominator.unit}. Hmotnostní poměr vyžaduje stejnou jednotku."
        )
    if numerator.basis != denominator.basis:
        raise BasisMismatchError(f"Poměr {ratio_code}: součty mají různé báze.")
    return components


def ratio_interval(
    numerator: NutrientTotal, denominator: NutrientTotal, ratio_code: str = CA_P
) -> RatioInterval | None:
    """Spočítá hmotnostní poměr dvou denních součtů (docs/06 §6.6.3).

    Interval ``[num_lo / den_hi, num_hi / den_lo]``; bod ``num / den``, mají-li
    oba součty bodovou hodnotu. Počítá se jen tehdy, když jsou oba součty
    ``COMPLETE`` a dolní mez jmenovatele je > 0 (žádné dělení nulou).

    Vstup: součty čitatele a jmenovatele (pro ``CA_P`` vápník a fosfor) a kód poměru.
    Výstup: :class:`RatioInterval`, nebo ``None``, když poměr nelze spočítat.
    Chyby: ``TypeError``; :class:`~nutricalc.errors.ValidationError` pro neznámý
    poměr nebo prohozené živiny; :class:`~nutricalc.errors.UnitMismatchError`,
    :class:`~nutricalc.errors.BasisMismatchError`.
    """
    _check_ratio_totals(ratio_code, numerator, denominator)
    complete = Completeness.COMPLETE
    if numerator.completeness != complete or denominator.completeness != complete:
        return None
    if numerator.upper is None or denominator.upper is None or not denominator.lower > 0:
        return None
    with calc_context():
        lower = numerator.lower / denominator.upper
        upper = numerator.upper / denominator.lower
        point = None
        if numerator.point is not None and denominator.point is not None:
            point = numerator.point / denominator.point
    return RatioInterval(lower=lower, upper=upper, point=point)


def evaluate_ratio(
    ca_total: NutrientTotal,
    p_total: NutrientTotal,
    ratio_requirements: Iterable[Requirement],
    *,
    ratio_code: str = CA_P,
    condition_note: str = "",
) -> RatioEvaluation:
    """Vyhodnotí poměr Ca:P proti ``RATIO_MIN`` a ``RATIO_MAX`` (docs/06 §6.6.3).

    Pravidla: bez použitelného požadavku → ``NO_REFERENCE``; poměr nelze
    spočítat (:func:`ratio_interval`) → ``NOT_EVALUABLE``; jinak
    ``hi < RATIO_MIN`` → ``BELOW_MIN``, ``lo < RATIO_MIN ≤ hi`` →
    ``BORDERLINE_MIN``, ``lo > RATIO_MAX`` → ``ABOVE_MAX``,
    ``lo ≤ RATIO_MAX < hi`` → ``BORDERLINE_MAX``, jinak ``ADEQUATE``.

    Vstup: denní součty Ca a P (:class:`~nutricalc.composition.NutrientTotal`),
    požadavky poměru (jen ``RATIO_MIN``/``RATIO_MAX`` s kódem ``ratio_code``)
    a podmínka.
    Výstup: :class:`RatioEvaluation`.
    Chyby: jako :func:`ratio_interval`; :class:`~nutricalc.errors.ValidationError`
    pro požadavek jiného kódu nebo typu.
    """
    numerator_code, denominator_code = _check_ratio_totals(ratio_code, ca_total, p_total)
    applicable = _applicable(ratio_requirements, ratio_code, condition_note, ratio=True)
    interval = ratio_interval(ca_total, p_total, ratio_code)
    statuses: set[NutrientStatus] = set()
    if not applicable:
        statuses.add(NutrientStatus.NO_REFERENCE)
    elif interval is None:
        statuses.add(NutrientStatus.NOT_EVALUABLE)
    else:
        for req in applicable:
            if req.requirement_type == RequirementType.RATIO_MIN:
                if interval.upper < req.value:
                    statuses.add(NutrientStatus.BELOW_MIN)
                elif interval.lower < req.value:
                    statuses.add(NutrientStatus.BORDERLINE_MIN)
            elif interval.lower > req.value:
                statuses.add(NutrientStatus.ABOVE_MAX)
            elif interval.upper > req.value:
                statuses.add(NutrientStatus.BORDERLINE_MAX)
        if not statuses:
            statuses.add(NutrientStatus.ADEQUATE)
    ordered = ordered_statuses(statuses)
    return RatioEvaluation(
        nutrient_code=ratio_code,
        numerator_code=numerator_code,
        denominator_code=denominator_code,
        interval=interval,
        status=ordered[0],
        all_statuses=ordered,
        requirements=applicable,
    )


# --- spolehlivost ----------------------------------------------------------------------------


class QualityContributor(NamedTuple):
    """Surovina se známou horní mezí příspěvku a kvalitou údaje."""

    ingredient_code: str
    upper: Decimal
    quality: QualityGrade


def confidence(
    contributors: Iterable[QualityContributor], threshold: Decimal
) -> QualityGrade | None:
    """Spolehlivost výsledku živiny = nejhorší kvalita významných surovin (docs/06 §6.6.5).

    Významná je surovina, jejíž horní mez příspěvku je alespoň ``threshold``
    ze součtu horních mezí (``upper ≥ threshold · Σ upper``). Je-li součet 0
    nebo žádná surovina práh nedosáhne, rozhoduje nejhorší kvalita všech
    známých surovin (konzervativně).

    Vstup: suroviny se známým příspěvkem (:class:`QualityContributor`) a práh
    jako podíl 0–1 (``Decimal``; data, která předává volající 🛠 🩺).
    Výstup: :class:`~nutricalc.vocab.QualityGrade`, nebo ``None``, když není
    žádná surovina se známým příspěvkem.
    Chyby: ``TypeError`` pro ``float`` a jiné typy;
    :class:`~nutricalc.errors.InvalidInputError` pro práh mimo 0–1 nebo
    zápornou mez.
    """
    if not isinstance(threshold, Decimal):
        raise TypeError(f"Práh spolehlivosti musí být Decimal, ne {type(threshold).__name__}.")
    share = to_decimal(threshold, name="Práh spolehlivosti")
    if share > 1:
        raise InvalidInputError(f"Práh spolehlivosti musí být 0 až 1 (zadáno {share}).")
    collected: list[QualityContributor] = []
    for entry in contributors:
        if not isinstance(entry, QualityContributor):
            raise TypeError(f"Očekává se QualityContributor, ne {type(entry).__name__}.")
        to_decimal(entry.upper, name=f"Horní mez příspěvku {entry.ingredient_code}")
        as_member(QualityGrade, entry.quality, "kvalita údaje")
        collected.append(entry)
    if not collected:
        return None
    with calc_context():
        total = sum((entry.upper for entry in collected), _ZERO)
        limit = share * total
    relevant = [entry for entry in collected if total > 0 and entry.upper >= limit]
    return worst_quality(entry.quality for entry in (relevant or collected))


# --- souhrn ----------------------------------------------------------------------------------


class SummaryStatus(StrEnum):
    """Souhrnný stav dávky (docs/06 §6.6.4)."""

    BLOCKED = "BLOCKED"
    INCOMPLETE = "INCOMPLETE"
    DEFICITS_OR_EXCESSES = "DEFICITS_OR_EXCESSES"
    BORDERLINE = "BORDERLINE"
    ALL_EVALUATED_MET = "ALL_EVALUATED_MET"


@dataclass(frozen=True, kw_only=True)
class Summary:
    """Souhrn rozboru.

    ``status`` – :class:`SummaryStatus`.
    ``evaluated_count`` / ``required_count`` – vyhodnocené povinné živiny
    z počtu povinných („vyhodnoceno X z Y“).
    ``not_evaluated`` – povinné živiny, které vyhodnotit nešlo (seřazené).
    ``status_counts`` – počet živin v každém hlavním stavu (všechny stavy
    v pořadí :data:`STATUS_PRIORITY`, i s nulou).
    ``message_cs`` – česká souhrnná věta.
    """

    status: SummaryStatus
    evaluated_count: int
    required_count: int
    not_evaluated: tuple[str, ...]
    status_counts: tuple[tuple[NutrientStatus, int], ...]
    message_cs: str


def profile_label(profile: StandardProfile) -> str:
    """Český popis profilu pro souhrn, např. ``"TESTSTD 1 (pes, dospělý, udržovací potřeba)"``."""
    if not isinstance(profile, StandardProfile):
        raise TypeError(f"profile_label očekává StandardProfile, ne {type(profile).__name__}.")
    return (
        f"{profile.standard_code} {profile.edition} ({SPECIES_LABELS[profile.species]}, "
        f"{LIFE_STAGE_LABELS[profile.life_stage]})"
    )


def met_message(standard_label: str) -> str:
    """Věta pro souhrn ``ALL_EVALUATED_MET`` (docs/08 §8.7, docs/06 §6.6.4).

    Říká, že splněny jsou jen **vyhodnocené** požadavky jmenovaného standardu
    a že to neznamená, že je dávka bezpečná.
    """
    label = require_text(standard_label, "Popis standardu")
    return (
        f"Všechny vyhodnocené požadavky standardu {label} jsou splněny. To neznamená, že dávka "
        "je bezpečná nebo kompletní: vyhodnocení vychází z dostupných dat o surovinách a "
        "nezohledňuje mikrobiologická rizika."
    )


_UNEVALUATED: Final = frozenset({NutrientStatus.NOT_EVALUABLE, NutrientStatus.NO_REFERENCE})


def summarize(
    gate_status: GateStatus | str,
    nutrient_results: Mapping[str, NutrientStatus],
    mandatory_nutrients: Iterable[str],
    maxima_by_nutrient: Mapping[str, Iterable[RequirementType]],
    *,
    standard_label: str,
) -> Summary:
    """Konzervativní souhrnný stav dávky (docs/06 §6.6.4).

    Pořadí pravidel:
        1. ``BLOCKED``, pokud brána blokuje (stavy živin se neuvádějí).
        2. ``INCOMPLETE``, pokud je některá povinná živina ``NOT_EVALUABLE``,
           ``NO_REFERENCE``, ve výsledcích chybí, nebo je ``MIN_MET_PARTIAL``
           a má maximum (``NUTRITIONAL_MAX``, ``SUL`` nebo ``LEGAL_MAX_EU``),
           které nelze ověřit; ``INCOMPLETE`` také tehdy, když se nepodařilo
           vyhodnotit vůbec nic (jen ``NOT_EVALUABLE`` a ``NO_REFERENCE``),
           protože věta „vše vyhodnocené splněno“ by pak byla zavádějící.
        3. ``DEFICITS_OR_EXCESSES`` při ``BELOW_MIN``, ``ABOVE_MAX`` nebo
           ``ABOVE_SUL`` u kterékoli živiny.
        4. ``BORDERLINE`` při ``BORDERLINE_MIN`` nebo ``BORDERLINE_MAX``.
        5. Jinak ``ALL_EVALUATED_MET`` (věta :func:`met_message`).

    Vstup: stav brány, hlavní stavy živin a poměrů podle kódu, povinné živiny
    profilu, typy maxim podle kódu živiny a český popis standardu
    (:func:`profile_label`).
    Výstup: :class:`Summary`.
    Chyby: ``TypeError`` pro jiné typy;
    :class:`~nutricalc.errors.InvalidInputError` pro neznámý stav nebo typ.
    """
    gate = as_member(GateStatus, gate_status, "stav brány")
    label = require_text(standard_label, "Popis standardu")
    if not isinstance(nutrient_results, Mapping):
        raise TypeError("nutrient_results musí být mapování kód → NutrientStatus.")
    statuses = {
        require_text(code, "Kód živiny"): as_member(NutrientStatus, status, "stav živiny")
        for code, status in nutrient_results.items()
    }
    if isinstance(mandatory_nutrients, str) or not isinstance(mandatory_nutrients, Iterable):
        raise TypeError("mandatory_nutrients musí být kolekce kódů živin.")
    mandatory = sorted({require_text(code, "Kód povinné živiny") for code in mandatory_nutrients})
    if not isinstance(maxima_by_nutrient, Mapping):
        raise TypeError("maxima_by_nutrient musí být mapování kód → typy požadavků.")
    with_maximum = {
        code
        for code, kinds in maxima_by_nutrient.items()
        if any(as_member(RequirementType, kind, "typ požadavku") in MAXIMUM_TYPES for kind in kinds)
    }
    if gate == GateStatus.BLOCKED:
        return Summary(
            status=SummaryStatus.BLOCKED,
            evaluated_count=0,
            required_count=len(mandatory),
            not_evaluated=tuple(mandatory),
            status_counts=tuple((status, 0) for status in STATUS_PRIORITY),
            message_cs=(
                "Automatický výpočet nelze doporučit. Požadavky standardu se nevyhodnotily; "
                "dávku musí sestavit nebo posoudit veterinář."
            ),
        )
    not_evaluated = tuple(
        code
        for code in mandatory
        if code not in statuses
        or statuses[code] in _UNEVALUATED
        or (statuses[code] == NutrientStatus.MIN_MET_PARTIAL and code in with_maximum)
    )
    counts = tuple(
        (status, sum(1 for value in statuses.values() if value == status))
        for status in STATUS_PRIORITY
    )
    present = set(statuses.values())
    evaluated = len(mandatory) - len(not_evaluated)
    if not_evaluated:
        status = SummaryStatus.INCOMPLETE
        message = (
            f"Neúplné vyhodnocení (vyhodnoceno {evaluated} z {len(mandatory)} povinných živin). "
            f"Nelze plně vyhodnotit: {', '.join(not_evaluated)}. Chybějící údaj nelze nahradit nulou."
        )
    elif not present - _UNEVALUATED:
        status = SummaryStatus.INCOMPLETE
        message = (
            "Neúplné vyhodnocení: žádný požadavek standardu nebylo možné vyhodnotit. "
            "Chybějící údaj nelze nahradit nulou."
        )
    elif present & DEFICIT_OR_EXCESS_STATUSES:
        status = SummaryStatus.DEFICITS_OR_EXCESSES
        message = "Nalezeny nedostatky nebo nadbytky."
    elif present & BORDERLINE_STATUSES:
        status = SummaryStatus.BORDERLINE
        message = "Na hranici – doporučena kontrola."
    else:
        status = SummaryStatus.ALL_EVALUATED_MET
        message = met_message(label)
    return Summary(
        status=status,
        evaluated_count=evaluated,
        required_count=len(mandatory),
        not_evaluated=not_evaluated,
        status_counts=counts,
        message_cs=message,
    )
