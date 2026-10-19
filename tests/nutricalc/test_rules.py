"""Deklarativní pravidla upozornění (docs/06 §6.7).

Pravidla, příznaky, kategorie a prahy jsou SYNTETICKÉ testovací fixtury.
"""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from nutricalc.errors import InvalidInputError, ValidationError
from nutricalc.evaluation import NutrientStatus
from nutricalc.rules import (
    Always,
    CategoryMassShareAbove,
    IngredientFlagPresent,
    NutrientStatusIn,
    RuleContext,
    RuleWarning,
    WarningRule,
    evaluate_rules,
    sorted_rules,
)
from nutricalc.vocab import Species, WarningLevel
from tests.nutricalc.synthetic import item, measured, profile

D = Decimal


def rule(
    code: str, condition: object, level: WarningLevel = WarningLevel.INFO, **extra: object
) -> WarningRule:
    return WarningRule(
        code=code,
        level=level,
        message_cs=f"Syntetické upozornění {code}.",
        source_key="TEST_FIXTURE",
        condition=condition,  # type: ignore[arg-type]
        **extra,  # type: ignore[arg-type]
    )


def recipe() -> tuple:
    return (
        item(
            profile("SYN_LIVER", {"P": measured("1")}, category="LIVER", safety_flags={"SYN_FLAG"}),
            "30",
        ),
        item(profile("SYN_MUSCLE", {"P": measured("1")}, category="MUSCLE"), "60"),
        item(
            profile(
                "SYN_BONE",
                {"P": measured("1")},
                category="MEATY_BONE",
                safety_flags={"SYN_FLAG", "BONE"},
            ),
            "10",
        ),
    )


def context(species: Species = Species.DOG, **statuses: set[NutrientStatus]) -> RuleContext:
    return RuleContext(
        species=species,
        items=recipe(),
        nutrient_statuses={code: frozenset(values) for code, values in statuses.items()},
    )


def test_no_rules_no_warnings() -> None:
    assert evaluate_rules((), context()) == ()


def test_always_rule() -> None:
    (warning,) = evaluate_rules([rule("RAW_DIET", Always())], context())
    assert warning == RuleWarning(
        level=WarningLevel.INFO,
        code="RAW_DIET",
        message_cs="Syntetické upozornění RAW_DIET.",
        source_key="TEST_FIXTURE",
        ingredient_codes=(),
    )


def test_ingredient_flag_lists_matching_ingredients_sorted() -> None:
    (warning,) = evaluate_rules(
        [rule("SYN_FLAG_RULE", IngredientFlagPresent("SYN_FLAG"))], context()
    )
    assert warning.ingredient_codes == ("SYN_BONE", "SYN_LIVER")
    assert evaluate_rules([rule("X", IngredientFlagPresent("ABSENT"))], context()) == ()


@pytest.mark.parametrize(
    ("share", "fires"),
    [("0.29", True), ("0.2999", True), ("0.3", False), ("0.31", False), ("0", True)],
)
def test_category_mass_share_is_strictly_above(share: str, fires: bool) -> None:
    # SYN_LIVER = 30 g ze 100 g = podíl 0,3
    warnings = evaluate_rules(
        [rule("LIVER_SHARE", CategoryMassShareAbove("LIVER", D(share)))], context()
    )
    assert bool(warnings) == fires
    if fires:
        assert warnings[0].ingredient_codes == ("SYN_LIVER",)


def test_category_absent_never_fires() -> None:
    assert evaluate_rules([rule("FISH", CategoryMassShareAbove("FISH", D(0)))], context()) == ()


def test_nutrient_status_condition_uses_all_statuses() -> None:
    condition = NutrientStatusIn("VIT_A", frozenset({NutrientStatus.ABOVE_LEGAL_MAX_INFO}))
    hit = context(VIT_A={NutrientStatus.BORDERLINE_MAX, NutrientStatus.ABOVE_LEGAL_MAX_INFO})
    assert len(evaluate_rules([rule("VIT_A_HIGH", condition)], hit)) == 1
    miss = context(VIT_A={NutrientStatus.ADEQUATE})
    assert evaluate_rules([rule("VIT_A_HIGH", condition)], miss) == ()
    assert evaluate_rules([rule("VIT_A_HIGH", condition)], context()) == ()


