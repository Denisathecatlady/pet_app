"""Slovníky jádra, shoda s ``refdata.vocab`` a upozornění (Flag).

Testy smí importovat ``refdata``; balíček ``nutricalc`` ne (hlídá statický test).
"""

from dataclasses import FrozenInstanceError
from decimal import Decimal
from enum import StrEnum

import pytest

from nutricalc import vocab
from nutricalc.errors import InvalidInputError, ValidationError
from nutricalc.flags import Flag, sorted_flags
from nutricalc.vocab import (
    METABOLIC_BASIS,
    METABOLIC_EXPONENT,
    Basis,
    QualityGrade,
    Species,
    Unit,
    WarningLevel,
    as_member,
    require_text,
    worst_quality,
)
from refdata import vocab as refdata_vocab


def _values(enum_type: type[StrEnum]) -> set[str]:
    return {member.value for member in enum_type}


@pytest.mark.parametrize("name", ["Species", "LifeStage", "RequirementType"])
def test_shared_vocabularies_equal_refdata(name: str) -> None:
    assert _values(getattr(vocab, name)) == _values(getattr(refdata_vocab, name))


def test_refdata_bases_are_subset_with_identical_strings() -> None:
    assert _values(refdata_vocab.Basis) <= _values(Basis)
    assert _values(Basis) - _values(refdata_vocab.Basis) == {"PER_100G_AS_FED", "PER_DAY"}


def test_units_are_canonical_only() -> None:
    assert _values(Unit) == {"g", "mg", "ug", "kcal", "kJ", "ratio"}
    assert _values(refdata_vocab.Unit) - {"IU"} <= _values(Unit)
    assert "IU" not in _values(Unit)


@pytest.mark.parametrize("name", ["MINIMUM_TYPES", "MAXIMUM_TYPES", "RATIO_TYPES"])
def test_requirement_type_groups_equal_refdata(name: str) -> None:
    ours = {member.value for member in getattr(vocab, name)}
    theirs = {member.value for member in getattr(refdata_vocab, name)}
    assert ours == theirs


def test_requirement_type_groups_partition_all_types() -> None:
    groups = (vocab.MINIMUM_TYPES, vocab.MAXIMUM_TYPES, vocab.RATIO_TYPES)
    assert set().union(*groups) == set(vocab.RequirementType)
    assert sum(len(group) for group in groups) == len(vocab.RequirementType)


def test_metabolic_exponent_matches_refdata_and_is_read_only() -> None:
    assert METABOLIC_EXPONENT == {Species.DOG: Decimal("0.75"), Species.CAT: Decimal("0.67")}
    assert {k.value: v for k, v in METABOLIC_EXPONENT.items()} == {
        k.value: v for k, v in refdata_vocab.METABOLIC_EXPONENT.items()
    }
    assert METABOLIC_BASIS == {Species.DOG: Basis.PER_KG_BW075, Species.CAT: Basis.PER_KG_BW067}
    with pytest.raises(TypeError):
        METABOLIC_EXPONENT[Species.DOG] = Decimal(1)  # type: ignore[index]


def test_kj_per_kcal_matches_refdata() -> None:
    from nutricalc.units import KJ_PER_KCAL

    assert KJ_PER_KCAL == refdata_vocab.KJ_PER_KCAL == Decimal("4.184")


@pytest.mark.parametrize(
    ("name", "values"),
    [
        ("PhysiologicalState", {"MAINTENANCE", "GROWTH", "GESTATION", "LACTATION"}),
        (
            "ValueKind",
            {
                "MEASURED",
                "CALCULATED",
                "BORROWED",
                "IMPUTED",
                "BELOW_LOD",
                "TRACE",
                "ZERO_BY_DEFINITION",
                "MISSING",
            },
        ),
        ("QualityGrade", {"A", "B", "C", "D"}),
        ("Completeness", {"COMPLETE", "PARTIAL", "UNKNOWN"}),
        ("WarningLevel", {"INFO", "NUTRITION_WARNING", "EXPERT_REQUIRED", "BLOCKED"}),
        ("EnergyStatus", {"OK", "EXPERT_REQUIRED", "BLOCKED"}),
        ("MeMethod", {"NRC2006_DOG_CF", "NRC2006_DOG_TDF", "MOD_ATWATER", "NRC2006_CAT"}),
    ],
)
def test_core_vocabularies(name: str, values: set[str]) -> None:
    assert _values(getattr(vocab, name)) == values


