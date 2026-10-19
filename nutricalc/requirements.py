"""Požadavky standardu, výběr sloupce a přepočet na skutečné zvíře (docs/06 §6.4).

Hodnoty požadavků, referenční energie sloupců (``reference_k``) a seznam
povinných živin jsou **data** schválené verze standardu, která předává
volající jako :class:`StandardProfile`. V kódu nejsou žádné hodnoty
požadavků ani koeficienty sloupců (docs/05 §5.0, docs/06 §6.7).

Výběr sloupce (:func:`select_requirements`) je konzervativní návrh docs/06
§6.4 🛠 🩺: zvíře s nižším příjmem energie, než předpokládá nižší sloupec,
dostane požadavky typu minimum vynásobené poměrem ``reference_k / k_skut``.
Maxima a poměry se nikdy nepřepočítávají. Lineární přepočet musí potvrdit
specialista, proto výsledek s faktorem ≠ 1 vždy nese upozornění
``REQUIREMENT_SCALING_NEEDS_REVIEW``.
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from decimal import Decimal
from types import MappingProxyType
from typing import Final

from nutricalc.decimal_ctx import calc_context, round_significant, to_decimal
from nutricalc.errors import (
    BasisMismatchError,
    InvalidInputError,
    SpeciesMismatchError,
    UnitMismatchError,
    ValidationError,
)
from nutricalc.flags import Flag, sorted_flags
from nutricalc.units import MASS_UNITS, Quantity, per_1000kcal_to_per_day
from nutricalc.vocab import (
    BASIS_LABELS,
    MAXIMUM_TYPES,
    METABOLIC_EXPONENT,
    MINIMUM_TYPES,
    RATIO_TYPES,
    Basis,
    LifeStage,
    RequirementType,
    Species,
    Unit,
    WarningLevel,
    as_member,
    require_text,
)

REQUIREMENT_BASIS: Final = Basis.PER_1000KCAL_ME
"""Báze všech požadavků v jádře (docs/06 §6.4; jiné báze převede import)."""

LIFE_STAGE_PAIRS: Final = MappingProxyType(
    {LifeStage.ADULT_MAINTENANCE: LifeStage.ADULT_MAINTENANCE_LOW}
)
"""Dvojice sloupců jednoho standardu: fáze vyššího sloupce → fáze nižšího sloupce.

Struktura tabulek FEDIAF pro dospělé (docs/03 §3.1): sloupec běžné a sloupec
nízké potřeby energie. Hodnoty ``reference_k`` obou sloupců jsou data
profilu, ne konstanty kódu.
"""

K_ACTUAL_SIGNIFICANT_DIGITS: Final = 20
"""Počet platných číslic ``k_skut`` (technická konstanta, ne nutriční údaj).

