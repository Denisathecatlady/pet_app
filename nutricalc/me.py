"""Metabolizovatelná energie (ME) krmiva a dávky z makroživin (docs/06 §6.3).

Metody (:class:`~nutricalc.vocab.MeMethod`):

``NRC2006_DOG_CF`` – [NRC2006], stav ✅ S::

    GE  = 5,7·B + 9,4·T + 4,1·(BNLV + V)                [kcal]
    stravitelnost energie % = 91,2 − 1,43·V_DM%
    DE  = GE · stravitelnost / 100
    ME  = DE − 1,04·B

``NRC2006_DOG_TDF`` – [NRC2006], doporučeno [Calvez2019], stav ✅ S:
stravitelnost % = 96,6 − 0,95·TDF_DM%, ostatní kroky stejné. Hrubá
energie (GE) i zde používá BNLV + hrubou vlákninu V (docs/06 §6.3:
„ostatní stejně“; BNLV je definována dopočtem s hrubou vlákninou), TDF
vstupuje jen do stravitelnosti 🟡 (ověřit v originále NRC 2006).

``MOD_ATWATER`` – ME = 3,5·B + 8,5·T + 3,5·BNLV ([NRC2006], AAFCO; stav
🟡 *ověřit*: obecně známé faktory, v originále zatím neověřené).

``NRC2006_CAT`` – koeficienty pro kočky nejsou ověřené (docs/06 §6.3),
proto :class:`~nutricalc.errors.UnsupportedMethodError`.

B = bílkoviny (``PROTEIN``), T = tuk (``FAT``), BNLV = bezdusíkaté látky
výtažkové (``NFE``), V = hrubá vláknina (``CRUDE_FIBRE``), TDF = celková
vláknina (``TDF``); vše v gramech. Sušina = hmotnost − voda (``WATER``).

**ME dávky** se počítá z **denních součtů** makroživin celé dávky: rovnice
NRC jsou odvozené pro celé krmivo (stravitelnost závisí na podílu vlákniny
v sušině celé dávky), proto ME dávky obecně není součtem ME jednotlivých
surovin. ME jednotlivých surovin (``MeResult.per_item``) se počítá stejnou
metodou pro každou surovinu zvlášť a slouží **jen** k podílům surovin na
energii, nikdy k výpočtu ME dávky.

Vstupy makroživin jsou bodové hodnoty (``MEASURED``, ``CALCULATED``,
``BORROWED``, ``IMPUTED`` → v; ``ZERO_BY_DEFINITION`` → 0; ``BELOW_LOD``
a ``TRACE`` → 0 s upozorněním ``ME_BELOW_LOD_AS_ZERO``; ``MISSING`` →
chybí). Zacházení s chybějícími údaji popisuje :func:`ration_me`.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, NamedTuple

from nutricalc.composition import (
    LOD_KINDS,
    MEASURED_KINDS,
    IngredientProfile,
    RecipeItem,
    validate_items,
)
from nutricalc.decimal_ctx import calc_context, to_decimal, to_optional_decimal
from nutricalc.errors import (
    InvalidInputError,
    MissingDataError,
    SpeciesMismatchError,
    UnsupportedMethodError,
    ValidationError,
)
from nutricalc.flags import Flag, sorted_flags
from nutricalc.vocab import Completeness, MeMethod, Species, ValueKind, WarningLevel, as_member

# Kódy živin z data/reference/nutrients.csv.
PROTEIN: Final = "PROTEIN"
FAT: Final = "FAT"
NFE: Final = "NFE"
CRUDE_FIBRE: Final = "CRUDE_FIBRE"
TDF: Final = "TDF"
WATER: Final = "WATER"
ASH: Final = "ASH"

# --- koeficienty rovnic ---------------------------------------------------------------

# Hrubá energie: GE = 5,7·B + 9,4·T + 4,1·(BNLV + V) [kcal/g]:
# [NRC2006] (docs/06 §6.3), stav ✅ S.
NRC_GE_PROTEIN_KCAL_PER_G: Final = Decimal("5.7")
NRC_GE_FAT_KCAL_PER_G: Final = Decimal("9.4")
NRC_GE_CARBOHYDRATE_KCAL_PER_G: Final = Decimal("4.1")

# Stravitelnost energie psi, hrubá vláknina: 91,2 − 1,43·V_DM%:
# [NRC2006] (docs/06 §6.3), stav ✅ S.
NRC_DOG_CF_DIGESTIBILITY_INTERCEPT_PCT: Final = Decimal("91.2")
NRC_DOG_CF_DIGESTIBILITY_SLOPE: Final = Decimal("1.43")

# Stravitelnost energie psi, celková vláknina: 96,6 − 0,95·TDF_DM%:
# [NRC2006], doporučeno [Calvez2019] (docs/06 §6.3), stav ✅ S.
NRC_DOG_TDF_DIGESTIBILITY_INTERCEPT_PCT: Final = Decimal("96.6")
NRC_DOG_TDF_DIGESTIBILITY_SLOPE: Final = Decimal("0.95")

# Ztráta energie močí: ME = DE − 1,04·B [kcal/g bílkovin]:
# [NRC2006] (docs/06 §6.3), stav ✅ S.
NRC_ME_PROTEIN_CORRECTION_KCAL_PER_G: Final = Decimal("1.04")

# Modifikované Atwaterovy faktory 3,5 / 8,5 / 3,5 kcal/g:
# [NRC2006], AAFCO (docs/06 §6.3), stav 🟡 ověřit.
MOD_ATWATER_PROTEIN_KCAL_PER_G: Final = Decimal("3.5")
MOD_ATWATER_FAT_KCAL_PER_G: Final = Decimal("8.5")
MOD_ATWATER_NFE_KCAL_PER_G: Final = Decimal("3.5")

NRC_DOG_METHODS: Final = frozenset({MeMethod.NRC2006_DOG_CF, MeMethod.NRC2006_DOG_TDF})
"""Metody NRC 2006 pro psy (jen druh ``DOG``)."""

SUPPORTED_METHODS: Final = NRC_DOG_METHODS | {MeMethod.MOD_ATWATER}
"""Metody, které jádro v této verzi počítá."""

_ZERO: Final = Decimal(0)
_HUNDRED: Final = Decimal(100)

_DIGESTIBILITY: Final = {
    MeMethod.NRC2006_DOG_CF: (
        NRC_DOG_CF_DIGESTIBILITY_INTERCEPT_PCT,
        NRC_DOG_CF_DIGESTIBILITY_SLOPE,
    ),
    MeMethod.NRC2006_DOG_TDF: (
        NRC_DOG_TDF_DIGESTIBILITY_INTERCEPT_PCT,
        NRC_DOG_TDF_DIGESTIBILITY_SLOPE,
    ),
}

# --- rovnice ------------------------------------------------------------------------


def _grams(value: Decimal | int | str, name: str) -> Decimal:
    return to_decimal(value, name=name)


def _nrc_method(method: MeMethod | str) -> MeMethod:
    member = as_member(MeMethod, method, "metoda ME")
    if member not in NRC_DOG_METHODS:
        raise UnsupportedMethodError(
            f"Metoda {member} není rovnice NRC 2006 pro psy (povolené: "
            f"{', '.join(sorted(NRC_DOG_METHODS))})."
        )
    return member


def nrc_gross_energy_kcal(
    protein_g: Decimal | int | str,
    fat_g: Decimal | int | str,
    nfe_g: Decimal | int | str,
    crude_fibre_g: Decimal | int | str,
) -> Decimal:
    """Hrubá energie ``GE = 5,7·B + 9,4·T + 4,1·(BNLV + V)`` v kcal ([NRC2006], ✅ S).

    Vstup: gramy bílkovin, tuku, BNLV a hrubé vlákniny (nezáporné).
    Výstup: kcal. Chyby: ``TypeError`` pro ``float``;
    :class:`~nutricalc.errors.InvalidInputError` pro záporné číslo.
    """
    protein = _grams(protein_g, "Bílkoviny (g)")
    fat = _grams(fat_g, "Tuk (g)")
    nfe = _grams(nfe_g, "BNLV (g)")
    fibre = _grams(crude_fibre_g, "Hrubá vláknina (g)")
    with calc_context():
        return (
            NRC_GE_PROTEIN_KCAL_PER_G * protein
            + NRC_GE_FAT_KCAL_PER_G * fat
            + NRC_GE_CARBOHYDRATE_KCAL_PER_G * (nfe + fibre)
        )


def energy_digestibility_pct(method: MeMethod | str, fibre_dm_pct: Decimal | int | str) -> Decimal:
    """Stravitelnost energie v % podle metody NRC 2006 pro psy.

    ``NRC2006_DOG_CF``: ``91,2 − 1,43·V_DM%``; ``NRC2006_DOG_TDF``:
    ``96,6 − 0,95·TDF_DM%`` ([NRC2006], ✅ S).

    Vstup: metoda a podíl příslušné vlákniny v sušině v % (nezáporný).
    Výstup: % (může vyjít záporně, pokud je vlákniny extrémně mnoho; to
    hlídá volající).
    Chyby: :class:`~nutricalc.errors.UnsupportedMethodError` pro jinou metodu;
    :class:`~nutricalc.errors.InvalidInputError` pro záporný podíl.
    """
    member = _nrc_method(method)
    fibre = to_decimal(fibre_dm_pct, name="Vláknina (% sušiny)")
    intercept, slope = _DIGESTIBILITY[member]
    with calc_context():
        return intercept - slope * fibre


def fibre_percent_of_dm(
    fibre_g: Decimal | int | str, mass_g: Decimal | int | str, water_g: Decimal | int | str | None
) -> Decimal:
    """Podíl vlákniny v sušině v % (``vláknina · 100 / (hmotnost − voda)``).

    Vstup: gramy vlákniny, celková hmotnost v gramech a gramy vody (nebo
    ``None``, když obsah vody není známý). Při nulové vláknině se voda
    nepotřebuje a výsledek je 0.
    Výstup: % sušiny.
    Chyby: :class:`~nutricalc.errors.MissingDataError`, je-li vláknina > 0 a
    voda ``None``; :class:`~nutricalc.errors.ValidationError`, je-li vláknina
    > 0 a sušina ≤ 0 (rozporné údaje); ``InvalidInputError`` pro záporná čísla.
    """
    fibre = _grams(fibre_g, "Vláknina (g)")
    mass = _grams(mass_g, "Hmotnost (g)")
    water = to_optional_decimal(water_g, name="Voda (g)")
    if fibre.is_zero():
        return _ZERO
    if water is None:
        raise MissingDataError("Podíl vlákniny v sušině nelze spočítat bez obsahu vody (WATER).")
    with calc_context():
        dry_matter = mass - water
        if not dry_matter > 0:
            raise ValidationError(
                f"Sušina vychází {dry_matter} g, ale vláknina je {fibre} g. Údaje o vodě a "
                "vláknině si odporují; ověřte složení suroviny."
            )
        return fibre * _HUNDRED / dry_matter


@dataclass(frozen=True)
class NrcEnergy:
    """Mezivýsledky rovnice NRC 2006: GE, stravitelnost (%), DE a ME (kcal)."""

    ge_kcal: Decimal
    digestibility_pct: Decimal
    de_kcal: Decimal
    me_kcal: Decimal


def nrc2006_dog_energy(
    *,
    method: MeMethod | str,
    protein_g: Decimal | int | str,
    fat_g: Decimal | int | str,
    nfe_g: Decimal | int | str,
    crude_fibre_g: Decimal | int | str,
    fibre_dm_pct: Decimal | int | str,
) -> NrcEnergy:
    """Spočítá GE, stravitelnost, DE a ME podle NRC 2006 pro psy ([NRC2006], ✅ S).

    Vstup (pojmenované argumenty): metoda ``NRC2006_DOG_CF`` nebo
    ``NRC2006_DOG_TDF``; gramy bílkovin, tuku, BNLV a hrubé vlákniny (pro GE);
    podíl vlákniny metody v sušině v % (hrubá vláknina u ``_CF``, TDF
    u ``_TDF``; viz :func:`fibre_percent_of_dm`).
    Výstup: :class:`NrcEnergy`. Stravitelnost i ME mohou vyjít záporně mimo
    rozsah platnosti rovnice; rozhoduje o tom volající.
    Chyby: jako :func:`nrc_gross_energy_kcal` a :func:`energy_digestibility_pct`.
    """
    member = _nrc_method(method)
    protein = _grams(protein_g, "Bílkoviny (g)")
    ge = nrc_gross_energy_kcal(protein, fat_g, nfe_g, crude_fibre_g)
    digestibility = energy_digestibility_pct(member, fibre_dm_pct)
    with calc_context():
        de = ge * digestibility / _HUNDRED
        me = de - NRC_ME_PROTEIN_CORRECTION_KCAL_PER_G * protein
    return NrcEnergy(ge_kcal=ge, digestibility_pct=digestibility, de_kcal=de, me_kcal=me)


def mod_atwater_me_kcal(
    protein_g: Decimal | int | str, fat_g: Decimal | int | str, nfe_g: Decimal | int | str
) -> Decimal:
    """ME podle modifikovaných Atwaterových faktorů ``3,5·B + 8,5·T + 3,5·BNLV``.

    Zdroj: [NRC2006], AAFCO (docs/06 §6.3), stav 🟡 ověřit.
    Vstup: gramy bílkovin, tuku a BNLV (nezáporné). Výstup: kcal.
    Chyby: ``TypeError`` pro ``float``; ``InvalidInputError`` pro záporné číslo.
    """
    protein = _grams(protein_g, "Bílkoviny (g)")
    fat = _grams(fat_g, "Tuk (g)")
    nfe = _grams(nfe_g, "BNLV (g)")
    with calc_context():
        return (
            MOD_ATWATER_PROTEIN_KCAL_PER_G * protein
            + MOD_ATWATER_FAT_KCAL_PER_G * fat
            + MOD_ATWATER_NFE_KCAL_PER_G * nfe
        )


# --- vstupy surovin -----------------------------------------------------------------


@dataclass(frozen=True)
class _ItemInputs:
    """Makroživiny jedné položky v gramech za den (po zacházení s chybějícími údaji)."""

    code: str
    grams: Decimal
    protein: Decimal | None
    fat: Decimal | None
    nfe: Decimal
    crude_fibre: Decimal
    tdf: Decimal
    water: Decimal | None
    partial: bool


class _Resolver:
    """Bodové hodnoty makroživin jedné suroviny na 100 g a upozornění k nim."""

    def __init__(self, profile: IngredientProfile, flags: list[Flag]) -> None:
        self.profile = profile
        self.flags = flags

    def flag(self, level: WarningLevel, code: str, message: str) -> None:
        self.flags.append(Flag(level, code, message, subject=self.profile.ingredient_code))

    def point(self, nutrient: str) -> Decimal | None:
        nv = self.profile.get(nutrient)
        if nv.kind in MEASURED_KINDS:
            return nv.value
        if nv.kind == ValueKind.ZERO_BY_DEFINITION:
            return _ZERO
        if nv.kind in LOD_KINDS:
            self.flag(
                WarningLevel.INFO,
                "ME_BELOW_LOD_AS_ZERO",
                f"Surovina {self.profile.ingredient_code}: {nutrient} je pod mezí detekce nebo "
                "ve stopovém množství; pro výpočet ME se počítá jako 0.",
            )
            return _ZERO
        return None

    def nfe(
        self, protein: Decimal | None, fat: Decimal | None, water: Decimal | None
    ) -> Decimal | None:
        code = self.profile.ingredient_code
        if self.profile.get(NFE).kind != ValueKind.MISSING:
            return self.point(NFE)
        parts = {
            WATER: water,
            PROTEIN: protein,
            FAT: fat,
            ASH: self.point(ASH),
            CRUDE_FIBRE: self.point(CRUDE_FIBRE),
        }
        lacking = [name for name, value in parts.items() if value is None]
        if lacking:
            self.flag(
                WarningLevel.NUTRITION_WARNING,
                "ME_NFE_MISSING",
                f"Surovina {code}: chybí BNLV (NFE) a nelze ji dopočítat (chybí "
                f"{', '.join(lacking)}). BNLV se počítá jako 0, ME je proto neúplná (PARTIAL) "
                "a může být podhodnocená.",
            )
            return None
        with calc_context():
            computed = _HUNDRED - sum(
                (value for value in parts.values() if value is not None), _ZERO
            )
        self.flag(
            WarningLevel.INFO,
            "ME_NFE_CALCULATED",
            f"Surovina {code}: BNLV (NFE) dopočtena jako 100 − (voda + bílkoviny + tuk + popel "
            f"+ hrubá vláknina) = {computed} g/100 g.",
        )
        if computed < 0:
            self.flag(
                WarningLevel.INFO,
                "ME_NFE_NEGATIVE_CLAMPED",
                f"Surovina {code}: dopočet BNLV vyšel záporně ({computed} g/100 g), součet "
                "složek přesahuje 100 g. BNLV se počítá jako 0; ověřte složení suroviny.",
            )
            return _ZERO
        return computed


def _resolve(item: RecipeItem, method: MeMethod, flags: list[Flag]) -> _ItemInputs:
    resolver = _Resolver(item.profile, flags)
    code = item.ingredient_code
    protein = resolver.point(PROTEIN)
    fat = resolver.point(FAT)
    lacking = [name for name, value in ((PROTEIN, protein), (FAT, fat)) if value is None]
    if lacking:
        resolver.flag(
            WarningLevel.NUTRITION_WARNING,
            "ME_MACRONUTRIENT_MISSING",
            f"Surovina {code}: chybí {', '.join(lacking)}. ME suroviny ani dávky nelze "
            "spočítat (chybějící údaj se nenahrazuje nulou).",
        )
    water = resolver.point(WATER)
    if water is not None and water > _HUNDRED:
        raise ValidationError(f"Surovina {code}: obsah vody {water} g/100 g je větší než 100 g.")
    partial = False
    nfe = resolver.nfe(protein, fat, water)
    if nfe is None:
        partial = True
        nfe = _ZERO
    crude_fibre = _ZERO
    tdf = _ZERO
    if method in NRC_DOG_METHODS:
        value = resolver.point(CRUDE_FIBRE)
        if value is None:
            partial = True
            effect = (
                "stravitelnost a tím ME může být nadhodnocená"
                if method == MeMethod.NRC2006_DOG_CF
                else "hrubá energie (GE) a tím ME může být podhodnocená"
            )
            resolver.flag(
                WarningLevel.NUTRITION_WARNING,
                "ME_FIBRE_MISSING",
                f"Surovina {code}: chybí hrubá vláknina (CRUDE_FIBRE). Počítá se jako 0, ME je "
                f"proto neúplná (PARTIAL): {effect}.",
            )
        else:
            crude_fibre = value
        if method == MeMethod.NRC2006_DOG_TDF:
            value = resolver.point(TDF)
            if value is None:
                partial = True
                resolver.flag(
                    WarningLevel.NUTRITION_WARNING,
                    "ME_FIBRE_MISSING",
                    f"Surovina {code}: chybí celková vláknina (TDF). Počítá se jako 0, ME je "
                    "proto neúplná (PARTIAL): stravitelnost a tím ME může být nadhodnocená.",
                )
            else:
                tdf = value
    with calc_context():
        scale = item.grams / _HUNDRED
        return _ItemInputs(
            code=code,
            grams=item.grams,
            protein=None if protein is None else protein * scale,
            fat=None if fat is None else fat * scale,
            nfe=nfe * scale,
            crude_fibre=crude_fibre * scale,
            tdf=tdf * scale,
            water=None if water is None else water * scale,
            partial=partial,
        )


# --- ME suroviny a dávky ----------------------------------------------------------------


class ItemMe(NamedTuple):
    """ME jedné položky v kcal/den (jen pro podíly), nebo ``None``, když nejde spočítat."""

    ingredient_code: str
    kcal: Decimal | None


@dataclass(frozen=True)
class MeResult:
    """ME dávky a podklady pro podíly surovin.

    ``kcal``: ME dávky v kcal/den z denních součtů makroživin, nebo ``None``
    (``UNKNOWN``). ``completeness``: ``COMPLETE``, ``PARTIAL`` (některé BNLV
    nebo vláknina počítány jako 0 kvůli chybějícím údajům; ``kcal`` je pak jen
    přibližná hodnota, ne mez) nebo ``UNKNOWN``. ``per_item``: :class:`ItemMe`
    seřazené podle kódu suroviny. ``flags``: upozornění (podle
    :func:`~nutricalc.flags.sorted_flags`). ``method``: použitá metoda.
    """

    kcal: Decimal | None
    completeness: Completeness
    per_item: tuple[ItemMe, ...]
    flags: tuple[Flag, ...]
    method: MeMethod


def _check_method(method: MeMethod | str, species: Species | str) -> MeMethod:
    try:
        member = as_member(MeMethod, method, "metoda ME")
    except InvalidInputError as exc:
        raise UnsupportedMethodError(str(exc)) from None
    animal = as_member(Species, species, "druh")
    if member not in SUPPORTED_METHODS:
        raise UnsupportedMethodError(
            f"Metoda {member} v této verzi jádra není dostupná: koeficienty rovnice (NRC 2006 "
            "pro kočky) zatím nebyly ověřeny v originále (docs/06 §6.3)."
        )
    if member in NRC_DOG_METHODS and animal != Species.DOG:
        raise SpeciesMismatchError(f"Metoda {member} platí jen pro psy, zvíře je {animal}.")
    return member


@dataclass(frozen=True)
class _Totals:
    """Makroživiny v gramech pro jednu položku nebo celou dávku."""

    protein: Decimal
    fat: Decimal
    nfe: Decimal
    crude_fibre: Decimal
    method_fibre: Decimal
    mass: Decimal
    water: Decimal | None


def _nrc_energy(method: MeMethod, totals: _Totals) -> NrcEnergy:
    return nrc2006_dog_energy(
        method=method,
        protein_g=totals.protein,
        fat_g=totals.fat,
        nfe_g=totals.nfe,
        crude_fibre_g=totals.crude_fibre,
        fibre_dm_pct=fibre_percent_of_dm(totals.method_fibre, totals.mass, totals.water),
    )


def _method_fibre(method: MeMethod, inputs: _ItemInputs) -> Decimal:
    return inputs.crude_fibre if method == MeMethod.NRC2006_DOG_CF else inputs.tdf


def _out_of_range(energy: NrcEnergy) -> bool:
    return energy.digestibility_pct < 0 or energy.me_kcal < 0


def _item_me(inputs: _ItemInputs, method: MeMethod, flags: list[Flag]) -> Decimal | None:
    if inputs.protein is None or inputs.fat is None:
        return None
    if method == MeMethod.MOD_ATWATER:
        return mod_atwater_me_kcal(inputs.protein, inputs.fat, inputs.nfe)
    fibre = _method_fibre(method, inputs)
    if fibre > 0 and inputs.water is None:
        flags.append(
            Flag(
                WarningLevel.NUTRITION_WARNING,
                "ME_WATER_MISSING",
                f"Surovina {inputs.code}: chybí voda (WATER), bez které nelze vlákninu přepočítat "
                "na sušinu. ME suroviny nelze spočítat.",
                subject=inputs.code,
            )
        )
        return None
    totals = _Totals(
        protein=inputs.protein,
        fat=inputs.fat,
        nfe=inputs.nfe,
        crude_fibre=inputs.crude_fibre,
        method_fibre=fibre,
        mass=inputs.grams,
        water=inputs.water,
    )
    energy = _nrc_energy(method, totals)
    if _out_of_range(energy):
        flags.append(
            Flag(
                WarningLevel.INFO,
                "ME_EQUATION_OUT_OF_RANGE",
                f"Surovina {inputs.code}: rovnice {method} dává pro samotnou surovinu zápornou "
                "stravitelnost nebo ME (velmi vysoký podíl vlákniny). Podíl suroviny na energii "
                "nelze určit; ME dávky se počítá z celé dávky.",
                subject=inputs.code,
            )
        )
        return None
    return energy.me_kcal


def _ration_kcal(
    resolved: Sequence[_ItemInputs], method: MeMethod, flags: list[Flag]
) -> Decimal | None:
    proteins = [inputs.protein for inputs in resolved if inputs.protein is not None]
    fats = [inputs.fat for inputs in resolved if inputs.fat is not None]
    if len(proteins) < len(resolved) or len(fats) < len(resolved):
        return None
    with calc_context():
        protein = sum(proteins, _ZERO)
        fat = sum(fats, _ZERO)
        nfe = sum((inputs.nfe for inputs in resolved), _ZERO)
    if method == MeMethod.MOD_ATWATER:
        return mod_atwater_me_kcal(protein, fat, nfe)
    with calc_context():
        crude_fibre = sum((inputs.crude_fibre for inputs in resolved), _ZERO)
        fibre = sum((_method_fibre(method, inputs) for inputs in resolved), _ZERO)
        mass = sum((inputs.grams for inputs in resolved), _ZERO)
    water: Decimal | None = None
    if fibre > 0:
        lacking = [inputs.code for inputs in resolved if inputs.water is None]
        if lacking:
            flags.append(
                Flag(
                    WarningLevel.NUTRITION_WARNING,
                    "ME_WATER_MISSING",
                    f"ME dávky nelze spočítat: suroviny {', '.join(lacking)} nemají údaj o vodě "
                    "(WATER), takže vlákninu dávky nelze přepočítat na sušinu.",
                )
            )
            return None
        with calc_context():
            water = sum((inputs.water for inputs in resolved if inputs.water is not None), _ZERO)
    totals = _Totals(
        protein=protein,
        fat=fat,
        nfe=nfe,
        crude_fibre=crude_fibre,
        method_fibre=fibre,
        mass=mass,
        water=water,
    )
    energy = _nrc_energy(method, totals)
    if _out_of_range(energy):
        flags.append(
            Flag(
                WarningLevel.EXPERT_REQUIRED,
                "ME_EQUATION_OUT_OF_RANGE",
                f"ME dávky nelze spočítat: rovnice {method} dává zápornou stravitelnost nebo ME "
                "(podíl vlákniny v sušině dávky je mimo rozsah platnosti rovnice). Dávku musí "
                "posoudit odborník.",
            )
        )
        return None
    return energy.me_kcal


def ration_me(
    items: Iterable[RecipeItem], method: MeMethod | str, species: Species | str
) -> MeResult:
    """Spočítá ME dávky v kcal/den a ME jednotlivých položek pro podíly.

    Vstup: položky receptu (libovolné pořadí), metoda a druh zvířete.

    Zacházení s údaji (pro každou surovinu, docs/06 §6.3):
        - ``PROTEIN`` nebo ``FAT`` chybí → ME suroviny i dávky je neznámá
          (``ME_MACRONUTRIENT_MISSING``, ``kcal = None``, ``UNKNOWN``).
        - ``NFE`` známá → použije se; jinak se dopočte jako
          ``100 − (WATER + PROTEIN + FAT + ASH + CRUDE_FIBRE)`` na 100 g, jsou-li
          všechny složky známé (``ME_NFE_CALCULATED``; záporný výsledek → 0
          s ``ME_NFE_NEGATIVE_CLAMPED``); jinak se počítá jako 0 a výsledek je
          ``PARTIAL`` (``ME_NFE_MISSING``).
        - vláknina metody NRC (``CRUDE_FIBRE`` u ``_CF``; ``CRUDE_FIBRE`` pro
          GE a ``TDF`` pro stravitelnost u ``_TDF``) chybí → počítá se jako 0,
          výsledek ``PARTIAL`` (``ME_FIBRE_MISSING``; ME může být nadhodnocená).
        - podíl vlákniny v sušině potřebuje ``WATER``, je-li vláknina > 0; bez
          vody je ME neznámá (``ME_WATER_MISSING``).
        - rovnice NRC mimo rozsah platnosti (záporná stravitelnost nebo ME) →
          ME neznámá (``ME_EQUATION_OUT_OF_RANGE``).
        - ``BELOW_LOD`` a ``TRACE`` → 0 (``ME_BELOW_LOD_AS_ZERO``).

    ME dávky se počítá z denních součtů makroživin celé dávky; ME položek
    stejnou metodou pro každou položku zvlášť (jen pro podíly).

    Výstup: :class:`MeResult`; nezávisí na pořadí položek.

    Chyby: jako :func:`~nutricalc.composition.validate_items`;
    :class:`~nutricalc.errors.UnsupportedMethodError` pro ``NRC2006_CAT``
    nebo neznámou metodu; :class:`~nutricalc.errors.SpeciesMismatchError`
    pro metodu NRC pro psy u kočky; :class:`~nutricalc.errors.ValidationError`
    pro rozporné složení (voda > 100 g/100 g, vláknina bez sušiny).
    """
    member = _check_method(method, species)
    ordered = validate_items(items)
    flags: list[Flag] = []
    resolved = [_resolve(item, member, flags) for item in ordered]
    per_item = tuple(ItemMe(inputs.code, _item_me(inputs, member, flags)) for inputs in resolved)
    kcal = _ration_kcal(resolved, member, flags)
    if kcal is None:
        completeness = Completeness.UNKNOWN
    elif any(inputs.partial for inputs in resolved):
        completeness = Completeness.PARTIAL
    else:
        completeness = Completeness.COMPLETE
    return MeResult(
        kcal=kcal,
        completeness=completeness,
        per_item=per_item,
        flags=sorted_flags(flags),
        method=member,
    )
