"""Slovníky, převodní konstanty, nálezy a výstupní formáty."""

import json
from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

import refdata
from refdata import vocab
from refdata.findings import (
    ERROR,
    INFO,
    WARNING,
    Finding,
    count_by_severity,
    has_errors,
    merge_findings,
    sorted_findings,
)
from refdata.report import format_text, to_json
from refdata.vocab import (
    ADULT_STAGES,
    LIFE_STAGES,
    MAXIMUM_TYPES,
    METABOLIC_EXPONENT,
    MINIMUM_TYPES,
    RATIO_TYPES,
    SCALED_PAIRS,
    LifeStage,
    RequirementType,
    Species,
    Unit,
)


def test_version() -> None:
    assert refdata.__version__ == "0.1.0"


def test_conversion_constants() -> None:
    assert vocab.KCAL_PER_KG_DM == Decimal("4000")
    assert vocab.DM_TO_1000KCAL_FACTOR == Decimal("2.5")
    assert vocab.KJ_PER_KCAL == Decimal("4.184")
    assert vocab.MJ_TO_1000KCAL_FACTOR == Decimal("4.184")
    for value in (vocab.DM_TO_1000KCAL_FACTOR, vocab.MJ_TO_1000KCAL_FACTOR):
        assert isinstance(value, Decimal)


def test_species_exponents_and_scaled_pairs() -> None:
    assert METABOLIC_EXPONENT == {Species.DOG: Decimal("0.75"), Species.CAT: Decimal("0.67")}
    assert SCALED_PAIRS == {
        Species.DOG: (Decimal("95"), Decimal("110")),
        Species.CAT: (Decimal("75"), Decimal("100")),
    }
    with pytest.raises(TypeError):
        METABOLIC_EXPONENT[Species.DOG] = Decimal("1")  # type: ignore[index]


def test_life_stages_per_species() -> None:
    assert LIFE_STAGES[Species.DOG] == {
        LifeStage.ADULT_MAINTENANCE,
        LifeStage.ADULT_MAINTENANCE_LOW,
        LifeStage.EARLY_GROWTH_REPRO,
        LifeStage.LATE_GROWTH,
    }
    assert LIFE_STAGES[Species.CAT] == {
        LifeStage.ADULT_MAINTENANCE,
        LifeStage.ADULT_MAINTENANCE_LOW,
        LifeStage.GROWTH_REPRO,
    }
    assert ADULT_STAGES <= LIFE_STAGES[Species.DOG] & LIFE_STAGES[Species.CAT]


def test_requirement_type_groups_partition_all_types() -> None:
    assert MINIMUM_TYPES == {"MIN_RECOMMENDED", "MR", "AI", "RA"}
    assert MAXIMUM_TYPES == {"NUTRITIONAL_MAX", "LEGAL_MAX_EU", "SUL"}
    assert RATIO_TYPES == {"RATIO_MIN", "RATIO_MAX"}
    assert MINIMUM_TYPES | MAXIMUM_TYPES | RATIO_TYPES == set(RequirementType)
    assert not (MINIMUM_TYPES & MAXIMUM_TYPES or MINIMUM_TYPES & RATIO_TYPES)


def test_units_and_tokens() -> None:
    assert {unit.value for unit in Unit} == {"g", "mg", "ug", "kcal", "IU", "ratio"}
    assert Unit.IU not in vocab.CANONICAL_UNITS
    assert vocab.IU_ALLOWED_NUTRIENTS == {"VIT_A", "VIT_D", "VIT_E"}
    assert vocab.CONFIRM_TOKEN == "CONFIRMED_AS_PRINTED"


def test_finding_is_frozen_and_checks_severity() -> None:
    finding = Finding(ERROR, "E_X", "zpráva", (2,))
    with pytest.raises(FrozenInstanceError):
        finding.code = "E_Y"  # type: ignore[misc]
    with pytest.raises(ValueError):
        Finding("FATAL", "E_X", "zpráva")  # type: ignore[arg-type]


def test_count_merge_and_sort() -> None:
    first = Finding(WARNING, "W_B", "b", (3,))
    second = Finding(ERROR, "E_A", "a", (3,))
    third = Finding(INFO, "I_C", "c", (1,))
    assert count_by_severity([first, second, third, first]) == {"ERROR": 1, "WARNING": 2, "INFO": 1}
    assert count_by_severity([]) == {"ERROR": 0, "WARNING": 0, "INFO": 0}
    assert has_errors([first, second]) and not has_errors([first, third])
    assert sorted_findings([first, second, third]) == [third, second, first]
    assert merge_findings([first, second], [first, third]) == [third, second, first]


def test_format_text_in_czech_with_summary() -> None:
    findings = [
        Finding(ERROR, "E_A", "Opravte buňku.", (2,)),
        Finding(WARNING, "W_B", "Ověřte buňku.", (3, 5)),
        Finding(INFO, "I_C", "Pro informaci.", ()),
    ]
    text = format_text(findings, "Kontrola")
    assert text.startswith("Kontrola\n========\n")
    assert "CHYBA E_A (ř. 2): Opravte buňku." in text
    assert "VAROVÁNÍ W_B (ř. 3, 5): Ověřte buňku." in text
    assert "INFO I_C (soubor): Pro informaci." in text
    assert text.endswith("Souhrn: chyby (ERROR) 1, varování (WARNING) 1, informace (INFO) 1\n")
    assert "Žádné nálezy." in format_text([], "Kontrola")


def test_to_json_sorted_keys_and_unicode() -> None:
    findings = [
        Finding(ERROR, "E_A", "Chybí stránka.", (2,), ("TESTSTD", "1")),
        Finding(INFO, "I_C", "č"),
    ]
    output = to_json(findings)
    payload = json.loads(output)
    assert payload["summary"] == {"ERROR": 1, "INFO": 1, "WARNING": 0}
    assert payload["findings"][0] == {
        "code": "E_A",
        "key": ["TESTSTD", "1"],
        "lines": [2],
        "message": "Chybí stránka.",
        "severity": "ERROR",
    }
    assert payload["findings"][1]["key"] is None
    assert "Chybí stránka." in output  # ensure_ascii=False
    assert output == json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