``DER = k · BW^n`` se počítá s přesností 28 číslic, takže zpětný výpočet
``DER / BW^n`` se od ``k`` může lišit v poslední číslici (např.
``109,99…9`` místo ``110``). Zaokrouhlení na 20 platných číslic tuto chybu
odstraní, aby nezměnila volbu sloupce na přesné hranici.
"""

_TYPE_ORDER: Final = MappingProxyType(
    {member: index for index, member in enumerate(RequirementType)}
)


# --- požadavek a profil ------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class Requirement:
    """Jeden požadavek standardu na 1000 kcal ME (data, docs/07 §7.4 ``NutrientRequirement``).

    Pole (jen jako pojmenované argumenty):
        ``nutrient_code`` – kód živiny z katalogu (např. ``CA``, ``CA_P``).
        ``requirement_type`` – :class:`~nutricalc.vocab.RequirementType`.
        ``value`` – hodnota (``Decimal``, ``int`` nebo text; > 0).
        ``unit`` – kanonická jednotka živiny (g, mg, µg); požadavky typu
        ``RATIO_MIN``/``RATIO_MAX`` mají jednotku ``ratio``.
        ``basis`` – vždy ``PER_1000KCAL_ME`` (také u poměrů, jako v šabloně
        přepisu ``data/reference/standard_import_template.csv``; poměr na bázi
        nezávisí).
        ``condition_note`` – podmínka platnosti z originálu (prázdná =
        požadavek platí bez podmínky).
        ``source_key`` – klíč zdroje z ``docs/zdroje.md``.

    Chyby: ``TypeError`` pro ``float`` a jiné typy;
    :class:`~nutricalc.errors.ValidationError` pro prázdný text, hodnotu ≤ 0
    nebo podmínku s okrajovými mezerami;
    :class:`~nutricalc.errors.UnitMismatchError`, když jednotka neodpovídá
    typu (poměr ⇔ ``ratio``, živina ⇔ g/mg/µg);
    :class:`~nutricalc.errors.BasisMismatchError` pro jinou bázi než
    ``PER_1000KCAL_ME``.
    """

    nutrient_code: str
    requirement_type: RequirementType
    value: Decimal
    unit: Unit
    basis: Basis
    condition_note: str = ""
    source_key: str

    def __post_init__(self) -> None:
        require_text(self.nutrient_code, "Requirement.nutrient_code")
        require_text(self.source_key, "Requirement.source_key")
        if not isinstance(self.condition_note, str):
            raise TypeError(
                f"Requirement.condition_note musí být text, ne {type(self.condition_note).__name__}."
            )
        if self.condition_note != self.condition_note.strip():
            raise ValidationError(
                f"Podmínka požadavku {self.nutrient_code} nesmí začínat ani končit mezerou."
            )
        kind = as_member(RequirementType, self.requirement_type, "typ požadavku")
        object.__setattr__(self, "requirement_type", kind)
        value = to_decimal(self.value, name=f"Hodnota požadavku {self.nutrient_code}")
        if not value > 0:
            raise ValidationError(
                f"Hodnota požadavku {self.nutrient_code} {kind} musí být větší než 0 "
                f"(zadáno {value})."
            )
        object.__setattr__(self, "value", value)
        unit = as_member(Unit, self.unit, "jednotka požadavku")
        object.__setattr__(self, "unit", unit)
        basis = as_member(Basis, self.basis, "báze požadavku")
        object.__setattr__(self, "basis", basis)
        if basis != REQUIREMENT_BASIS:
            raise BasisMismatchError(
                f"Požadavek {self.nutrient_code} {kind} je {BASIS_LABELS[basis]}; jádro přijímá "
                f"jen požadavky {BASIS_LABELS[REQUIREMENT_BASIS]} (převod provede import)."
            )
        if kind in RATIO_TYPES:
            if unit != Unit.RATIO:
                raise UnitMismatchError(
                    f"Požadavek {self.nutrient_code} typu {kind} musí mít jednotku ratio "
                    f"(zadáno {unit})."
                )
        elif unit not in MASS_UNITS:
            raise UnitMismatchError(
                f"Požadavek {self.nutrient_code} typu {kind} musí mít jednotku g, mg nebo ug "
                f"(zadáno {unit}). Poměr zapište jako RATIO_MIN nebo RATIO_MAX."
            )

    @property
    def is_minimum(self) -> bool:
        """``True`` pro typ minimum (``MIN_RECOMMENDED``, ``MR``, ``AI``, ``RA``)."""
        return self.requirement_type in MINIMUM_TYPES

    @property
    def is_maximum(self) -> bool:
        """``True`` pro typ maximum (``NUTRITIONAL_MAX``, ``LEGAL_MAX_EU``, ``SUL``)."""
        return self.requirement_type in MAXIMUM_TYPES

    @property
    def is_ratio(self) -> bool:
        """``True`` pro požadavek na poměr (``RATIO_MIN``, ``RATIO_MAX``)."""
        return self.requirement_type in RATIO_TYPES

    def quantity(self) -> Quantity:
        """Hodnota požadavku jako :class:`~nutricalc.units.Quantity` (na 1000 kcal ME)."""
        return Quantity(self.value, self.unit, self.basis)


def requirement_sort_key(req: Requirement) -> tuple[str, str, int, Decimal, str, str]:
    """Klíč deterministického pořadí požadavků (živina, podmínka, typ, hodnota…)."""
    return (
        req.nutrient_code,
        req.condition_note,
        _TYPE_ORDER[req.requirement_type],
        req.value,
        req.unit.value,
        req.source_key,
    )


def check_requirement_set(requirements: Iterable[Requirement]) -> tuple[Requirement, ...]:
    """Zkontroluje soubor požadavků a vrátí ho v deterministickém pořadí.

    Pravidla pro každou dvojici (živina, podmínka):
        - nejvýše jeden požadavek typu minimum (``MIN_RECOMMENDED``, ``MR``,
          ``AI``, ``RA`` dohromady),
        - nejvýše jeden požadavek od každého typu maxima a poměru,
        - minimum je menší než každé maximum a ``RATIO_MIN`` menší než
          ``RATIO_MAX`` (jako kontrola ``E_MIN_NOT_BELOW_MAX`` v ``refdata``).
    Všechny požadavky jedné živiny mají stejnou jednotku.

    Vstup: požadavky v libovolném pořadí.
    Výstup: n-tice seřazená podle :func:`requirement_sort_key`.
    Chyby: ``TypeError`` pro jinou položku než :class:`Requirement`;
    :class:`~nutricalc.errors.ValidationError` pro porušení pravidel.
    """
    collected: list[Requirement] = []
    for req in requirements:
        if not isinstance(req, Requirement):
            raise TypeError(f"Požadavek musí být Requirement, ne {type(req).__name__}.")
        collected.append(req)
    ordered = tuple(sorted(collected, key=requirement_sort_key))
    units: dict[str, Unit] = {}
    groups: defaultdict[tuple[str, str], list[Requirement]] = defaultdict(list)
    for req in ordered:
        known = units.setdefault(req.nutrient_code, req.unit)
        if known != req.unit:
            raise ValidationError(
                f"Požadavky živiny {req.nutrient_code} mají různé jednotky ({known} a {req.unit}). "
                "Všechny požadavky jedné živiny musí být v její kanonické jednotce."
            )
        groups[(req.nutrient_code, req.condition_note)].append(req)
    for (code, note), group in groups.items():
        where = f"{code}" + (f" (podmínka „{note}“)" if note else "")
        minima = [req for req in group if req.is_minimum]
        if len(minima) > 1:
            kinds = ", ".join(req.requirement_type.value for req in minima)
            raise ValidationError(
                f"Živina {where} má více požadavků typu minimum ({kinds}). Povolen je nejvýše "
                "jeden; ostatní rozlište podmínkou (condition_note)."
            )
        seen: set[RequirementType] = set()
        for req in group:
            if req.is_minimum:
                continue
            if req.requirement_type in seen:
                raise ValidationError(
                    f"Živina {where} má požadavek {req.requirement_type} vícekrát."
                )
            seen.add(req.requirement_type)
        for low in minima:
            for high in (req for req in group if req.is_maximum):
                if not low.value < high.value:
                    raise ValidationError(
                        f"Živina {where}: minimum {low.requirement_type} {low.value} {low.unit} "
                        f"musí být menší než {high.requirement_type} {high.value} {high.unit}."
                    )
        ratio_min = [req for req in group if req.requirement_type == RequirementType.RATIO_MIN]
        ratio_max = [req for req in group if req.requirement_type == RequirementType.RATIO_MAX]
        for low in ratio_min:
            for high in ratio_max:
                if not low.value < high.value:
                    raise ValidationError(
                        f"Poměr {where}: RATIO_MIN {low.value} musí být menší než RATIO_MAX "
                        f"{high.value}."
                    )
    return ordered


@dataclass(frozen=True, kw_only=True)
class StandardProfile:
    """Jeden sloupec schváleného standardu pro druh a fázi (data, docs/06 §6.4).

    Pole (jen jako pojmenované argumenty):
        ``standard_code``, ``edition`` – standard a jeho vydání.
        ``species``, ``life_stage`` – druh a životní fáze sloupce.
        ``reference_k`` – referenční energie sloupce v kcal ME/kg BW^n (> 0).
        ``exponent`` – exponent ``n`` metabolické hmotnosti; musí odpovídat
        druhu (:data:`~nutricalc.vocab.METABOLIC_EXPONENT`).
        ``requirements`` – požadavky (libovolná kolekce :class:`Requirement`;
        uloží se jako n-tice v pořadí :func:`requirement_sort_key`, pravidla
        viz :func:`check_requirement_set`).
        ``mandatory_nutrients`` – povinné živiny profilu (bez dat o nich není
        souhrn nikdy „splněno“, docs/06 §6.6.4); každá musí mít aspoň jeden
        požadavek.
        ``data_version`` – verze dat standardu (``DataVersion``).

    Chyby: ``TypeError`` pro nesprávné typy;
    :class:`~nutricalc.errors.ValidationError` pro prázdný text, ``reference_k``
    ≤ 0, porušení pravidel požadavků nebo povinnou živinu bez požadavku;
    :class:`~nutricalc.errors.SpeciesMismatchError`, když exponent neodpovídá
    druhu.
    """

    standard_code: str
    edition: str
    species: Species
    life_stage: LifeStage
    reference_k: Decimal
    exponent: Decimal
    requirements: tuple[Requirement, ...]
    mandatory_nutrients: frozenset[str]
    data_version: str

    def __post_init__(self) -> None:
        require_text(self.standard_code, "StandardProfile.standard_code")
        require_text(self.edition, "StandardProfile.edition")
        require_text(self.data_version, "StandardProfile.data_version")
        species = as_member(Species, self.species, "druh profilu")
        object.__setattr__(self, "species", species)
        object.__setattr__(
            self, "life_stage", as_member(LifeStage, self.life_stage, "životní fáze profilu")
        )
        reference_k = to_decimal(self.reference_k, name="StandardProfile.reference_k")
        if not reference_k > 0:
            raise ValidationError(
                f"Referenční energie profilu musí být větší než 0 (zadáno {reference_k})."
            )
        object.__setattr__(self, "reference_k", reference_k)
        exponent = to_decimal(self.exponent, name="StandardProfile.exponent")
        if exponent != METABOLIC_EXPONENT[species]:
            raise SpeciesMismatchError(
                f"Profil {self.standard_code} {self.edition} pro druh {species} má exponent "
                f"{exponent}; druh {species} vyžaduje {METABOLIC_EXPONENT[species]}."
            )
        object.__setattr__(self, "exponent", exponent)
        if isinstance(self.requirements, (str, Requirement)) or not isinstance(
            self.requirements, Iterable
        ):
            raise TypeError("StandardProfile.requirements musí být kolekce Requirement.")
        object.__setattr__(self, "requirements", check_requirement_set(self.requirements))
        if isinstance(self.mandatory_nutrients, str) or not isinstance(
            self.mandatory_nutrients, Iterable
        ):
            raise TypeError("StandardProfile.mandatory_nutrients musí být kolekce kódů živin.")
        mandatory = frozenset(self.mandatory_nutrients)
        for code in mandatory:
            require_text(code, "Kód povinné živiny")
        object.__setattr__(self, "mandatory_nutrients", mandatory)
        covered = {req.nutrient_code for req in self.requirements}
        lacking = sorted(mandatory - covered)
        if lacking:
            raise ValidationError(
                f"Povinné živiny {', '.join(lacking)} nemají v profilu {self.standard_code} "
                f"{self.edition} ({self.life_stage}) žádný požadavek."
            )

    @property
    def nutrient_codes(self) -> frozenset[str]:
        """Kódy všech živin a poměrů, pro které profil uvádí požadavek."""
        return frozenset(req.nutrient_code for req in self.requirements)

    def for_nutrient(self, nutrient_code: str) -> tuple[Requirement, ...]:
        """Požadavky jedné živiny (všechny podmínky) v pořadí profilu."""
        return tuple(req for req in self.requirements if req.nutrient_code == nutrient_code)


# --- skutečný koeficient a výběr sloupce -----------------------------------------------------


def _positive(value: Decimal | int | str, name: str) -> Decimal:
    number = to_decimal(value, name=name)
    if not number > 0:
        raise InvalidInputError(f"{name} musí být větší než 0 (zadáno {number}).")
    return number


def actual_k(
    der_kcal: Decimal | int | str, body_weight_kg: Decimal | int | str, species: Species | str
) -> Decimal:
    """Skutečný koeficient zvířete ``k_skut = DER / BW^n`` (docs/06 §6.4).

    Vstup: denní energetická potřeba v kcal ME (> 0), hmotnost v kg (> 0) a
    druh (určuje ``n``: pes 0,75, kočka 0,67).
    Výstup: ``k_skut`` v kcal ME/kg BW^n zaokrouhlené na
    :data:`K_ACTUAL_SIGNIFICANT_DIGITS` platných číslic.
    Chyby: ``TypeError`` pro ``float``;
    :class:`~nutricalc.errors.InvalidInputError` pro hodnotu ≤ 0 nebo neznámý druh.
    """
    der = _positive(der_kcal, "Energetická potřeba DER (kcal/den)")
    weight = _positive(body_weight_kg, "Hmotnost (kg)")
    member = as_member(Species, species, "druh")
    with calc_context():
        value = der / weight ** METABOLIC_EXPONENT[member]
    return round_significant(value, K_ACTUAL_SIGNIFICANT_DIGITS)


@dataclass(frozen=True, kw_only=True)
class SelectedColumn:
    """Popis použitého sloupce standardu pro výsledek rozboru.

    ``column_code`` – identifikátor sloupce ``standard:vydání:druh:fáze``.
    ``reference_k`` – referenční energie použitého sloupce.
    ``k_actual`` – skutečný koeficient zvířete.
    ``min_scale_factor`` – faktor, kterým se násobí požadavky typu minimum
    (1, nebo ``reference_k / k_actual`` > 1).
    """

    column_code: str
    standard_code: str
    edition: str
    species: Species
    life_stage: LifeStage
    reference_k: Decimal
    k_actual: Decimal
    min_scale_factor: Decimal
    data_version: str


@dataclass(frozen=True, kw_only=True)
class SelectedRequirements:
    """Výsledek výběru sloupce (:func:`select_requirements`).

    ``profile_used`` – použitý profil (nepřepočtený, jak přišel v datech).
    ``k_actual`` – skutečný koeficient zvířete.
    ``min_scale_factor`` – faktor pro požadavky typu minimum (≥ 1).
    ``column_code`` – identifikátor sloupce (viz :class:`SelectedColumn`).
    ``requirements`` – požadavky profilu po přepočtu (minima × faktor;
    maxima a poměry beze změny), pořadí jako v profilu.
    ``flags`` – upozornění (``REQUIREMENT_SCALING_NEEDS_REVIEW`` při faktoru ≠ 1).
    """

    profile_used: StandardProfile
    k_actual: Decimal
    min_scale_factor: Decimal
    column_code: str
    requirements: tuple[Requirement, ...]
    flags: tuple[Flag, ...]

    @property
    def column(self) -> SelectedColumn:
        """Souhrn použitého sloupce (bez seznamu požadavků)."""
        profile = self.profile_used
        return SelectedColumn(
            column_code=self.column_code,
            standard_code=profile.standard_code,
            edition=profile.edition,
            species=profile.species,
            life_stage=profile.life_stage,
            reference_k=profile.reference_k,
            k_actual=self.k_actual,
            min_scale_factor=self.min_scale_factor,
            data_version=profile.data_version,
        )

    def for_nutrient(self, nutrient_code: str) -> tuple[Requirement, ...]:
        """Přepočtené požadavky jedné živiny (všechny podmínky)."""
        return tuple(req for req in self.requirements if req.nutrient_code == nutrient_code)


def column_code(profile: StandardProfile) -> str:
    """Identifikátor sloupce ``standard:vydání:druh:fáze`` (např. ``TESTSTD:1:DOG:ADULT_MAINTENANCE``)."""
    return f"{profile.standard_code}:{profile.edition}:{profile.species}:{profile.life_stage}"


def check_profile_pair(high_profile: StandardProfile, low_profile: StandardProfile) -> None:
    """Ověří, že dva profily tvoří dvojici sloupců jednoho standardu.

    Vstup: profil vyššího sloupce (běžná potřeba energie) a nižšího sloupce.
    Výstup: žádný.
    Chyby: ``TypeError`` pro jiný typ;
    :class:`~nutricalc.errors.SpeciesMismatchError` pro různé druhy nebo
    fáze, které netvoří dvojici :data:`LIFE_STAGE_PAIRS`;
    :class:`~nutricalc.errors.ValidationError` pro různý standard, vydání,
    ``reference_k`` vyššího sloupce, které není větší než nižšího, nebo
    různé jednotky téže živiny.
    """
    for name, profile in (("high_profile", high_profile), ("low_profile", low_profile)):
        if not isinstance(profile, StandardProfile):
            raise TypeError(f"{name} musí být StandardProfile, ne {type(profile).__name__}.")
    if high_profile.species != low_profile.species:
        raise SpeciesMismatchError(
            f"Profily standardu patří různým druhům ({high_profile.species} a "
            f"{low_profile.species}). Oba sloupce musí být pro druh zvířete."
        )
    if (high_profile.standard_code, high_profile.edition) != (
        low_profile.standard_code,
        low_profile.edition,
    ):
        raise ValidationError(
            f"Profily jsou z různých standardů nebo vydání ({high_profile.standard_code} "
            f"{high_profile.edition} a {low_profile.standard_code} {low_profile.edition})."
        )
    if LIFE_STAGE_PAIRS.get(high_profile.life_stage) != low_profile.life_stage:
        allowed = ", ".join(f"{high} + {low}" for high, low in LIFE_STAGE_PAIRS.items())
        raise SpeciesMismatchError(
            f"Fáze {high_profile.life_stage} a {low_profile.life_stage} netvoří dvojici sloupců "
            f"standardu (povolené dvojice: {allowed})."
        )
    if not high_profile.reference_k > low_profile.reference_k:
        raise ValidationError(
            f"Referenční energie vyššího sloupce ({high_profile.reference_k}) musí být větší než "
            f"nižšího sloupce ({low_profile.reference_k})."
        )
    units = {req.nutrient_code: req.unit for req in high_profile.requirements}
    for req in low_profile.requirements:
        known = units.get(req.nutrient_code)
        if known is not None and known != req.unit:
            raise ValidationError(
                f"Živina {req.nutrient_code} má ve sloupcích standardu různé jednotky "
                f"({known} a {req.unit})."
            )


def scale_minima(requirements: Iterable[Requirement], factor: Decimal) -> tuple[Requirement, ...]:
    """Vynásobí požadavky typu minimum faktorem; maxima a poměry vrátí beze změny.

    Vstup: požadavky a faktor ``Decimal`` (≥ 1).
    Výstup: n-tice ve stejném pořadí.
    Chyby: ``TypeError`` pro jiný typ; :class:`~nutricalc.errors.ValidationError`
    pro faktor < 1 (požadavky se nikdy nesnižují).
    """
    if not isinstance(factor, Decimal):
        raise TypeError(f"Faktor přepočtu musí být Decimal, ne {type(factor).__name__}.")
    number = to_decimal(factor, name="Faktor přepočtu")
    if number < 1:
        raise ValidationError(f"Faktor přepočtu minim nesmí být menší než 1 (zadáno {number}).")
    result = []
    for req in requirements:
        if not isinstance(req, Requirement):
            raise TypeError(f"Požadavek musí být Requirement, ne {type(req).__name__}.")
        if req.is_minimum and number != 1:
            with calc_context():
                scaled = req.value * number
            result.append(replace(req, value=scaled))
        else:
            result.append(req)
    return tuple(result)


def select_requirements(
    high_profile: StandardProfile, low_profile: StandardProfile, k_actual: Decimal | int | str
) -> SelectedRequirements:
    """Vybere sloupec standardu a přepočte minima na skutečný příjem energie (docs/06 §6.4).

    Pravidla (hranice jsou ``reference_k`` profilů, tedy data):
        - ``k_actual ≥ high.reference_k`` → vyšší sloupec, faktor 1,
        - ``low.reference_k ≤ k_actual < high.reference_k`` → nižší sloupec, faktor 1,
        - ``k_actual < low.reference_k`` → nižší sloupec, faktor
          ``low.reference_k / k_actual``.
    Faktor se použije **jen** na požadavky typu minimum (``MIN_RECOMMENDED``,
    ``MR``, ``AI``, ``RA``); maxima a poměry se nikdy nepřepočítávají. Při
    faktoru ≠ 1 nese výsledek upozornění ``REQUIREMENT_SCALING_NEEDS_REVIEW``
    (lineární přepočet musí potvrdit specialista 🩺).

    Vstup: profil vyššího a nižšího sloupce (:func:`check_profile_pair`) a
    skutečný koeficient zvířete (> 0, viz :func:`actual_k`).
    Výstup: :class:`SelectedRequirements`.
    Chyby: jako :func:`check_profile_pair`; ``TypeError`` pro ``float``;
    :class:`~nutricalc.errors.InvalidInputError` pro ``k_actual`` ≤ 0.
    """
    check_profile_pair(high_profile, low_profile)
    k = _positive(k_actual, "Skutečný koeficient k")
    flags: list[Flag] = []
    if k >= high_profile.reference_k:
        used = high_profile
        factor = Decimal(1)
    else:
        used = low_profile
        if k >= low_profile.reference_k:
            factor = Decimal(1)
        else:
            with calc_context():
                factor = low_profile.reference_k / k
            flags.append(
                Flag(
                    WarningLevel.NUTRITION_WARNING,
                    "REQUIREMENT_SCALING_NEEDS_REVIEW",
                    f"Skutečný příjem energie (k ≈ {round_significant(k, 4)}) je nižší než "
                    f"referenční hodnota sloupce ({low_profile.reference_k}). Požadavky typu "
                    f"minimum byly lineárně přepočteny faktorem ≈ {round_significant(factor, 4)}; "
                    "maxima zůstala beze změny. Lineární přepočet je pracovní návrh, který musí "
                    "potvrdit veterinární nutriční specialista.",
                )
            )
    return SelectedRequirements(
        profile_used=used,
        k_actual=k,
        min_scale_factor=factor,
        column_code=column_code(used),
        requirements=scale_minima(used.requirements, factor),
        flags=sorted_flags(flags),
    )


def daily_requirement(req: Requirement, der_kcal: Decimal | int | str) -> Quantity:
    """Denní požadavek pro zobrazení ``req_den = req_1000 · DER / 1000`` (docs/06 §6.4).

    Vstup: požadavek živiny (na 1000 kcal ME, případně už přepočtený) a
    denní energetická potřeba v kcal (> 0).
    Výstup: :class:`~nutricalc.units.Quantity` s bází ``PER_DAY``.
    Chyby: ``TypeError`` pro jiný typ;
    :class:`~nutricalc.errors.UnitMismatchError` pro poměr (na energii nezávisí);
    :class:`~nutricalc.errors.ValidationError` pro DER ≤ 0.
    """
    if not isinstance(req, Requirement):
        raise TypeError(f"daily_requirement očekává Requirement, ne {type(req).__name__}.")
    return per_1000kcal_to_per_day(req.quantity(), der_kcal)