def test_ranks_cover_vocabularies_in_order() -> None:
    assert list(vocab.QUALITY_RANK) == list(QualityGrade)
    assert sorted(vocab.QUALITY_RANK.values()) == list(vocab.QUALITY_RANK.values())
    assert list(vocab.WARNING_LEVEL_RANK) == list(WarningLevel)
    assert set(vocab.BASIS_LABELS) == set(Basis)


def test_as_member() -> None:
    assert as_member(Species, Species.CAT, "druh") is Species.CAT
    assert as_member(Species, "DOG", "druh") is Species.DOG
    assert as_member(Species, refdata_vocab.Species.DOG, "druh") is Species.DOG
    with pytest.raises(InvalidInputError, match="druh"):
        as_member(Species, "HORSE", "druh")
    with pytest.raises(InvalidInputError):
        as_member(Species, "dog", "druh")
    with pytest.raises(TypeError):
        as_member(Species, 1, "druh")


def test_require_text() -> None:
    assert require_text("SYN_A", "kód") == "SYN_A"
    for empty in ("", "   "):
        with pytest.raises(ValidationError, match="kód"):
            require_text(empty, "kód")
    with pytest.raises(TypeError, match="kód"):
        require_text(None, "kód")


def test_worst_quality() -> None:
    assert worst_quality([QualityGrade.A, QualityGrade.C, QualityGrade.B]) == QualityGrade.C
    assert worst_quality([QualityGrade.A]) == QualityGrade.A
    assert worst_quality([]) is None


# --- Flag ------------------------------------------------------------------------


def test_flag_is_frozen_and_validated() -> None:
    flag = Flag(WarningLevel.INFO, "SOME_CODE_1", "Zpráva.")
    assert flag.subject is None
    with pytest.raises(FrozenInstanceError):
        flag.code = "OTHER"  # type: ignore[misc]
    assert Flag("BLOCKED", "X", "Zpráva.", subject="SYN_A").level is WarningLevel.BLOCKED  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (("FATAL", "X", "Zpráva."), InvalidInputError),
        ((WarningLevel.INFO, "lower_case", "Zpráva."), ValidationError),
        ((WarningLevel.INFO, "1X", "Zpráva."), ValidationError),
        ((WarningLevel.INFO, "X", "  "), ValidationError),
        ((WarningLevel.INFO, 1, "Zpráva."), TypeError),
        ((WarningLevel.INFO, "X", None), TypeError),
        ((WarningLevel.INFO, "X", "Zpráva.", ""), ValidationError),
        ((WarningLevel.INFO, "X", "Zpráva.", 1), TypeError),
    ],
)
def test_flag_rejects_invalid_fields(args: tuple[object, ...], error: type[Exception]) -> None:
    with pytest.raises(error):
        Flag(*args)  # type: ignore[arg-type]


def test_sorted_flags_dedups_and_orders_by_severity_then_code() -> None:
    info_b = Flag(WarningLevel.INFO, "B_CODE", "b")
    info_a = Flag(WarningLevel.INFO, "A_CODE", "a")
    blocked = Flag(WarningLevel.BLOCKED, "Z_CODE", "z")
    expert = Flag(WarningLevel.EXPERT_REQUIRED, "Y_CODE", "y")
    warning = Flag(WarningLevel.NUTRITION_WARNING, "X_CODE", "x", subject="SYN_B")
    warning_a = Flag(WarningLevel.NUTRITION_WARNING, "X_CODE", "x", subject="SYN_A")
    result = sorted_flags([info_b, warning, info_a, blocked, info_b, expert, warning_a])
    assert result == (blocked, expert, warning_a, warning, info_a, info_b)
    assert sorted_flags([]) == ()


# --- doplňky části 2 ---------------------------------------------------------------------------


def test_labels_cover_all_members() -> None:
    assert set(vocab.SPECIES_LABELS) == set(Species)
    assert set(vocab.LIFE_STAGE_LABELS) == set(vocab.LifeStage)


def test_gate_and_data_scope_vocabularies() -> None:
    assert _values(vocab.GateStatus) == {"OK", "EXPERT_REQUIRED", "BLOCKED"}
    assert _values(vocab.DataScope) == {"INGREDIENTS", "STANDARDS", "ENERGY", "RULES"}


def test_check_code() -> None:
    from nutricalc.flags import check_code

    assert check_code("TOXIC_FOR_SPECIES", "kód") == "TOXIC_FOR_SPECIES"
    for bad in ("", "toxic", "1CODE", "A-B", "A B"):
        with pytest.raises(ValidationError):
            check_code(bad, "kód")
    with pytest.raises(TypeError):
        check_code(1, "kód")