def test_species_filter() -> None:
    cat_only = rule("CAT_ONLY", Always(), species={Species.CAT})
    assert evaluate_rules([cat_only], context(Species.DOG)) == ()
    assert len(evaluate_rules([cat_only], context(Species.CAT))) == 1
    assert cat_only.species == frozenset({Species.CAT})


def test_warnings_are_sorted_and_independent_of_order() -> None:
    rules = [
        rule("B_INFO", Always()),
        rule("A_INFO", Always()),
        rule("Z_BLOCK", IngredientFlagPresent("BONE"), WarningLevel.BLOCKED),
        rule("M_EXPERT", Always(), WarningLevel.EXPERT_REQUIRED),
        rule("N_NUTRITION", Always(), WarningLevel.NUTRITION_WARNING),
    ]
    forward = evaluate_rules(rules, context())
    assert [w.code for w in forward] == ["Z_BLOCK", "M_EXPERT", "N_NUTRITION", "A_INFO", "B_INFO"]
    assert evaluate_rules(list(reversed(rules)), context()) == forward
    shuffled = RuleContext(species=Species.DOG, items=tuple(reversed(recipe())))
    assert evaluate_rules(rules, shuffled) == forward


def test_duplicate_rule_codes_are_rejected() -> None:
    with pytest.raises(ValidationError):
        evaluate_rules([rule("X", Always()), rule("X", Always())], context())
    with pytest.raises(ValidationError):
        sorted_rules([rule("X", Always()), rule("X", IngredientFlagPresent("BONE"))])


def test_sorted_rules() -> None:
    rules = [rule("B", Always()), rule("A", Always())]
    assert [r.code for r in sorted_rules(rules)] == ["A", "B"]
    with pytest.raises(TypeError):
        sorted_rules(["A"])  # type: ignore[list-item]


@pytest.mark.parametrize(
    ("factory", "error"),
    [
        (lambda: rule("bad code", Always()), ValidationError),
        (lambda: rule("X", Always(), species=set()), ValidationError),
        (lambda: rule("X", Always(), species="DOG"), TypeError),
        (lambda: rule("X", "ALWAYS"), TypeError),
        (lambda: rule("X", Always(), level="LOUD"), InvalidInputError),  # type: ignore[arg-type]
        (lambda: CategoryMassShareAbove("LIVER", 0.3), TypeError),  # type: ignore[arg-type]
        (lambda: CategoryMassShareAbove("LIVER", D("1.1")), InvalidInputError),
        (lambda: CategoryMassShareAbove("", D("0.1")), ValidationError),
        (lambda: NutrientStatusIn("CA", frozenset()), ValidationError),
        (lambda: NutrientStatusIn("CA", frozenset({"LOW"})), InvalidInputError),  # type: ignore[arg-type]
        (lambda: IngredientFlagPresent(""), ValidationError),
    ],
)
def test_invalid_rules(factory: object, error: type) -> None:
    with pytest.raises(error):
        factory()  # type: ignore[operator]


def test_conditions_are_frozen_and_carry_kind() -> None:
    condition = CategoryMassShareAbove("LIVER", D("0.1"))
    assert condition.kind == "CATEGORY_MASS_SHARE_ABOVE"
    assert Always().kind == "ALWAYS"
    with pytest.raises(FrozenInstanceError):
        condition.share = D(0)  # type: ignore[misc]


def test_evaluate_rules_type_errors() -> None:
    with pytest.raises(TypeError):
        evaluate_rules([rule("X", Always())], "context")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        evaluate_rules(["X"], context())  # type: ignore[list-item]


def test_context_and_condition_collections_are_checked() -> None:
    with pytest.raises(TypeError):
        NutrientStatusIn("CA", "ADEQUATE")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RuleContext(species=Species.DOG, items=recipe(), nutrient_statuses=[])  # type: ignore[arg-type]
