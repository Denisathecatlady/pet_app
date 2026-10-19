"""Neměnný vstup rozboru, kanonický JSON a hash (docs/07 §7.2).

Suroviny, standard a pravidla jsou SYNTETICKÉ fixtury (SYN_*, TESTSTD).
"""

import json
from collections import namedtuple
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal
from types import MappingProxyType

import pytest

from nutricalc.errors import DuplicateItemError, InvalidInputError, ValidationError
from nutricalc.gate import HealthConditionRef
from nutricalc.rules import Always, WarningRule
from nutricalc.snapshot import (
    canonical_json,
    input_hash,
    sha256_hex,
    to_canonical,
)
from nutricalc.vocab import DataScope, MeMethod, QualityGrade, Species, WarningLevel
from tests.nutricalc.synthetic import (
    RULES_VERSION,
    analysis_input,
    animal,
    golden_items,
    item,
    syn_a,
    syn_b,
)

D = Decimal


def no_float(text: str) -> None:
    raise AssertionError(f"JSON obsahuje číslo s desetinnou tečkou: {text}")


def rule(code: str) -> WarningRule:
    return WarningRule(
        code=code,
        level=WarningLevel.INFO,
        message_cs="Syntetické upozornění.",
        source_key="TEST_FIXTURE",
        condition=Always(),
    )


# --- kanonický JSON -----------------------------------------------------------------------------


def test_canonical_json_format() -> None:
    text = canonical_json({"b": D("0.50"), "a": [QualityGrade.A, None, True, 3], "č": "žluť"})
    assert text == '{"a":["A",null,true,3],"b":"0.50","č":"žluť"}'


def test_decimal_is_kept_exactly_as_stored() -> None:
    assert to_canonical(D("0.50")) == "0.50"
    assert to_canonical(D("5.0")) == "5.0"
    assert to_canonical(D("1E+3")) == "1E+3"


def test_sets_are_sorted_tuples_keep_order() -> None:
    assert to_canonical(frozenset({"b", "a", "c"})) == ["a", "b", "c"]
    assert to_canonical({Species.DOG, Species.CAT}) == ["CAT", "DOG"]
    assert to_canonical(("b", "a")) == ["b", "a"]


def test_dataclasses_and_named_tuples_become_objects() -> None:
    Pair = namedtuple("Pair", ["left", "right"])
    assert to_canonical(Pair(D(1), "x")) == {"left": "1", "right": "x"}
    assert to_canonical(HealthConditionRef("SYN_CKD", WarningLevel.BLOCKED)) == {
        "code": "SYN_CKD",
        "mode": "BLOCKED",
    }
    assert to_canonical(MappingProxyType({Species.DOG: 1})) == {"DOG": 1}


@pytest.mark.parametrize("value", [1.5, {"a": 0.1}, [D(1), 2.0], (1j,), b"x", object(), {1: "x"}])
def test_unsupported_values_are_rejected(value: object) -> None:
    with pytest.raises(TypeError):
        canonical_json(value)


@pytest.mark.parametrize("value", [D("NaN"), D("Infinity")])
def test_non_finite_decimal_is_rejected(value: Decimal) -> None:
    with pytest.raises(InvalidInputError):
        canonical_json(value)


def test_exclude_top_level_fields() -> None:
    condition = HealthConditionRef("SYN_CKD", WarningLevel.BLOCKED)
    assert canonical_json(condition, exclude=frozenset({"mode"})) == '{"code":"SYN_CKD"}'


