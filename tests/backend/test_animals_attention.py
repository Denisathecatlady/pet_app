"""Attention level of an animal (docs/09 §9.2, docs/08 §8.6) and age helpers."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from animals.models import (
    AnimalHealthCondition,
    HealthCondition,
    MuscleCondition,
    PhysiologicalState,
    Sex,
    TargetWeightStatus,
)
from animals.services import (
    BLOCKED,
    EXPERT_REQUIRED,
    INFO,
    OK,
    UNVERIFIED_TARGET_REASON,
    age_in_months,
    age_text,
    attention,
    owned_animals,
    summarize,
)

pytestmark = pytest.mark.django_db

ADULT = date(2020, 1, 1)


@pytest.fixture
def healthy(user, make_animal, make_measurement):
    """Adult dog with BCS 5, normal MCS, no target weight and no condition: level OK."""
    animal = make_animal(user, birth_date=ADULT)
    make_measurement(animal, bcs=5, mcs=MuscleCondition.NORMAL)
    return animal


def levels(result):
    return [reason.level for reason in result.reasons]


def add_condition(animal, code):
    AnimalHealthCondition.objects.create(
        animal=animal, condition=HealthCondition.objects.get(code=code)
    )


def test_healthy_animal_is_ok(healthy):
    result = attention(healthy)
    assert result == (OK, ())


@pytest.mark.parametrize(
    "state",
    [PhysiologicalState.GROWTH, PhysiologicalState.GESTATION, PhysiologicalState.LACTATION],
)
def test_growth_gestation_lactation_are_blocked(healthy, state):
    healthy.sex = Sex.FEMALE
    healthy.physiological_state = state
    healthy.save()

    level, reasons = attention(healthy)

    assert level == BLOCKED
    assert levels(attention(healthy)) == [BLOCKED]
    assert "nelze doporučit" in reasons[0].text


@pytest.mark.parametrize(
    "code",
    ["CKD", "LIVER_DISEASE", "PANCREATITIS", "HYPERLIPIDEMIA", "DIABETES_MELLITUS", "UROLITHIASIS"],
)
def test_blocked_conditions(healthy, code):
    add_condition(healthy, code)
    level, reasons = attention(healthy)
    assert level == BLOCKED
    name = HealthCondition.objects.get(code=code).name_cs
    assert f"„{name}“" in reasons[0].text


@pytest.mark.parametrize("code", ["FOOD_ALLERGY", "MEDICATION_AFFECTING_DIET", "OTHER_CHRONIC"])
def test_expert_required_conditions(healthy, code):
    add_condition(healthy, code)
    assert attention(healthy).level == EXPERT_REQUIRED


@pytest.mark.parametrize(
    ("bcs", "expected"),
    [
        (1, BLOCKED),
        (2, BLOCKED),
        (3, EXPERT_REQUIRED),
        (4, OK),
        (5, OK),
        (6, EXPERT_REQUIRED),
        (7, EXPERT_REQUIRED),
        (8, EXPERT_REQUIRED),
        (9, EXPERT_REQUIRED),
    ],
)
def test_latest_bcs(user, make_animal, make_measurement, bcs, expected):
    animal = make_animal(user, birth_date=ADULT)
    make_measurement(animal, bcs=bcs)
    result = attention(animal)
    assert result.level == expected
    if expected != OK:
        assert f"{bcs}/9" in result.reasons[0].text


def test_only_the_latest_bcs_counts(user, make_animal, make_measurement):
    animal = make_animal(user, birth_date=ADULT)
    today = timezone.localdate()
    make_measurement(animal, measured_on=today - timedelta(days=30), bcs=2)
    make_measurement(animal, measured_on=today - timedelta(days=10), bcs=5)
    make_measurement(animal, measured_on=today, bcs=None)  # newer, but without BCS

    assert attention(animal).level == OK


def test_no_bcs_is_info(user, make_animal, make_measurement):
    animal = make_animal(user, birth_date=ADULT)
    assert attention(animal).level == INFO
    make_measurement(animal, bcs=None)
    level, reasons = attention(animal)
    assert level == INFO
    assert "BCS" in reasons[0].text and "není zadané" in reasons[0].text


@pytest.mark.parametrize(
    ("mcs", "expected"),
    [
        (MuscleCondition.NORMAL, OK),
        (MuscleCondition.MILD_LOSS, EXPERT_REQUIRED),
        (MuscleCondition.MODERATE_LOSS, EXPERT_REQUIRED),
        (MuscleCondition.SEVERE_LOSS, EXPERT_REQUIRED),
    ],
)
def test_latest_mcs(user, make_animal, make_measurement, mcs, expected):
    animal = make_animal(user, birth_date=ADULT)
    make_measurement(animal, bcs=5, mcs=mcs)
    result = attention(animal)
    assert result.level == expected
    if expected != OK:
        assert MuscleCondition(mcs).label in result.reasons[0].text


def test_only_the_latest_mcs_counts(user, make_animal, make_measurement):
    animal = make_animal(user, birth_date=ADULT)
    today = timezone.localdate()
    make_measurement(animal, measured_on=today - timedelta(days=9), mcs=MuscleCondition.SEVERE_LOSS)
    make_measurement(animal, measured_on=today, bcs=5, mcs=MuscleCondition.NORMAL)
    assert attention(animal).level == OK


def test_young_animal_in_maintenance_needs_expert(user, make_animal, make_measurement):
    today = date(2026, 10, 20)
    animal = make_animal(user, birth_date=date(2025, 10, 21))  # 11 months
    make_measurement(animal, bcs=5)

    level, reasons = attention(animal, today=today)

    assert level == EXPERT_REQUIRED
    assert "méně než 12 měsíců" in reasons[0].text
    assert attention(animal, today=date(2026, 10, 21)).level == OK  # 12 months


def test_young_animal_in_growth_is_blocked_by_growth_only(user, make_animal, make_measurement):
    animal = make_animal(
        user, birth_date=date(2026, 6, 1), physiological_state=PhysiologicalState.GROWTH
    )
    make_measurement(animal, bcs=5)
    result = attention(animal, today=date(2026, 10, 20))
    assert levels(result) == [BLOCKED]


def test_unknown_birth_date_is_not_flagged_as_young(user, make_animal, make_measurement):
    animal = make_animal(user)
    make_measurement(animal, bcs=5)
    assert attention(animal).level == OK


def test_unverified_target_weight_is_info(healthy, vet_user):
    healthy.target_weight_kg = Decimal("18")
    healthy.save()
    level, reasons = attention(healthy)
    assert level == INFO
    assert reasons[0].text == UNVERIFIED_TARGET_REASON
    assert UNVERIFIED_TARGET_REASON == (  # docs/08 §8.7
        "Zadaná cílová hmotnost je orientační. "
        "Ideální hmotnost by měl potvrdit veterinář podle BCS."
    )

    healthy.target_weight_status = TargetWeightStatus.VET_CONFIRMED
    healthy.target_weight_confirmed_by = vet_user
    healthy.target_weight_confirmed_at = timezone.now()
    healthy.save()
    assert attention(healthy).level == OK


def test_highest_level_wins_and_reasons_are_sorted(user, make_animal, make_measurement):
    animal = make_animal(user, target_weight_kg=Decimal("20"), birth_date=ADULT)
    make_measurement(animal, bcs=7)
    add_condition(animal, "CKD")
    add_condition(animal, "FOOD_ALLERGY")

    result = attention(animal)

    assert result.level == BLOCKED
    assert levels(result) == [BLOCKED, EXPERT_REQUIRED, EXPERT_REQUIRED, INFO]


def test_reasons_do_not_promise_safety(user, make_animal, make_measurement):
    animal = make_animal(
        user,
        sex=Sex.FEMALE,
        physiological_state=PhysiologicalState.LACTATION,
        target_weight_kg=Decimal("20"),
        birth_date=timezone.localdate() - timedelta(days=100),
    )
    make_measurement(animal, bcs=2, mcs=MuscleCondition.MILD_LOSS)
    for code in ("CKD", "FOOD_ALLERGY"):
        add_condition(animal, code)

    texts = " ".join(reason.text for reason in attention(animal).reasons).lower()

    for phrase in ("bezpečn", "v pořádku", "kompletní", "vyvážen", "zaručen"):
        assert phrase not in texts


def test_summaries_use_prefetched_data(
    user, make_animal, make_measurement, django_assert_num_queries
):
    for name in ("A", "B", "C"):
        animal = make_animal(user, name=name)
        make_measurement(animal, bcs=5)
        add_condition(animal, "CKD")
    # 1 animals + 1 measurements + 1 conditions with their catalog entry.
    with django_assert_num_queries(3):
        summaries = summarize(owned_animals(user))
    assert [s.attention.level for s in summaries] == [BLOCKED] * 3


# --- Age --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("birth", "today", "months"),
    [
        (date(2026, 1, 15), date(2026, 1, 14), 0),
        (date(2026, 1, 15), date(2026, 2, 15), 1),
        (date(2026, 1, 31), date(2026, 2, 28), 0),
        (date(2024, 2, 29), date(2025, 2, 28), 11),
        (date(2024, 2, 29), date(2025, 3, 1), 12),
        (date(2020, 5, 1), date(2026, 10, 20), 77),
    ],
)
def test_age_in_months(birth, today, months):
    assert age_in_months(birth, today) == months


@pytest.mark.parametrize(
    ("birth", "estimated", "text"),
    [
        (None, False, "neznámý"),
        (date(2026, 10, 1), False, "méně než 1 měsíc"),
        (date(2026, 9, 1), False, "1 měsíc"),
        (date(2026, 7, 1), False, "3 měsíce"),
        (date(2026, 1, 1), False, "9 měsíců"),
        (date(2025, 10, 1), False, "1 rok"),
        (date(2023, 10, 1), True, "asi 3 roky"),
        (date(2016, 10, 1), False, "10 let"),
    ],
)
def test_age_text(user, make_animal, birth, estimated, text):
    animal = make_animal(user, birth_date=birth, birth_date_estimated=estimated)
    assert age_text(animal, today=date(2026, 10, 20)) == text
