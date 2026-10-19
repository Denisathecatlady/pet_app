"""Rozbor dávky od neměnného snapshotu po souhrn (docs/06 §6.1 a §6.9).

:func:`analyze_recipe` spojuje moduly jádra v pevném pořadí:

1. validace vstupu (verze jádra, druh, dvojice sloupců, fáze, verze dat),
2. odhad energetické potřeby (:func:`nutricalc.energy.estimate_energy`),
3. ME dávky (:func:`nutricalc.me.ration_me`),
4. denní součty všech živin z požadavků a povinných živin
   (:func:`nutricalc.composition.sum_nutrient`, jednotky z požadavků),
5. obsah na 1000 kcal ME a podíl energie surovin bez údaje,
6. výběr sloupce a přepočet minim (:func:`nutricalc.requirements.select_requirements`),
7. vyhodnocení živin a poměru Ca:P (:mod:`nutricalc.evaluation`),
8. spolehlivost, pravidla upozornění, bezpečnostní brána a souhrn.

Situace v datech (chybějící údaje, blokace) jsou součástí výsledku, nikdy
výjimkou. Výjimky vznikají jen pro neplatný vstup (docs/06 §6.9). Výsledek
neobsahuje čas výpočtu; ``result_hash`` je SHA-256 kanonického JSON
výsledku bez pole ``result_hash``.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Final

from nutricalc import ENGINE_VERSION
from nutricalc.composition import NutrientTotal, sum_nutrient
from nutricalc.decimal_ctx import calc_context
from nutricalc.energy import EnergyEstimate, EnergyInput, estimate_energy
from nutricalc.errors import SpeciesMismatchError, ValidationError
from nutricalc.evaluation import (
    CA_P,
    CALCIUM,
    PHOSPHORUS,
    RATIO_COMPONENTS,
    NutrientEvaluation,
    NutrientInterval,
    NutrientStatus,
    QualityContributor,
    RatioEvaluation,
    RatioInterval,
    Summary,
    confidence,
    evaluate_nutrient,
    evaluate_ratio,
    no_data_evaluation,
    per_1000kcal_interval,
    profile_label,
    ratio_interval,
    summarize,
)
from nutricalc.flags import Flag, sorted_flags
from nutricalc.gate import GateResult, evaluate_gate
from nutricalc.me import ItemMe, MeResult, ration_me
from nutricalc.requirements import (
    Requirement,
    SelectedColumn,
    SelectedRequirements,
    actual_k,
    check_profile_pair,
    select_requirements,
)
from nutricalc.rules import RuleContext, RuleWarning, evaluate_rules
from nutricalc.snapshot import AnalysisInput, canonical_json, input_hash, sha256_hex
from nutricalc.vocab import (
    Completeness,
    DataScope,
    GateStatus,
    QualityGrade,
    Unit,
    WarningLevel,
)

# Ca a P mají kanonickou jednotku g (docs/06 §6.2). Použije se jen tehdy, když
# profil požaduje poměr Ca:P, ale pro Ca nebo P samotné žádný požadavek nemá.
RATIO_COMPONENT_UNIT: Final = Unit.G

_ZERO: Final = Decimal(0)
_HUNDRED: Final = Decimal(100)
_UNCONDITIONAL: Final = ""


@dataclass(frozen=True, kw_only=True)
class NutrientResult:
    """Výsledek jedné živiny.

    ``nutrient_code``, ``unit`` – kód a kanonická jednotka.
    ``total`` – denní součet s intervalem, úplností, podílem hmotnosti bez
    údaje a příspěvky surovin (:class:`~nutricalc.composition.NutrientTotal`).
    ``per_1000kcal`` – obsah na 1000 kcal ME, nebo ``None``, když ME dávky
    není známá a kladná.
    ``missing_energy_share`` – podíl energie surovin (ME položek) bez údaje
    o živině (0–1), nebo ``None``, když ME některé položky nelze spočítat.
    ``requirements`` – použité přepočtené požadavky (prázdné při blokaci).
    ``evaluation`` – vyhodnocení, nebo ``None`` při blokaci.
    ``confidence`` – spolehlivost A–D, nebo ``None`` bez známého příspěvku.
    """

    nutrient_code: str
    unit: Unit
    total: NutrientTotal
    per_1000kcal: NutrientInterval | None
    missing_energy_share: Decimal | None
    requirements: tuple[Requirement, ...]
    evaluation: NutrientEvaluation | None
    confidence: QualityGrade | None

    @property
    def status(self) -> NutrientStatus | None:
        """Hlavní stav živiny, nebo ``None`` bez vyhodnocení (blokace)."""
        return None if self.evaluation is None else self.evaluation.status


@dataclass(frozen=True, kw_only=True)
class RatioResult:
    """Výsledek poměru (Ca:P).

    ``interval`` – poměr denních součtů, nebo ``None``, když ho nelze spočítat
    (Ca nebo P není ``COMPLETE``, dolní mez P je 0).
    ``evaluation`` – vyhodnocení proti ``RATIO_MIN``/``RATIO_MAX``, nebo
    ``None`` při blokaci.
    """

    nutrient_code: str
    numerator_code: str
    denominator_code: str
    interval: RatioInterval | None
    evaluation: RatioEvaluation | None

    @property
    def status(self) -> NutrientStatus | None:
        """Hlavní stav poměru, nebo ``None`` bez vyhodnocení."""
        return None if self.evaluation is None else self.evaluation.status


@dataclass(frozen=True, kw_only=True)
class AnalysisResult:
    """Neměnný výsledek rozboru (docs/06 §6.9).

    ``energy`` – odhad energetické potřeby (DER = ``energy.kcal_point``).
    ``me`` – ME dávky a ME položek.
    ``energy_deviation_pct`` – odchylka ME dávky od DER v %
    (``(ME − DER) / DER · 100``), nebo ``None``.
    ``nutrients`` – :class:`NutrientResult` seřazené podle kódu živiny.
    ``ratios`` – :class:`RatioResult` (Ca:P).
    ``warnings`` – upozornění pravidel (:class:`~nutricalc.rules.RuleWarning`).
    ``flags`` – upozornění rozboru (ME, přepočet požadavků, podmíněné požadavky).
    ``gate`` – bezpečnostní brána. ``summary`` – souhrn.
    ``selected_column`` – použitý sloupec standardu, nebo ``None`` (blokace).
    ``input_hash``, ``result_hash`` – SHA-256 (hex) vstupu a výsledku.
    ``engine_version``, ``data_versions`` – verze jádra a dat.
    """

    energy: EnergyEstimate
    me: MeResult
    energy_deviation_pct: Decimal | None
    nutrients: tuple[NutrientResult, ...]
    ratios: tuple[RatioResult, ...]
    warnings: tuple[RuleWarning, ...]
    flags: tuple[Flag, ...]
    gate: GateResult
    summary: Summary
    selected_column: SelectedColumn | None
    input_hash: str
    result_hash: str
    engine_version: str
    data_versions: tuple[tuple[DataScope, str], ...]

    def nutrient(self, nutrient_code: str) -> NutrientResult:
        """Výsledek živiny podle kódu. Chyby: ``KeyError`` pro neznámý kód."""
        for result in self.nutrients:
            if result.nutrient_code == nutrient_code:
                return result
        raise KeyError(nutrient_code)

    def ratio(self, nutrient_code: str = CA_P) -> RatioResult:
        """Výsledek poměru podle kódu. Chyby: ``KeyError`` pro neznámý kód."""
        for result in self.ratios:
            if result.nutrient_code == nutrient_code:
                return result
        raise KeyError(nutrient_code)


def result_hash(result: AnalysisResult) -> str:
    """SHA-256 kanonického JSON výsledku bez pole ``result_hash`` (docs/07 §7.2).

    Chyby: ``TypeError`` pro jiný typ než :class:`AnalysisResult`.
    """
    if not isinstance(result, AnalysisResult):
        raise TypeError(f"result_hash očekává AnalysisResult, ne {type(result).__name__}.")
    return sha256_hex(canonical_json(result, exclude=frozenset({"result_hash"})))


# --- validace -----------------------------------------------------------------------------------


def _validate(inp: AnalysisInput) -> None:
    if inp.engine_version != ENGINE_VERSION:
        raise ValidationError(
            f"Snapshot je pro verzi jádra {inp.engine_version}, toto jádro má verzi "
            f"{ENGINE_VERSION}. Rozbor přepočítejte jádrem stejné verze."
        )
    species = inp.animal.species
    for label, other in (
        ("Koeficient energie", inp.energy_factor.species),
        ("Vyšší sloupec standardu", inp.high_profile.species),
        ("Nižší sloupec standardu", inp.low_profile.species),
    ):
        if other != species:
            raise SpeciesMismatchError(
                f"{label} platí pro druh {other}, zvíře je {species}. Použijte data pro "
                "správný druh."
            )
    check_profile_pair(inp.high_profile, inp.low_profile)
    stages = (inp.high_profile.life_stage, inp.low_profile.life_stage)
    if inp.animal.life_stage not in stages:
        raise SpeciesMismatchError(
            f"Zvíře patří do fáze {inp.animal.life_stage}, standard je pro fáze "
            f"{stages[0]} a {stages[1]}. Profil pro jinou fázi nelze použít."
        )
    versions = inp.data_versions_map
    expected = {
        DataScope.STANDARDS: inp.high_profile.data_version,
        DataScope.ENERGY: inp.energy_factor.data_version,
    }
    if inp.low_profile.data_version != inp.high_profile.data_version:
        raise ValidationError(
            f"Sloupce standardu jsou z různých verzí dat ({inp.high_profile.data_version} a "
            f"{inp.low_profile.data_version})."
        )
    for scope, label in expected.items():
        if versions.get(scope) != label:
            raise ValidationError(
                f"Verze dat {scope} ve snapshotu ({versions.get(scope, 'chybí')}) neodpovídá "
                f"použitým datům ({label})."
            )
    if DataScope.INGREDIENTS not in versions:
        raise ValidationError("Snapshot neuvádí verzi dat surovin (INGREDIENTS).")
    if inp.warning_rules and DataScope.RULES not in versions:
        raise ValidationError("Snapshot obsahuje pravidla, ale neuvádí jejich verzi (RULES).")


# --- pomocné výpočty ----------------------------------------------------------------------------


def _nutrient_units(inp: AnalysisInput) -> tuple[dict[str, Unit], bool]:
    units: dict[str, Unit] = {}
    ratios: set[str] = set()
    for profile in (inp.high_profile, inp.low_profile):
        for req in profile.requirements:
            if req.is_ratio:
                ratios.add(req.nutrient_code)
            else:
                units.setdefault(req.nutrient_code, req.unit)
    unknown = sorted(ratios - set(RATIO_COMPONENTS))
    if unknown:
        raise ValidationError(
            f"Poměry {', '.join(unknown)} jádro neumí spočítat (zná: {', '.join(RATIO_COMPONENTS)})."
        )
    needs_ratio = CA_P in ratios or (CALCIUM in units and PHOSPHORUS in units)
    if needs_ratio:
        for code in RATIO_COMPONENTS[CA_P]:
            units.setdefault(code, RATIO_COMPONENT_UNIT)
        numerator, denominator = RATIO_COMPONENTS[CA_P]
        if units[numerator] != units[denominator]:
            raise ValidationError(
                f"Poměr {CA_P} vyžaduje stejnou jednotku {numerator} a {denominator}; požadavky "
                f"standardu je uvádějí v {units[numerator]} a {units[denominator]}."
            )
    return units, needs_ratio


def _missing_energy_share(total: NutrientTotal, per_item: tuple[ItemMe, ...]) -> Decimal | None:
    if any(entry.kcal is None for entry in per_item):
        return None
    known = {contributor.ingredient_code for contributor in total.contributors}
    with calc_context():
        energy = sum((entry.kcal for entry in per_item if entry.kcal is not None), _ZERO)
        missing = sum(
            (
                entry.kcal
                for entry in per_item
                if entry.kcal is not None and entry.ingredient_code not in known
            ),
            _ZERO,
        )
        if not energy > 0:
            return None
        return _ZERO if missing.is_zero() else missing / energy


def _confidence(inp: AnalysisInput, total: NutrientTotal) -> QualityGrade | None:
    profiles = {entry.ingredient_code: entry.profile for entry in inp.items}
    return confidence(
        (
            QualityContributor(
                contributor.ingredient_code,
                contributor.upper,
                profiles[contributor.ingredient_code].get(total.nutrient_code).quality,
            )
            for contributor in total.contributors
        ),
        inp.confidence_threshold,
    )


def _split(
    selected: SelectedRequirements | None, code: str
) -> tuple[tuple[Requirement, ...], tuple[str, ...]]:
    if selected is None:
        return (), ()
    reqs = selected.for_nutrient(code)
    used = tuple(req for req in reqs if req.condition_note == _UNCONDITIONAL)
    notes = tuple(sorted({req.condition_note for req in reqs} - {_UNCONDITIONAL}))
    return used, notes


def _condition_flag(code: str, notes: tuple[str, ...]) -> Flag:
    return Flag(
        WarningLevel.INFO,
        "REQUIREMENT_CONDITION_NOT_APPLIED",
        f"Živina {code}: požadavky s podmínkou ({'; '.join(notes)}) se automaticky "
        "nevyhodnocují. Zda podmínka platí, posoudí odborník.",
        subject=code,
    )


def _me_flags(me: MeResult, usable: bool) -> list[Flag]:
    if not usable:
        return [
            Flag(
                WarningLevel.NUTRITION_WARNING,
                "ME_NOT_AVAILABLE",
                "Energii dávky (ME) nelze určit nebo není kladná. Obsah živin na 1000 kcal ani "
                "porovnání se standardem proto nelze spočítat: živiny jsou „nelze vyhodnotit“.",
            )
        ]
    if me.completeness == Completeness.PARTIAL:
        return [
            Flag(
                WarningLevel.NUTRITION_WARNING,
                "ME_PARTIAL",
                "ME dávky je jen přibližná (chybějící BNLV nebo vláknina se počítaly jako 0), "
                "proto je přibližný i obsah živin na 1000 kcal.",
            )
        ]
    return []


# --- rozbor -------------------------------------------------------------------------------------


def analyze_recipe(inp: AnalysisInput) -> AnalysisResult:
    """Provede celý rozbor dávky (docs/06 §6.1).

    Vstup: :class:`~nutricalc.snapshot.AnalysisInput`.

    Postup a pravidla:
        - živiny = všechny kódy z požadavků obou sloupců (bez poměrů); jednotka
          z požadavků; při požadavku na Ca:P nebo při požadavcích na Ca i P se
          počítají i součty Ca a P a poměr,
        - obsah na 1000 kcal z ME dávky; je-li ME neznámá nebo ≤ 0, jsou
          všechny živiny ``NOT_EVALUABLE`` (upozornění ``ME_NOT_AVAILABLE``),
        - sloupec standardu podle ``k_skut = DER / BW^n`` (DER = bodový odhad
          energie); minima se přepočtou, maxima ne,
        - vyhodnocují se požadavky bez podmínky; podmíněné požadavky dostanou
          upozornění ``REQUIREMENT_CONDITION_NOT_APPLIED``,
        - bezpečnostní brána ``BLOCKED``: výsledek obsahuje popisné součty,
          obsah na 1000 kcal a poměr, ale žádné požadavky, stavy ani
          upozornění pravidel podle stavů živin; souhrn ``BLOCKED``.

    Výstup: :class:`AnalysisResult`; stejný vstup dává stejný výsledek
    i hash nezávisle na pořadí položek.

    Chyby (jen neplatný vstup, docs/06 §6.9): ``TypeError`` pro jiný typ;
    :class:`~nutricalc.errors.ValidationError` pro jinou verzi jádra,
    nesoulad verzí dat, profily různých standardů nebo neznámý poměr;
    :class:`~nutricalc.errors.SpeciesMismatchError` pro data jiného druhu
    nebo fáze; výjimky :func:`~nutricalc.energy.estimate_energy`
    (nevěrohodná hmotnost) a :func:`~nutricalc.me.ration_me` (neověřená
    metoda, rozporné složení).
    """
    if not isinstance(inp, AnalysisInput):
        raise TypeError(f"analyze_recipe očekává AnalysisInput, ne {type(inp).__name__}.")
    _validate(inp)
    animal = inp.animal
    energy = estimate_energy(
        EnergyInput(
            species=animal.species,
            body_weight_kg=animal.body_weight_kg,
            physiological_state=animal.physiological_state,
            bcs=animal.bcs,
            neutered=animal.neutered,
            factor=inp.energy_factor,
        )
    )
    me = ration_me(inp.items, inp.me_method, animal.species)
    usable_kcal = me.kcal if me.kcal is not None and me.kcal > 0 else None
    units, needs_ratio = _nutrient_units(inp)
    totals = {code: sum_nutrient(inp.items, code, units[code]) for code in sorted(units)}

    selected: SelectedRequirements | None = None
    if energy.kcal_point is not None:
        k = actual_k(energy.kcal_point, animal.body_weight_kg, animal.species)
        selected = select_requirements(inp.high_profile, inp.low_profile, k)

    evaluation_flags: list[Flag] = [] if selected is None else list(selected.flags)
    nutrients: list[NutrientResult] = []
    for code, total in totals.items():
        interval = None if usable_kcal is None else per_1000kcal_interval(total, usable_kcal)
        used, notes = _split(selected, code)
        evaluation = None
        if selected is not None:
            evaluation = (
                evaluate_nutrient(interval, used)
                if interval is not None
                else no_data_evaluation(code, used)
            )
            if notes:
                evaluation_flags.append(_condition_flag(code, notes))
        nutrients.append(
            NutrientResult(
                nutrient_code=code,
                unit=total.unit,
                total=total,
                per_1000kcal=interval,
                missing_energy_share=_missing_energy_share(total, me.per_item),
                requirements=used,
                evaluation=evaluation,
                confidence=_confidence(inp, total),
            )
        )

    ratios: list[RatioResult] = []
    if needs_ratio:
        numerator, denominator = RATIO_COMPONENTS[CA_P]
        used, notes = _split(selected, CA_P)
        ratio_evaluation = None
        if selected is not None:
            ratio_evaluation = evaluate_ratio(totals[numerator], totals[denominator], used)
            if notes:
                evaluation_flags.append(_condition_flag(CA_P, notes))
        ratios.append(
            RatioResult(
                nutrient_code=CA_P,
                numerator_code=numerator,
                denominator_code=denominator,
                interval=ratio_interval(totals[numerator], totals[denominator]),
                evaluation=ratio_evaluation,
            )
        )

    statuses = {
        result.nutrient_code: frozenset(result.evaluation.all_statuses)
        for result in nutrients
        if result.evaluation is not None
    }
    statuses.update(
        (ratio.nutrient_code, frozenset(ratio.evaluation.all_statuses))
        for ratio in ratios
        if ratio.evaluation is not None
    )
    context = RuleContext(species=animal.species, items=inp.items, nutrient_statuses=statuses)
    warnings = evaluate_rules(inp.warning_rules, context)
    gate = evaluate_gate(
        animal.physiological_state, animal.bcs, animal.health_conditions, energy, warnings
    )

    mandatory_all = inp.high_profile.mandatory_nutrients | inp.low_profile.mandatory_nutrients
    if gate.status == GateStatus.BLOCKED or selected is None:
        if gate.status == GateStatus.BLOCKED:
            nutrients = [replace(result, requirements=(), evaluation=None) for result in nutrients]
            ratios = [replace(ratio, evaluation=None) for ratio in ratios]
            warnings = evaluate_rules(
                inp.warning_rules, RuleContext(species=animal.species, items=inp.items)
            )
            evaluation_flags = []
        summary = summarize(
            gate.status, {}, mandatory_all, {}, standard_label=profile_label(inp.high_profile)
        )
        column = None
    else:
        primary = {
            result.nutrient_code: result.evaluation.status
            for result in nutrients
            if result.evaluation is not None
        }
        primary.update(
            (ratio.nutrient_code, ratio.evaluation.status)
            for ratio in ratios
            if ratio.evaluation is not None
        )
        maxima = {
            result.nutrient_code: tuple(req.requirement_type for req in result.requirements)
            for result in nutrients
        }
        summary = summarize(
            gate.status,
            primary,
            selected.profile_used.mandatory_nutrients,
            maxima,
            standard_label=profile_label(selected.profile_used),
        )
        column = selected.column

    deviation = None
    if me.kcal is not None and energy.kcal_point is not None:
        with calc_context():
            deviation = (me.kcal - energy.kcal_point) / energy.kcal_point * _HUNDRED

    result = AnalysisResult(
        energy=energy,
        me=me,
        energy_deviation_pct=deviation,
        nutrients=tuple(nutrients),
        ratios=tuple(ratios),
        warnings=warnings,
        flags=sorted_flags([*_me_flags(me, usable_kcal is not None), *evaluation_flags]),
        gate=gate,
        summary=summary,
        selected_column=column,
        input_hash=input_hash(inp),
        result_hash="",
        engine_version=ENGINE_VERSION,
        data_versions=inp.data_versions,
    )
    return replace(result, result_hash=result_hash(result))