def test_sha256_hex() -> None:
    assert sha256_hex("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert len(sha256_hex("žluť")) == 64
    with pytest.raises(TypeError):
        sha256_hex(b"abc")  # type: ignore[arg-type]


def test_snapshot_json_is_complete_and_float_free() -> None:
    text = canonical_json(analysis_input())
    data = json.loads(text, parse_float=no_float)
    assert set(data) == {
        "animal",
        "items",
        "energy_factor",
        "high_profile",
        "low_profile",
        "me_method",
        "warning_rules",
        "confidence_threshold",
        "data_versions",
        "engine_version",
    }
    assert [entry["profile"]["ingredient_code"] for entry in data["items"]] == ["SYN_A", "SYN_B"]
    assert data["items"][0]["grams"] == "300"
    assert data["data_versions"] == [
        ["ENERGY", "test-1"],
        ["INGREDIENTS", "syn-1"],
        ["STANDARDS", "teststd-1"],
    ]


# --- hash vstupu ----------------------------------------------------------------------------------


def test_input_hash_ignores_input_order() -> None:
    base = analysis_input(
        warning_rules=(rule("A_RULE"), rule("B_RULE")),
        data_versions=(
            ("INGREDIENTS", "syn-1"),
            ("STANDARDS", "teststd-1"),
            ("ENERGY", "test-1"),
            ("RULES", RULES_VERSION),
        ),
        animal=animal(
            health_conditions=(
                HealthConditionRef("SYN_B", WarningLevel.EXPERT_REQUIRED),
                HealthConditionRef("SYN_A", WarningLevel.EXPERT_REQUIRED),
            )
        ),
    )
    permuted = analysis_input(
        items=tuple(reversed(golden_items())),
        warning_rules=(rule("B_RULE"), rule("A_RULE")),
        data_versions=(
            ("RULES", RULES_VERSION),
            ("ENERGY", "test-1"),
            ("STANDARDS", "teststd-1"),
            ("INGREDIENTS", "syn-1"),
        ),
        animal=animal(
            health_conditions=(
                HealthConditionRef("SYN_A", WarningLevel.EXPERT_REQUIRED),
                HealthConditionRef("SYN_B", WarningLevel.EXPERT_REQUIRED),
            )
        ),
    )
    assert permuted == base
    assert input_hash(permuted) == input_hash(base)
    assert [entry.ingredient_code for entry in permuted.items] == ["SYN_A", "SYN_B"]
    assert [c.code for c in permuted.animal.health_conditions] == ["SYN_A", "SYN_B"]


@pytest.mark.parametrize(
    "change",
    [
        {"me_method": MeMethod.MOD_ATWATER},
        {"items": (item(syn_a(), "300.1"), item(syn_b(), "50"))},
        {"confidence_threshold": D("0.2")},
        {
            "data_versions": (
                ("INGREDIENTS", "syn-2"),
                ("STANDARDS", "teststd-1"),
                ("ENERGY", "test-1"),
            )
        },
        {"animal": animal(bcs=4)},
    ],
)
def test_input_hash_changes_with_content(change: dict[str, object]) -> None:
    # docs/11: metoda ME je součástí hashe; změna verze dat = nový hash
    assert input_hash(analysis_input(**change)) != input_hash(analysis_input())


def test_input_hash_is_stable() -> None:
    assert input_hash(analysis_input()) == input_hash(analysis_input())
    with pytest.raises(TypeError):
        input_hash("snapshot")  # type: ignore[arg-type]


# --- validace snapshotu --------------------------------------------------------------------------


def test_analysis_input_is_frozen() -> None:
    inp = analysis_input()
    with pytest.raises(FrozenInstanceError):
        inp.engine_version = "9.9.9"  # type: ignore[misc]


def test_duplicate_or_empty_items_are_rejected() -> None:
    with pytest.raises(DuplicateItemError):
        analysis_input(items=(item(syn_a(), "300"), item(syn_a(), "10")))
    with pytest.raises(ValidationError):
        analysis_input(items=())


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"confidence_threshold": 0.1}, TypeError),
        ({"confidence_threshold": D("1.1")}, InvalidInputError),
        ({"confidence_threshold": D("-0.1")}, InvalidInputError),
        ({"me_method": "ATWATER_4_9_4"}, InvalidInputError),
        ({"data_versions": (("STANDARDS", "a"), ("STANDARDS", "b"))}, ValidationError),
        ({"data_versions": (("RECIPES", "a"),)}, InvalidInputError),
        ({"data_versions": (("STANDARDS", ""),)}, ValidationError),
        ({"data_versions": (["STANDARDS", "a"],)}, TypeError),
        ({"data_versions": "STANDARDS"}, TypeError),
        ({"warning_rules": (rule("X"), rule("X"))}, ValidationError),
        ({"warning_rules": rule("X")}, TypeError),
        ({"animal": "DOG"}, TypeError),
        ({"energy_factor": "k110"}, TypeError),
        ({"high_profile": None}, TypeError),
        ({"items": item(syn_a(), "1")}, TypeError),
        ({"engine_version": ""}, ValidationError),
    ],
)
def test_analysis_input_validation(change: dict[str, object], error: type) -> None:
    with pytest.raises(error):
        analysis_input(**change)


def test_data_versions_accept_mapping() -> None:
    inp = analysis_input(
        data_versions={"STANDARDS": "teststd-1", "ENERGY": "test-1", "INGREDIENTS": "syn-1"}
    )
    assert inp.data_versions == analysis_input().data_versions
    assert inp.data_versions_map[DataScope.ENERGY] == "test-1"


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"bcs": 0}, InvalidInputError),
        ({"bcs": 10}, InvalidInputError),
        ({"bcs": True}, TypeError),
        ({"bcs": 5.0}, TypeError),
        ({"body_weight_kg": 20.0}, TypeError),
        ({"neutered": 1}, TypeError),
        ({"life_stage": "ADULT"}, InvalidInputError),
        (
            {
                "health_conditions": (
                    HealthConditionRef("SYN_CKD", WarningLevel.BLOCKED),
                    HealthConditionRef("SYN_CKD", WarningLevel.EXPERT_REQUIRED),
                )
            },
            ValidationError,
        ),
        ({"health_conditions": ("SYN_CKD",)}, TypeError),
        ({"health_conditions": HealthConditionRef("SYN_CKD", WarningLevel.BLOCKED)}, TypeError),
    ],
)
def test_animal_snapshot_validation(change: dict[str, object], error: type) -> None:
    with pytest.raises(error):
        animal(**change)


def test_animal_snapshot_normalizes_values() -> None:
    snapshot = animal(body_weight_kg="20.5", species="DOG", bcs=None)
    assert snapshot.body_weight_kg == D("20.5") and snapshot.species is Species.DOG
    assert replace(snapshot, bcs=4).bcs == 4
